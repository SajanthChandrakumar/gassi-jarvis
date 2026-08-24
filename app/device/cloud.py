"""Cloud-side queue for the outbound Mac capability agent.

The gateway owns action intent, approvals, leases, and terminal metadata.  It
never imports the local executor/security/vision modules.  A Mac agent polls
this queue over an authenticated outbound connection and reports only typed
events back.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import (
    ActionPayload,
    ActionStatus,
    ActionType,
    DeviceAction,
    DeviceConnectionStatus,
    DeviceDecision,
    DeviceLifecycle,
    DeviceResult,
    DeviceStatus,
    DeviceUnavailable,
)


OFFLINE_SECONDS = 10.0
DELIVERY_LEASE_SECONDS = 30.0
APPROVAL_TTL_SECONDS = 300.0
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024


def _utc(value: float | None = None) -> datetime:
    return datetime.fromtimestamp(value if value is not None else time.time(), tz=timezone.utc)


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item),
    )


class DeviceGateway:
    """Durable, single-device cloud queue and lifecycle repository."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        device_id: str | None = None,
        clock: Callable[[], float] | None = None,
        vision_analyzer: Callable[[str, bytes], str] | None = None,
    ) -> None:
        configured = db_path or os.environ.get("JARVIS_CLOUD_DB_PATH", "jarvis_cloud.sqlite3")
        self.path = str(configured)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.device_id = (device_id or os.environ.get("JARVIS_DEVICE_ID", "local-mac")).strip()
        if not self.device_id:
            raise ValueError("device id is required")
        self.clock = clock or time.time
        self.device_token = os.environ.get("JARVIS_DEVICE_TOKEN", "")
        self.vision_analyzer = vision_analyzer
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS device_heartbeat (
                    device_id TEXT PRIMARY KEY,
                    last_seen REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_actions (
                    action_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    lease_until REAL,
                    approval_deadline REAL,
                    decision_json TEXT,
                    result_json TEXT,
                    analysis TEXT
                );
                """
            )

    # ------------------------------------------------------------------
    # Device reachability and durable action creation
    # ------------------------------------------------------------------

    def _now(self) -> float:
        return float(self.clock())

    def _configured_device(self, device_id: str) -> None:
        if device_id != self.device_id:
            raise ValueError("device id mismatch")

    def _last_seen(self) -> float | None:
        row = self._db.execute(
            "SELECT last_seen FROM device_heartbeat WHERE device_id = ?", (self.device_id,)
        ).fetchone()
        return float(row["last_seen"]) if row else None

    def status(self, *, now: float | None = None) -> DeviceStatus:
        now = self._now() if now is None else float(now)
        last_seen = self._last_seen()
        online = last_seen is not None and now - last_seen <= OFFLINE_SECONDS
        return DeviceStatus(
            device_id=self.device_id,
            available=online,
            status=DeviceConnectionStatus.ONLINE if online else DeviceConnectionStatus.OFFLINE,
            last_seen_at=_utc(last_seen) if last_seen is not None else None,
            unavailable_reason=None if online else "Mac agent is offline or has not connected yet",
        )

    def heartbeat(self, device_id: str, *, now: float | None = None) -> DeviceStatus:
        self._configured_device(device_id)
        stamp = self._now() if now is None else float(now)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO device_heartbeat(device_id,last_seen) VALUES (?,?) "
                "ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen",
                (device_id, stamp),
            )
        return self.status(now=stamp)

    def _next_id(self) -> str:
        return f"device-{uuid.uuid4().hex}"

    def queue_action(
        self,
        action_type: str | ActionType,
        payload: str,
        *,
        action_id: str | None = None,
        device_id: str | None = None,
        requires_approval: bool = False,
        tainted: bool = False,
    ) -> DeviceAction | DeviceUnavailable:
        target = device_id or self.device_id
        self._configured_device(target)
        try:
            kind = ActionType(action_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported device action type") from exc
        if not isinstance(payload, str) or not payload.strip():
            raise ValueError("device action payload must be a non-empty string")
        if not self.status().available:
            return DeviceUnavailable(reason="Mac agent is offline", action_id=action_id)
        action = DeviceAction(
            action_id=action_id or self._next_id(),
            device_id=target,
            payload=ActionPayload(action_type=kind, payload=payload, tainted=tainted),
            requires_approval=requires_approval,
            action_type=kind,
        )
        stamp = self._now()
        encoded = _json(action)
        intent = _json(
            {
                "device_id": action.device_id,
                "payload": action.payload,
                "requires_approval": action.requires_approval,
            }
        )
        digest = hashlib.sha256(intent.encode("utf-8")).hexdigest()
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT action_json, payload_hash FROM device_actions WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise ValueError("payload hash substitution for action")
                return DeviceAction.model_validate(json.loads(existing["action_json"]))
            self._db.execute(
                """INSERT INTO device_actions
                   (action_id,device_id,action_json,payload_hash,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    action.action_id,
                    target,
                    encoded,
                    digest,
                    ActionStatus.QUEUED.value,
                    stamp,
                    stamp,
                ),
            )
        return action

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def _row_action(self, row: sqlite3.Row) -> DeviceAction:
        return DeviceAction.model_validate(json.loads(row["action_json"]))

    def _lifecycle(self, row: sqlite3.Row) -> DeviceLifecycle:
        action = self._row_action(row)
        decision = DeviceDecision.model_validate(json.loads(row["decision_json"])) if row["decision_json"] else None
        result = DeviceResult.model_validate(json.loads(row["result_json"])) if row["result_json"] else None
        unavailable = None
        if not self.status().available and result is None and row["status"] not in {
            ActionStatus.SUCCEEDED.value,
            ActionStatus.FAILED.value,
            ActionStatus.REJECTED.value,
            ActionStatus.EXPIRED.value,
        }:
            unavailable = DeviceUnavailable(reason="Mac agent is offline", action_id=action.action_id)
        return DeviceLifecycle(
            action=action,
            decision=decision,
            result=result,
            unavailable=unavailable,
            status=ActionStatus(row["status"]),
            updated_at=_utc(float(row["updated_at"])),
            analysis=row["analysis"] if "analysis" in row.keys() else None,
        )

    def _get_row(self, action_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM device_actions WHERE action_id = ?", (action_id,)
        ).fetchone()

    def get_action(self, action_id: str) -> DeviceLifecycle | None:
        row = self._get_row(action_id)
        if row is not None:
            row = self._mark_expired_if_needed(row, now=self._now())
        return self._lifecycle(row) if row else None

    def _mark_expired_if_needed(self, row: sqlite3.Row, *, now: float) -> sqlite3.Row:
        deadline = row["approval_deadline"]
        if row["status"] == ActionStatus.AWAITING_APPROVAL.value and deadline is not None and now >= deadline:
            with self._lock, self._db:
                self._db.execute(
                    "UPDATE device_actions SET status=?, updated_at=?, lease_until=NULL WHERE action_id=?",
                    (ActionStatus.EXPIRED.value, now, row["action_id"]),
                )
            return self._get_row(row["action_id"]) or row
        return row

    def decide(self, action_id: str, *, approved: bool, reason: str | None = None) -> DeviceLifecycle:
        row = self._get_row(action_id)
        if row is None:
            raise KeyError("unknown action id")
        now = self._now()
        row = self._mark_expired_if_needed(row, now=now)
        if row["status"] == ActionStatus.EXPIRED.value:
            return self._lifecycle(row)
        if row["status"] != ActionStatus.AWAITING_APPROVAL.value:
            if row["decision_json"]:
                current = DeviceDecision.model_validate(json.loads(row["decision_json"]))
                if current.approved != approved or current.reason != reason:
                    raise ValueError("decision already recorded")
                return self._lifecycle(row)
            raise ValueError("action is not awaiting approval")
        decision = DeviceDecision(action_id=action_id, approved=approved, reason=reason)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE device_actions SET decision_json=?, status=?, updated_at=? WHERE action_id=?",
                (_json(decision), ActionStatus.APPROVED.value if approved else ActionStatus.DENIED.value, now, action_id),
            )
        return self.get_action(action_id)  # type: ignore[return-value]

    def poll(self, device_id: str) -> dict[str, list[dict[str, Any]]]:
        self._configured_device(device_id)
        now = self._now()
        self.heartbeat(device_id, now=now)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE device_actions SET status=?, updated_at=?, lease_until=NULL "
                "WHERE status=? AND approval_deadline IS NOT NULL AND approval_deadline <= ?",
                (ActionStatus.EXPIRED.value, now, ActionStatus.AWAITING_APPROVAL.value, now),
            )
            self._db.execute(
                "UPDATE device_actions SET lease_until=NULL, status=? "
                "WHERE status=? AND lease_until IS NOT NULL AND lease_until <= ?",
                (ActionStatus.QUEUED.value, ActionStatus.DELIVERED.value, now),
            )
            rows = self._db.execute(
                "SELECT * FROM device_actions WHERE device_id=? AND status=? "
                "AND (lease_until IS NULL OR lease_until <= ?) ORDER BY created_at LIMIT 10",
                (device_id, ActionStatus.QUEUED.value, now),
            ).fetchall()
            for row in rows:
                self._db.execute(
                    "UPDATE device_actions SET status=?, lease_until=?, updated_at=? WHERE action_id=?",
                    (ActionStatus.DELIVERED.value, now + DELIVERY_LEASE_SECONDS, now, row["action_id"]),
                )
            decisions = self._db.execute(
                "SELECT * FROM device_actions WHERE device_id=? AND status IN (?,?) "
                "AND decision_json IS NOT NULL ORDER BY updated_at LIMIT 10",
                (device_id, ActionStatus.APPROVED.value, ActionStatus.DENIED.value),
            ).fetchall()
        actions = [self._row_action(row).model_dump(mode="json") for row in rows]
        return {
            "actions": actions,
            "decisions": [
                DeviceDecision.model_validate(json.loads(row["decision_json"])).model_dump(mode="json")
                for row in decisions
            ],
        }

    # ------------------------------------------------------------------
    # Authenticated agent events
    # ------------------------------------------------------------------

    def record_event(self, action_id: str, device_token: str | None, event: dict[str, Any]) -> DeviceLifecycle:
        """Apply an authenticated agent event.

        Authentication is enforced by :mod:`app.device.routes`; the token
        parameter remains explicit here so callers cannot accidentally forget
        that this is an agent-only operation.
        """
        expected_token = self.device_token or os.environ.get("JARVIS_DEVICE_TOKEN", "")
        if not expected_token or not device_token or not secrets.compare_digest(device_token, expected_token):
            raise PermissionError("device token required")
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        row = self._get_row(action_id)
        if row is None:
            raise KeyError("unknown action id")
        kind = event.get("type")
        if kind == "approval_required":
            now = self._now()
            row = self._mark_expired_if_needed(row, now=now)
            if row["status"] == ActionStatus.EXPIRED.value:
                return self._lifecycle(row)
            if row["status"] not in {ActionStatus.QUEUED.value, ActionStatus.DELIVERED.value, ActionStatus.AWAITING_APPROVAL.value}:
                return self._lifecycle(row)
            with self._lock, self._db:
                self._db.execute(
                    "UPDATE device_actions SET status=?, approval_deadline=?, lease_until=NULL, updated_at=? WHERE action_id=?",
                    (ActionStatus.AWAITING_APPROVAL.value, now + APPROVAL_TTL_SECONDS, now, action_id),
                )
            return self.get_action(action_id)  # type: ignore[return-value]
        if kind != "result":
            raise ValueError("unknown device event type")
        raw_result = event.get("result")
        if not isinstance(raw_result, dict):
            raise ValueError("result event requires a result object")
        result = DeviceResult.model_validate(raw_result)
        if result.action_id not in {None, action_id}:
            raise ValueError("result action id mismatch")
        result.action_id = action_id
        now = self._now()
        row = self._mark_expired_if_needed(row, now=now)
        existing = row
        if existing and existing["result_json"]:
            stored_result = DeviceResult.model_validate(json.loads(existing["result_json"]))
            if stored_result.model_dump(exclude={"finished_at"}) != result.model_dump(exclude={"finished_at"}):
                raise ValueError("terminal result already recorded")
            return self._lifecycle(existing)
        allowed_statuses = {
            ActionStatus.DELIVERED.value,
            ActionStatus.APPROVED.value,
            ActionStatus.RUNNING.value,
        }
        if row["status"] not in allowed_statuses:
            raise ValueError(
                f"cannot record result before delivery or after terminal state "
                f"(action is {row['status']})"
            )
        image_b64 = event.get("screenshot_b64")
        analysis: str | None = None
        if image_b64 is not None:
            action = self._row_action(row)
            if action.action_type != ActionType.TAKE_SCREENSHOT:
                raise ValueError("screenshot is only valid for screenshot actions")
            if not isinstance(image_b64, str):
                raise ValueError("screenshot must be base64 text")
            try:
                # encoded length bound is checked before decoding to avoid an
                # attacker allocating an unbounded byte string.
                if len(image_b64) > ((MAX_SCREENSHOT_BYTES + 2) // 3) * 4 + 4:
                    raise ValueError("screenshot exceeds size limit")
                image = base64.b64decode(image_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("invalid screenshot payload") from exc
            if len(image) > MAX_SCREENSHOT_BYTES:
                raise ValueError("screenshot exceeds size limit")
            if self.vision_analyzer is not None:
                # The bytes are deliberately scoped to this call and never
                # enter SQLite, action models, or log records.
                analysis = self.vision_analyzer(self._row_action(row).command, image)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE device_actions SET status=?, result_json=?, analysis=?, lease_until=NULL, updated_at=? WHERE action_id=?",
                (result.status, _json(result), analysis, now, action_id),
            )
        return self.get_action(action_id)  # type: ignore[return-value]

    def wait_for_result(
        self, action_id: str, *, timeout: float = 0.5, interval: float = 0.05
    ) -> DeviceLifecycle | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            lifecycle = self.get_action(action_id)
            if lifecycle is None or lifecycle.result is not None:
                return lifecycle
            if time.monotonic() >= deadline:
                return lifecycle
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "DeviceGateway":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = [
    "APPROVAL_TTL_SECONDS",
    "DELIVERY_LEASE_SECONDS",
    "DeviceGateway",
    "MAX_SCREENSHOT_BYTES",
    "OFFLINE_SECONDS",
]

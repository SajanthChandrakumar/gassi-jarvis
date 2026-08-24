"""Durable, local state for the outbound Mac device agent.

The cloud is not the source of truth for an action once the Mac has accepted
it.  Payloads and their hashes stay local so a redelivery can never replace a
stored command, and terminal results are committed before they are reported.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import DeviceAction, DeviceDecision, DeviceResult


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_payload(payload: Any) -> str:
    """Return a stable SHA-256 digest for an action payload."""

    if isinstance(payload, DeviceAction):
        payload = payload.payload
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    encoded = _json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class StoredPayload:
    action: DeviceAction
    payload_hash: str
    status: str
    lease_until: float | None
    approval_deadline: float | None


class AgentState:
    """Small SQLite repository for one local Mac identity."""

    def __init__(self, path: str | Path = "jarvis_device_agent.sqlite3") -> None:
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
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
                CREATE TABLE IF NOT EXISTS pending_payloads (
                    action_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL,
                    approval_deadline REAL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    action_id TEXT PRIMARY KEY,
                    decision_json TEXT NOT NULL,
                    decided_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS terminal_results (
                    action_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_tombstones (
                    action_id TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    recorded_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def hash_payload(payload: Any) -> str:
        return hash_payload(payload)

    def payload_hash(self, action_id: str) -> str | None:
        row = self._db.execute(
            "SELECT payload_hash FROM pending_payloads WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            row = self._db.execute(
                "SELECT payload_hash FROM replay_tombstones WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return row["payload_hash"] if row else None

    def save_payload(self, action: DeviceAction) -> bool:
        """Store a payload once; reject same-id substitutions."""

        action = DeviceAction.model_validate(action)
        digest = hash_payload(action.payload)
        action_json = _json(action.model_dump(mode="json"))
        with self._lock, self._db:
            tombstone = self._db.execute(
                "SELECT payload_hash FROM replay_tombstones WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            if tombstone:
                if tombstone["payload_hash"] != digest:
                    raise ValueError("payload hash substitution for replayed action")
                return False

            existing = self._db.execute(
                "SELECT payload_hash FROM pending_payloads WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != digest:
                    raise ValueError("payload hash substitution for pending action")
                return False

            self._db.execute(
                """
                INSERT INTO pending_payloads
                    (action_id, device_id, payload_json, payload_hash, status,
                     created_at, requires_approval)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id,
                    action.device_id,
                    action_json,
                    digest,
                    str(action.status),
                    action.created_at.isoformat(),
                    int(action.requires_approval),
                ),
            )
            return True

    def _row_to_payload(self, row: sqlite3.Row | None) -> StoredPayload | None:
        if row is None:
            return None
        return StoredPayload(
            action=DeviceAction.model_validate(json.loads(row["payload_json"])),
            payload_hash=row["payload_hash"],
            status=row["status"],
            lease_until=row["lease_until"],
            approval_deadline=row["approval_deadline"],
        )

    def get_payload(self, action_id: str) -> DeviceAction | None:
        row = self._db.execute(
            "SELECT * FROM pending_payloads WHERE action_id = ?", (action_id,)
        ).fetchone()
        stored = self._row_to_payload(row)
        return stored.action if stored else None

    get_pending = get_payload

    def get_stored(self, action_id: str) -> StoredPayload | None:
        row = self._db.execute(
            "SELECT * FROM pending_payloads WHERE action_id = ?", (action_id,)
        ).fetchone()
        return self._row_to_payload(row)

    def update_status(self, action_id: str, status: str, *, approval_deadline: float | None = None) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE pending_payloads SET status = ?, approval_deadline = ? WHERE action_id = ?",
                (str(status), approval_deadline, action_id),
            )

    def claim_delivery(self, action_id: str, *, now: float, lease_seconds: float = 30.0) -> DeviceAction | None:
        """Claim one payload until its lease expires."""

        with self._lock, self._db:
            row = self._db.execute(
                "SELECT * FROM pending_payloads WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None or self._db.execute(
                "SELECT 1 FROM replay_tombstones WHERE action_id = ?", (action_id,)
            ).fetchone():
                return None
            lease_until = row["lease_until"]
            if lease_until is not None and lease_until > now:
                return None
            self._db.execute(
                "UPDATE pending_payloads SET lease_until = ? WHERE action_id = ?",
                (now + lease_seconds, action_id),
            )
            return DeviceAction.model_validate(json.loads(row["payload_json"]))

    def release_delivery(self, action_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE pending_payloads SET lease_until = NULL WHERE action_id = ?",
                (action_id,),
            )

    def save_decision(self, decision: DeviceDecision) -> bool:
        decision = DeviceDecision.model_validate(decision)
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT decision_json FROM decisions WHERE action_id = ?",
                (decision.action_id,),
            ).fetchone()
            encoded = _json(decision.model_dump(mode="json"))
            if existing:
                return existing["decision_json"] == encoded
            self._db.execute(
                "INSERT INTO decisions (action_id, decision_json, decided_at) VALUES (?, ?, ?)",
                (decision.action_id, encoded, decision.decided_at.isoformat()),
            )
            return True

    def get_decision(self, action_id: str) -> DeviceDecision | None:
        row = self._db.execute(
            "SELECT decision_json FROM decisions WHERE action_id = ?", (action_id,)
        ).fetchone()
        return DeviceDecision.model_validate(json.loads(row["decision_json"])) if row else None

    def get_terminal_result(self, action_id: str) -> DeviceResult | None:
        row = self._db.execute(
            "SELECT result_json FROM terminal_results WHERE action_id = ?", (action_id,)
        ).fetchone()
        return DeviceResult.model_validate(json.loads(row["result_json"])) if row else None

    get_result = get_terminal_result

    def record_terminal(
        self,
        result: DeviceResult,
        *,
        payload_hash_value: str | None = None,
        recorded_at: float = 0.0,
    ) -> tuple[DeviceResult, bool]:
        """Atomically store a terminal result and replay tombstone."""

        result = DeviceResult.model_validate(result)
        if not result.action_id:
            raise ValueError("terminal result requires an action_id")
        with self._lock, self._db:
            existing = self._db.execute(
                "SELECT payload_hash, result_json FROM terminal_results WHERE action_id = ?",
                (result.action_id,),
            ).fetchone()
            if existing:
                if payload_hash_value and existing["payload_hash"] != payload_hash_value:
                    raise ValueError("payload hash substitution for terminal action")
                return DeviceResult.model_validate(json.loads(existing["result_json"])), False

            known_hash = self.payload_hash(result.action_id)
            digest = payload_hash_value or known_hash
            if digest is None:
                raise ValueError("cannot record terminal result without payload hash")
            encoded = _json(result.model_dump(mode="json"))
            self._db.execute(
                "INSERT INTO terminal_results (action_id, payload_hash, result_json, recorded_at) VALUES (?, ?, ?, ?)",
                (result.action_id, digest, encoded, recorded_at),
            )
            self._db.execute(
                "INSERT OR IGNORE INTO replay_tombstones (action_id, payload_hash, recorded_at) VALUES (?, ?, ?)",
                (result.action_id, digest, recorded_at),
            )
            self._db.execute(
                "UPDATE pending_payloads SET status = ?, lease_until = NULL WHERE action_id = ?",
                (result.status, result.action_id),
            )
            return result, True

    record_terminal_result = record_terminal

    def is_tombstoned(self, action_id: str, payload_hash_value: str | None = None) -> bool:
        row = self._db.execute(
            "SELECT payload_hash FROM replay_tombstones WHERE action_id = ?", (action_id,)
        ).fetchone()
        return bool(row and (payload_hash_value is None or row["payload_hash"] == payload_hash_value))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "AgentState":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


SQLiteAgentState = AgentState


__all__ = ["AgentState", "SQLiteAgentState", "StoredPayload", "hash_payload"]

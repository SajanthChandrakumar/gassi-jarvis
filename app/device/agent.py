"""Outbound-only Mac capability agent.

This module is deliberately a client, not a server.  It makes authenticated
requests to the cloud gateway, stores accepted actions locally, and executes
only the payload that was originally delivered for an action id.  The cloud
cannot replace a payload after delivery and an approval contains no executable
data.

The default transport uses only :mod:`urllib`; keeping the agent dependency
free makes it suitable for a small launchd-managed process on macOS.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import ActionPayload, ActionType, DeviceAction, DeviceDecision, DeviceResult
from .state import AgentState


POLL_INTERVAL_SECONDS = 2.0
DELIVERY_LEASE_SECONDS = 30.0
APPROVAL_TTL_SECONDS = 300.0
MAX_BACKOFF_SECONDS = 30.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024

Transport = Callable[[str, str, Mapping[str, str], Any], Any]
Report = Callable[[dict[str, Any]], Any]


def validate_agent_url(url: str) -> bool:
    """Allow HTTPS, plus HTTP only for an explicit loopback host.

    The agent must never silently downgrade a remote cloud connection to
    plaintext HTTP.  ``localhost`` is intentionally accepted for the
    two-process compatibility mode.
    """

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme == "https":
        return bool(
            parsed.hostname
            and parsed.netloc
            and parsed.username is None
            and parsed.password is None
        )
    if parsed.scheme != "http" or not parsed.hostname or not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    return parsed.hostname.lower().rstrip(".") in {"localhost", "127.0.0.1", "::1"}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def current_boot_identity() -> str:
    """Return a boot-scoped identity, or a process identity on failure.

    Linux exposes a stable boot UUID.  macOS exposes the boot time through
    ``kern.boottime``.  If either platform mechanism is unavailable, a random
    process identity intentionally invalidates all pending approvals after a
    restart instead of risking execution under a new monotonic epoch.
    """

    if sys.platform.startswith("linux"):
        try:
            value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            if value:
                return f"linux:{value}"
        except (OSError, UnicodeError):
            pass
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "kern.boottime"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            value = result.stdout.strip()
            if result.returncode == 0 and value:
                return f"darwin:{value}"
        except (OSError, subprocess.SubprocessError):
            pass
    return f"process:{uuid.uuid4().hex}"


class MacAgent:
    """One outbound Mac agent with durable, replay-safe action handling."""

    def __init__(
        self,
        cloud_url: str,
        device_token: str,
        *,
        device_id: str = "local-mac",
        state_path: str | Path = "jarvis_device_agent.sqlite3",
        executor: Any | None = None,
        transport: Transport | None = None,
        report: Report | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        boot_identity: str | Callable[[], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_timeout: float = 15.0,
    ) -> None:
        if not validate_agent_url(cloud_url):
            raise ValueError("cloud URL must use HTTPS, except for loopback HTTP")
        if not device_token or not device_token.strip():
            raise ValueError("device token is required")
        if not device_id or not device_id.strip():
            raise ValueError("device id is required")

        self.cloud_url = cloud_url.rstrip("/")
        self.device_token = device_token
        self.device_id = device_id
        self.state = AgentState(state_path)
        self.transport = transport or self._urllib_transport
        self.report = report
        self.monotonic = monotonic
        if callable(boot_identity):
            boot_identity = boot_identity()
        self.boot_identity = boot_identity or current_boot_identity()
        self.sleep = sleep
        self.request_timeout = request_timeout
        self.poll_interval = POLL_INTERVAL_SECONDS
        self.delivery_lease = DELIVERY_LEASE_SECONDS
        self.approval_ttl = APPROVAL_TTL_SECONDS
        self.max_backoff = MAX_BACKOFF_SECONDS
        self._failure_count = 0
        self._stop = threading.Event()

        # Importing the executor is the point at which Mac-only dependencies
        # enter the process.  Cloud modules can import the contracts without
        # importing this module or any local capability implementation.
        if executor is None:
            from .executor import MacExecutor

            executor = MacExecutor()
        self.executor = executor

    # ------------------------------------------------------------------
    # Cloud transport
    # ------------------------------------------------------------------

    @property
    def poll_url(self) -> str:
        return f"{self.cloud_url}/api/device-agent/poll"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.device_token}",
            "X-Jarvis-Device-ID": self.device_id,
        }

    def _urllib_transport(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Any = None,
    ) -> Any:
        encoded = None
        request_headers = dict(headers)
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=encoded, headers=request_headers, method=method)
        with urlopen(request, timeout=self.request_timeout) as response:
            if getattr(response, "status", 200) == 204:
                return {}
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("cloud response exceeds size limit")
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _request(self, method: str, url: str, body: Any = None) -> Any:
        # The injectable transport is useful for tests and the localhost
        # compatibility runner.  It receives the same auth headers as urllib.
        return self.transport(method, url, self._headers(), body)

    # ------------------------------------------------------------------
    # Durable execution and approval state machine
    # ------------------------------------------------------------------

    @staticmethod
    def _action_type(action: DeviceAction) -> str:
        payload = action.payload
        action_type = payload.action_type if isinstance(payload, ActionPayload) else action.action_type
        return str(_enum_value(action_type or ""))

    @staticmethod
    def _command(action: DeviceAction) -> str:
        return action.command

    def _needs_approval(self, action: DeviceAction) -> bool:
        payload = action.payload
        action_type = self._action_type(action)
        threat_level: int | None = None
        if action_type == ActionType.SHELL_COMMAND.value:
            try:
                # Reclassification is intentionally local and authoritative.
                threat_level = int(self.executor.security_level(self._command(action)))
            except Exception:
                # A classifier failure fails closed.
                return True
        if action.requires_approval:
            return True
        if isinstance(payload, ActionPayload) and payload.tainted:
            return True
        return threat_level is not None and threat_level >= 2

    def _report_event(self, event: dict[str, Any]) -> None:
        """Report without making execution depend on cloud availability."""

        try:
            if self.report is not None:
                self.report(event)
            else:
                action_id = str(event.get("action_id", ""))
                if not action_id:
                    return
                self._request(
                    "POST",
                    f"{self.cloud_url}/api/device-agent/actions/{action_id}/events",
                    event,
                )
        except Exception:
            # The terminal result is already durable.  A later cloud poll can
            # redeliver the action and receive the same result without re-run.
            return

    def _report_result(self, result: DeviceResult, screenshot: bytes | None = None) -> None:
        event: dict[str, Any] = {
            "type": "result",
            "action_id": result.action_id,
            "result": result.model_dump(mode="json"),
        }
        if screenshot is not None:
            # Screenshot bytes are bounded, sent only in memory, and never
            # included in AgentState.  Do not log this event.
            event["screenshot_b64"] = base64.b64encode(screenshot).decode("ascii")
        self._report_event(event)

    def _report_approval_required(self, action_id: str) -> None:
        self._report_event(
            {
                "type": "approval_required",
                "action_id": action_id,
                "status": "awaiting_approval",
            }
        )

    def _approval_expired(self, stored: Any) -> bool:
        """Fail closed when a deadline is missing, stale, or from another boot."""

        return (
            stored.approval_deadline is None
            or stored.approval_boot_identity != self.boot_identity
            or self.monotonic() >= stored.approval_deadline
        )

    def _expire_waiting(self, stored: Any) -> DeviceResult | None:
        if stored.status != "awaiting_approval" or not self._approval_expired(stored):
            return None
        return self._finish(
            DeviceResult(
                action_id=stored.action.action_id,
                status="expired",
                action="approval_expired",
                error="approval TTL expired or boot identity changed",
            )
        )

    def _retry_waiting_approvals(self) -> None:
        for stored in self.state.awaiting_approvals():
            if self._expire_waiting(stored) is None:
                self._report_approval_required(stored.action.action_id)

    def _finish(self, result: DeviceResult, *, screenshot: bytes | None = None) -> DeviceResult:
        terminal, _new = self.state.record_terminal(
            result,
            recorded_at=self.monotonic(),
        )
        self._report_result(terminal, screenshot if _new else None)
        return terminal

    def _reject_without_storage(self, action_id: str, reason: str) -> DeviceResult:
        result = DeviceResult(
            action_id=action_id,
            status="rejected",
            action="device_action_rejected",
            error=reason,
        )
        self._report_result(result)
        return result

    def _execute(self, action: DeviceAction, *, force: bool) -> tuple[DeviceResult, bytes | None]:
        action_type = self._action_type(action)
        payload = self._command(action)
        try:
            if action_type == ActionType.SHELL_COMMAND.value:
                output = self.executor.execute_shell_command(payload, force=force)
                return (
                    DeviceResult(
                        action_id=action.action_id,
                        status="succeeded",
                        action="shell_command",
                        output=str(output),
                    ),
                    None,
                )
            if action_type == ActionType.OPEN_APP.value:
                raw = self.executor.open_app(payload)
                result = raw if isinstance(raw, DeviceResult) else DeviceResult.model_validate(raw)
                return DeviceResult(
                    action_id=action.action_id,
                    status=result.status,
                    action=result.action,
                    output=result.output,
                    error=result.error,
                ), None
            if action_type == ActionType.TAKE_SCREENSHOT.value:
                image = self.executor.capture_screen()
                if not isinstance(image, (bytes, bytearray)):
                    raise TypeError("screenshot executor must return bytes")
                if len(image) > MAX_SCREENSHOT_BYTES:
                    return (
                        DeviceResult(
                            action_id=action.action_id,
                            status="failed",
                            action="take_screenshot",
                            error="screenshot exceeds size limit",
                        ),
                        None,
                    )
                return (
                    DeviceResult(
                        action_id=action.action_id,
                        status="succeeded",
                        action="take_screenshot",
                        output="Screenshot captured.",
                    ),
                    bytes(image),
                )
            return (
                DeviceResult(
                    action_id=action.action_id,
                    status="rejected",
                    action="unsupported_device_action",
                    error="unsupported device action type",
                ),
                None,
            )
        except Exception as error:
            return (
                DeviceResult(
                    action_id=action.action_id,
                    status="failed",
                    action=action_type or "device_action",
                    error=str(error),
                ),
                None,
            )

    def _execute_stored(self, action: DeviceAction, *, force: bool) -> DeviceResult:
        self.state.update_status(action.action_id, "running")
        result, screenshot = self._execute(action, force=force)
        return self._finish(result, screenshot=screenshot)

    def receive_action(self, action: DeviceAction | Mapping[str, Any]) -> DeviceResult | str:
        """Accept one cloud directive and execute or await approval.

        The action payload is saved before any execution.  Subsequent
        deliveries with the same id can only refer to that saved payload.
        """

        action = DeviceAction.model_validate(action)
        if action.device_id != self.device_id:
            return self._reject_without_storage(action.action_id, "device id mismatch")

        self.state.save_payload(action)
        terminal = self.state.get_terminal_result(action.action_id)
        if terminal is not None:
            self._report_result(terminal)
            return terminal

        stored = self.state.get_stored(action.action_id)
        if stored is None:
            return self._reject_without_storage(action.action_id, "action was not stored")
        if stored.status == "awaiting_approval":
            expired = self._expire_waiting(stored)
            if expired is not None:
                return expired
            # Persisted awaiting state is also the retry outbox for the
            # approval-required event.  Reporting is idempotent server-side.
            self._report_approval_required(stored.action.action_id)
            return stored.status
        if stored.status in {"approved", "running"}:
            return stored.status

        claimed = self.state.claim_delivery(
            action.action_id,
            now=self.monotonic(),
            lease_seconds=self.delivery_lease,
        )
        if claimed is None:
            stored = self.state.get_stored(action.action_id)
            return stored.status if stored is not None else "queued"

        if self._needs_approval(claimed):
            deadline = self.monotonic() + self.approval_ttl
            self.state.update_status(
                claimed.action_id,
                "awaiting_approval",
                approval_deadline=deadline,
                approval_boot_identity=self.boot_identity,
            )
            self.state.release_delivery(claimed.action_id)
            self._report_approval_required(claimed.action_id)
            return "awaiting_approval"

        return self._execute_stored(claimed, force=False)

    def receive_decision(self, decision: DeviceDecision | Mapping[str, Any]) -> DeviceResult:
        """Apply an action-ID-only human decision to the locally stored action."""

        decision = DeviceDecision.model_validate(decision)
        terminal = self.state.get_terminal_result(decision.action_id)
        if terminal is not None:
            self._report_result(terminal)
            return terminal

        stored = self.state.get_stored(decision.action_id)
        if stored is None:
            return self._reject_without_storage(decision.action_id, "unknown action id")

        existing_decision = self.state.get_decision(decision.action_id)
        if existing_decision is not None:
            if existing_decision.model_dump(mode="json") != decision.model_dump(mode="json"):
                return self._reject_without_storage(decision.action_id, "decision already recorded")
            decision = existing_decision
        else:
            # Do not persist approvals for unknown ids.  Otherwise a guessed
            # id could be pre-approved before the cloud ever delivers its
            # payload.
            self.state.save_decision(decision)

        if stored.status != "awaiting_approval":
            return self._reject_without_storage(decision.action_id, "action is not awaiting approval")

        expired = self._expire_waiting(stored)
        if expired is not None:
            return expired
        if not decision.approved:
            self.state.update_status(decision.action_id, "denied")
            return self._finish(
                DeviceResult(
                    action_id=decision.action_id,
                    status="rejected",
                    action="approval_denied",
                    error=decision.reason or "action denied",
                )
            )

        self.state.update_status(decision.action_id, "approved")
        return self._execute_stored(stored.action, force=True)

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _actions_from_response(self, response: Any) -> list[Any]:
        if isinstance(response, list):
            return response
        if not isinstance(response, Mapping):
            return []
        actions = response.get("actions")
        if isinstance(actions, list):
            return actions
        action = response.get("action")
        if isinstance(action, Mapping):
            return [action]
        if response.get("action_id"):
            return [response]
        return []

    def _decisions_from_response(self, response: Any) -> list[Any]:
        if not isinstance(response, Mapping):
            return []
        decisions = response.get("decisions")
        if isinstance(decisions, list):
            return decisions
        decision = response.get("decision")
        if isinstance(decision, Mapping):
            return [decision]
        return []

    def poll_once(self) -> bool:
        """Heartbeat and process one bounded cloud response."""

        try:
            # Poll is an authenticated POST so the cloud can receive a
            # heartbeat/device identity without placing identity in a URL.
            response = self._request("POST", self.poll_url, {"device_id": self.device_id})
            self._failure_count = 0
        except Exception:
            self._failure_count += 1
            delay = min(2.0 ** (self._failure_count - 1), self.max_backoff)
            self.sleep(delay)
            return False

        for raw_action in self._actions_from_response(response):
            try:
                self.receive_action(raw_action)
            except (TypeError, ValueError, KeyError):
                # Invalid cloud directives are rejected locally and never
                # reach the executor.  Do not log their payloads.
                continue
        for raw_decision in self._decisions_from_response(response):
            try:
                self.receive_decision(raw_decision)
            except (TypeError, ValueError, KeyError):
                continue
        # Awaiting rows are a durable, retryable outbox for approval events and
        # also provide the no-redelivery expiry check.
        self._retry_waiting_approvals()
        return True

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        """Run the outbound loop until ``stop_event`` or ``stop`` is called."""

        stop_event = stop_event or self._stop
        while not stop_event.is_set():
            healthy = self.poll_once()
            if healthy:
                self.sleep(self.poll_interval)

    def stop(self) -> None:
        self._stop.set()


def _shell_cwd_from_environment() -> str:
    cwd = os.environ.get("JARVIS_SHELL_CWD", "")
    path = Path(cwd) if cwd else None
    if path is None or not path.is_absolute() or not path.is_dir():
        raise ValueError("JARVIS_SHELL_CWD must be an existing absolute directory")
    return str(path)


def main() -> int:
    """Launch the outbound agent from environment-driven configuration."""

    parser = argparse.ArgumentParser(description="Jarvis outbound Mac agent")
    parser.add_argument("--cloud-url", default=os.environ.get("JARVIS_CLOUD_API_BASE_URL", ""))
    parser.add_argument("--device-token", default=os.environ.get("JARVIS_DEVICE_TOKEN", ""))
    parser.add_argument("--device-id", default=os.environ.get("JARVIS_DEVICE_ID", "local-mac"))
    parser.add_argument(
        "--state-path",
        default=os.environ.get("JARVIS_DEVICE_AGENT_STATE_PATH", "jarvis_device_agent.sqlite3"),
    )
    args = parser.parse_args()
    if not args.cloud_url or not args.device_token:
        parser.error("cloud URL and device token are required")
    _shell_cwd_from_environment()
    MacAgent(
        args.cloud_url,
        args.device_token,
        device_id=args.device_id,
        state_path=args.state_path,
    ).run_forever()
    return 0


__all__ = [
    "APPROVAL_TTL_SECONDS",
    "DELIVERY_LEASE_SECONDS",
    "MacAgent",
    "MAX_SCREENSHOT_BYTES",
    "POLL_INTERVAL_SECONDS",
    "validate_agent_url",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - exercised by launchd
    raise SystemExit(main())

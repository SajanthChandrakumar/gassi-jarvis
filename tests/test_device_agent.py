"""State-machine and redelivery contracts for the outbound Mac agent."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest


@dataclass
class FakeClock:
    now: float = 100.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeExecutor:
    def __init__(self, *, threat_level: int = 0) -> None:
        self.threat_level = threat_level
        self.calls: list[tuple[str, str, bool]] = []

    def security_level(self, command: str) -> int:
        return self.threat_level

    def execute_shell_command(self, command: str, *, force: bool = False) -> str:
        self.calls.append(("shell_command", command, force))
        return "executed"


def _action(action_id: str = "a-1", *, command: str = "echo hi", requires_approval: bool = False):
    from app.device.models import ActionPayload, DeviceAction

    return DeviceAction(
        action_id=action_id,
        payload=ActionPayload(action_type="shell_command", payload=command),
        requires_approval=requires_approval,
    )


def test_state_persists_payload_hash_and_rejects_substitution(tmp_path):
    from app.device.state import AgentState

    state = AgentState(tmp_path / "agent.sqlite3")
    action = _action(command="echo first")

    assert state.save_payload(action) is True
    assert state.payload_hash("a-1") == state.hash_payload(action)
    assert state.save_payload(action) is False

    with pytest.raises(ValueError, match="payload hash"):
        state.save_payload(_action(command="echo substituted"))


def test_dangerous_payload_is_reclassified_locally_and_executes_only_after_id_approval(tmp_path):
    from app.device.agent import MacAgent

    clock = FakeClock()
    executor = FakeExecutor(threat_level=2)
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        monotonic=clock.monotonic,
    )

    assert agent.receive_action(_action(command="rm -rf /")) == "awaiting_approval"
    assert executor.calls == []

    result = agent.receive_decision({"action_id": "a-1", "approved": True})

    assert result.status == "succeeded"
    assert executor.calls == [("shell_command", "rm -rf /", True)]


def test_approval_expires_from_local_monotonic_clock(tmp_path):
    from app.device.agent import MacAgent

    clock = FakeClock()
    executor = FakeExecutor(threat_level=2)
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        monotonic=clock.monotonic,
    )
    agent.receive_action(_action(command="rm -rf /"))
    clock.advance(300.001)

    result = agent.receive_decision({"action_id": "a-1", "approved": True})

    assert result.status == "expired"
    assert executor.calls == []


def test_record_before_report_prevents_execution_on_redelivery(tmp_path):
    from app.device.agent import MacAgent

    executor = FakeExecutor()
    reports: list[dict] = []
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        report=lambda event: reports.append(event),
    )
    action = _action(command="echo once")

    first = agent.receive_action(action)
    second = agent.receive_action(action)

    assert first.status == second.status == "succeeded"
    assert executor.calls == [("shell_command", "echo once", False)]
    assert len(reports) == 2
    assert agent.state.is_tombstoned("a-1")


def test_delivery_lease_allows_redelivery_only_after_thirty_seconds(tmp_path):
    from app.device.state import AgentState

    state = AgentState(tmp_path / "agent.sqlite3")
    action = _action(command="echo lease")
    state.save_payload(action)

    assert state.claim_delivery("a-1", now=10.0, lease_seconds=30.0) is not None
    assert state.claim_delivery("a-1", now=39.9, lease_seconds=30.0) is None
    assert state.claim_delivery("a-1", now=40.0, lease_seconds=30.0) is not None


def test_agent_url_requires_https_except_loopback():
    from app.device.agent import validate_agent_url

    assert validate_agent_url("https://jarvis.example.test/api/device/poll")
    assert validate_agent_url("http://127.0.0.1:8000")
    assert validate_agent_url("http://localhost:8000")
    assert not validate_agent_url("http://jarvis.example.test")
    assert not validate_agent_url("ftp://127.0.0.1")


def test_poll_request_uses_device_bearer_and_two_second_default(tmp_path):
    from app.device.agent import MacAgent

    requests: list[tuple[str, str, dict, object]] = []

    def transport(method, url, headers, body=None):
        requests.append((method, url, headers, body))
        return {"actions": []}

    agent = MacAgent(
        "https://jarvis.example.test",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=FakeExecutor(),
        transport=transport,
    )

    agent.poll_once()

    assert agent.poll_interval == 2.0
    assert requests[0][0] == "POST"
    assert requests[0][3] == {"device_id": "local-mac"}
    assert requests[0][2]["Authorization"] == "Bearer device-secret"


def test_agent_backoff_is_bounded(tmp_path):
    from app.device.agent import MacAgent

    sleeps: list[float] = []
    agent = MacAgent(
        "https://jarvis.example.test",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=FakeExecutor(),
        transport=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
        sleep=sleeps.append,
    )

    for _ in range(8):
        agent.poll_once()

    assert sleeps
    assert max(sleeps) <= 30.0
    assert sleeps == sorted(sleeps)


def test_poll_processes_action_id_only_decisions(tmp_path):
    from app.device.agent import MacAgent

    executor = FakeExecutor(threat_level=2)

    def transport(method, url, headers, body=None):
        return {
            "actions": [_action(command="rm -rf /tmp/nope").model_dump(mode="json")],
            "decisions": [{"action_id": "a-1", "approved": True}],
        }

    agent = MacAgent(
        "https://jarvis.example.test",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        transport=transport,
    )

    agent.poll_once()

    assert executor.calls == [("shell_command", "rm -rf /tmp/nope", True)]


def test_redelivery_expires_waiting_approval_without_a_decision(tmp_path):
    from app.device.agent import MacAgent

    clock = FakeClock()
    executor = FakeExecutor(threat_level=2)
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        monotonic=clock.monotonic,
    )
    action = _action(command="rm -rf /")

    assert agent.receive_action(action) == "awaiting_approval"
    clock.advance(300.001)

    result = agent.receive_action(action)

    assert result.status == "expired"
    assert agent.state.get_result("a-1").status == "expired"
    assert executor.calls == []


def test_poll_expires_waiting_approval_even_without_redelivery(tmp_path):
    from app.device.agent import MacAgent

    clock = FakeClock()
    executor = FakeExecutor(threat_level=2)
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=executor,
        monotonic=clock.monotonic,
        transport=lambda *args, **kwargs: {"actions": [], "decisions": []},
    )
    agent.receive_action(_action(command="rm -rf /"))
    clock.advance(300.001)

    agent.poll_once()

    assert agent.state.get_result("a-1").status == "expired"
    assert executor.calls == []


def test_approval_required_event_is_retried_from_persisted_waiting_state(tmp_path):
    from app.device.agent import MacAgent

    attempts: list[dict] = []

    def report(event):
        attempts.append(event)
        if len(attempts) == 1:
            raise OSError("cloud temporarily unavailable")

    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=FakeExecutor(threat_level=2),
        report=report,
        transport=lambda *args, **kwargs: {"actions": [], "decisions": []},
    )
    agent.receive_action(_action(command="rm -rf /"))
    assert len(attempts) == 1

    agent.poll_once()

    assert len(attempts) == 2
    assert attempts[0]["type"] == attempts[1]["type"] == "approval_required"


def test_persisted_approval_from_another_boot_fails_closed(tmp_path):
    from app.device.agent import MacAgent

    clock = FakeClock()
    path = tmp_path / "agent.sqlite3"
    first = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=path,
        executor=FakeExecutor(threat_level=2),
        monotonic=clock.monotonic,
        boot_identity="boot-a",
    )
    first.receive_action(_action(command="rm -rf /"))

    second_executor = FakeExecutor(threat_level=2)
    second = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=path,
        executor=second_executor,
        monotonic=clock.monotonic,
        boot_identity="boot-b",
    )

    result = second.receive_decision({"action_id": "a-1", "approved": True})

    assert result.status == "expired"
    assert second_executor.calls == []

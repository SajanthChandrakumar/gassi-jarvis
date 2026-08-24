"""Final release regressions for the cloud/Mac device security boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _gateway_with_delivered_action(tmp_path, monkeypatch, *, action_id="release-1"):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    clock = Clock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "rm -rf /", action_id=action_id)
    gateway.poll("mac-1")
    return gateway, clock


def test_cloud_approval_required_deadline_is_first_transition_only(tmp_path, monkeypatch):
    gateway, clock = _gateway_with_delivered_action(tmp_path, monkeypatch)

    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    first = gateway._db.execute(
        "SELECT status, approval_deadline FROM device_actions WHERE action_id=?",
        ("release-1",),
    ).fetchone()
    clock.now += 30
    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    duplicate = gateway._db.execute(
        "SELECT status, approval_deadline FROM device_actions WHERE action_id=?",
        ("release-1",),
    ).fetchone()

    assert first["status"] == duplicate["status"] == "awaiting_approval"
    assert duplicate["approval_deadline"] == first["approval_deadline"] == 400.0


def test_cloud_approval_required_cannot_revert_approved_or_terminal(tmp_path, monkeypatch):
    gateway, _clock = _gateway_with_delivered_action(tmp_path, monkeypatch)
    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    gateway.decide("release-1", approved=True)
    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    assert gateway.get_action("release-1").status == "approved"

    gateway.record_event(
        "release-1",
        "device-secret",
        {"type": "result", "result": {"status": "succeeded", "action": "done"}},
    )
    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    assert gateway.get_action("release-1").result.status == "succeeded"


def test_cloud_competing_decisions_have_one_winner(tmp_path, monkeypatch):
    gateway, _clock = _gateway_with_delivered_action(tmp_path, monkeypatch)
    gateway.record_event("release-1", "device-secret", {"type": "approval_required"})
    barrier = threading.Barrier(2)
    outcomes = []

    def decide(approved):
        barrier.wait()
        try:
            outcomes.append(gateway.decide("release-1", approved=approved))
        except Exception as exc:  # the losing conflicting decision is rejected
            outcomes.append(exc)

    threads = [threading.Thread(target=decide, args=(True,)), threading.Thread(target=decide, args=(False,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    row = gateway._db.execute(
        "SELECT status, decision_json FROM device_actions WHERE action_id=?", ("release-1",)
    ).fetchone()
    assert row["status"] in {"approved", "denied"}
    assert json.loads(row["decision_json"])["approved"] is (row["status"] == "approved")
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1


def test_cloud_results_are_first_writer_and_exact_replays_are_idempotent(tmp_path, monkeypatch):
    gateway, _clock = _gateway_with_delivered_action(tmp_path, monkeypatch)
    first = {"type": "result", "result": {"status": "succeeded", "action": "done", "output": "one"}}
    replay = gateway.record_event("release-1", "device-secret", first)
    duplicate = gateway.record_event("release-1", "device-secret", first)
    assert duplicate.result.model_dump(mode="json") == replay.result.model_dump(mode="json")
    with pytest.raises(ValueError, match="terminal result"):
        gateway.record_event(
            "release-1",
            "device-secret",
            {"type": "result", "result": {"status": "failed", "action": "done", "output": "two"}},
        )


def test_cloud_competing_results_have_one_first_writer(tmp_path, monkeypatch):
    gateway, _clock = _gateway_with_delivered_action(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    outcomes = []

    def record(output):
        barrier.wait()
        try:
            outcomes.append(
                gateway.record_event(
                    "release-1",
                    "device-secret",
                    {"type": "result", "result": {"status": "succeeded", "action": "done", "output": output}},
                )
            )
        except Exception as exc:  # the second conflicting result is rejected
            outcomes.append(exc)

    threads = [threading.Thread(target=record, args=("one",)), threading.Thread(target=record, args=("two",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = gateway.get_action("release-1").result
    assert stored.output in {"one", "two"}
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1


def test_urllib_transport_does_not_forward_bearer_across_redirect(tmp_path, monkeypatch):
    import app.device.agent as agent_module

    seen = []

    class NoRedirectOpener:
        def open(self, request, **_kwargs):
            seen.append((request.full_url, request.headers.get("Authorization")))
            raise HTTPError(
                request.full_url,
                302,
                "redirect rejected",
                {"Location": "http://other-host.example/target"},
                None,
            )

    monkeypatch.setattr(agent_module, "_NO_REDIRECT_OPENER", NoRedirectOpener())
    agent = agent_module.MacAgent(
        "https://jarvis.example.test",
        "device-secret",
        state_path=tmp_path / "agent.sqlite3",
        executor=SimpleNamespace(security_level=lambda _command: 0),
    )
    with pytest.raises(HTTPError):
        agent._urllib_transport("GET", agent.cloud_url, agent._headers())
    assert seen == [("https://jarvis.example.test", "Bearer device-secret")]
    assert agent_module._NoRedirectHandler().redirect_request(
        None, "http://other-host.example/target", 302, "", {}, None
    ) is None


def test_unset_frontend_token_allows_local_no_token_but_rejects_bearers(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway
    from app.device.routes import router

    monkeypatch.delenv("JARVIS_API_TOKEN", raising=False)
    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    api = FastAPI()
    api.include_router(router)
    api.state.device_gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1")
    client = TestClient(api)

    assert client.get("/api/device/status").status_code == 200
    assert client.get(
        "/api/device/status", headers={"Authorization": "Bearer device-secret"}
    ).status_code == 401
    assert client.post(
        "/api/device-agent/poll", json={"device_id": "mac-1"}
    ).status_code == 401


def test_unset_frontend_token_rejects_device_bearer_on_main_frontend_routes(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "API_TOKEN", "")
    response = TestClient(main_module.app).get(
        "/api/research/providers", headers={"Authorization": "Bearer device-secret"}
    )
    assert response.status_code == 401


def test_equal_frontend_and_device_tokens_fail_configuration():
    env = os.environ.copy()
    env.update(
        {
            "GOOGLE_API_KEY": "test-only-key",
            "JARVIS_API_TOKEN": "same-secret",
            "JARVIS_DEVICE_TOKEN": "same-secret",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=".",
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must differ" in (result.stderr + result.stdout)


def test_restart_recovers_running_action_without_second_executor_call(tmp_path):
    from app.device.agent import MacAgent
    from app.device.models import ActionPayload, DeviceAction

    action = DeviceAction(
        action_id="ambiguous-1",
        payload=ActionPayload(action_type="shell_command", payload="echo side-effect"),
    )
    first_calls = []

    class CrashingExecutor:
        def security_level(self, _command):
            return 0

        def execute_shell_command(self, command, *, force=False):
            first_calls.append((command, force))
            raise KeyboardInterrupt("crash after side effect window")

    state_path = tmp_path / "agent.sqlite3"
    first = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=state_path,
        executor=CrashingExecutor(),
        report=lambda _event: None,
    )
    with pytest.raises(KeyboardInterrupt):
        first.receive_action(action)
    assert first_calls == [("echo side-effect", False)]

    second_calls = []
    reports = []
    second = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=state_path,
        executor=SimpleNamespace(
            security_level=lambda _command: 0,
            execute_shell_command=lambda command, force=False: second_calls.append(command),
        ),
        report=reports.append,
    )
    recovered = second.state.get_result("ambiguous-1")
    assert recovered.status == "failed"
    assert "reissue" in recovered.error.lower()
    assert second_calls == []
    assert second.receive_action(action).status == "failed"
    assert second_calls == []


def test_mac_executor_requires_existing_absolute_shell_cwd(tmp_path, monkeypatch):
    from app.device.executor import MacExecutor

    monkeypatch.delenv("JARVIS_SHELL_CWD", raising=False)
    with pytest.raises(ValueError, match="absolute"):
        MacExecutor()
    monkeypatch.setenv("JARVIS_SHELL_CWD", "relative/path")
    with pytest.raises(ValueError, match="absolute"):
        MacExecutor()
    monkeypatch.setenv("JARVIS_SHELL_CWD", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="existing"):
        MacExecutor()
    monkeypatch.setenv("JARVIS_SHELL_CWD", str(tmp_path))
    assert MacExecutor().shell_cwd == str(tmp_path)


def test_mac_agent_requires_cwd_only_for_real_executor(tmp_path, monkeypatch):
    from app.device.agent import MacAgent

    monkeypatch.setenv("JARVIS_SHELL_CWD", "relative/path")
    with pytest.raises(ValueError, match="absolute"):
        MacAgent("http://127.0.0.1:8000", "device-secret", state_path=tmp_path / "real.sqlite3")

    # Test doubles remain injectable without requiring a host filesystem path.
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "fake.sqlite3",
        executor=SimpleNamespace(security_level=lambda _command: 0),
    )
    assert agent.executor is not None

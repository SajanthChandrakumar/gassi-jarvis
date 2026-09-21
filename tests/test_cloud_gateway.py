"""Cloud queue and trust-boundary contracts for the Mac device gateway."""

from __future__ import annotations

import base64
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _action(action_id: str = "a-1", *, kind: str = "shell_command", payload: str = "echo hi"):
    from app.device.models import ActionPayload, DeviceAction

    return DeviceAction(
        action_id=action_id,
        device_id="mac-1",
        payload=ActionPayload(action_type=kind, payload=payload),
    )


class FakeClock:
    def __init__(self, now: float = 100.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_research_can_use_gateway_while_device_is_offline(tmp_path):
    from app.device.cloud import DeviceGateway

    clock = FakeClock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)

    unavailable = gateway.queue_action("shell_command", "echo hi")

    assert unavailable.available is False
    assert gateway.status().status == "offline"


def test_poll_is_authenticated_and_leased_with_separate_device_token(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway
    from app.device.routes import router

    monkeypatch.setenv("JARVIS_API_TOKEN", "user-secret")
    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    clock = FakeClock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    queued = gateway.queue_action("shell_command", "echo hi")
    assert queued.action_id

    api = FastAPI()
    api.include_router(router)
    api.state.device_gateway = gateway
    client = TestClient(api)

    denied = client.post(
        "/api/device-agent/poll",
        headers={"Authorization": "Bearer user-secret"},
        json={"device_id": "mac-1"},
    )
    assert denied.status_code == 401

    response = client.post(
        "/api/device-agent/poll",
        headers={"Authorization": "Bearer device-secret"},
        json={"device_id": "mac-1"},
    )
    assert response.status_code == 200
    assert response.json()["actions"][0]["action_id"] == queued.action_id


def test_mismatched_device_identity_is_rejected(tmp_path):
    from app.device.cloud import DeviceGateway

    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1")

    with pytest.raises(ValueError, match="device id"):
        gateway.heartbeat("other-mac")


def test_approval_decision_is_idempotent_and_expiry_is_terminal(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    clock = FakeClock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    action = gateway.queue_action("shell_command", "rm -rf /", action_id="danger-1")
    gateway.poll("mac-1")
    gateway.record_event("danger-1", "device-secret", {"type": "approval_required"})

    first = gateway.decide("danger-1", approved=True)
    second = gateway.decide("danger-1", approved=True)
    assert first.action.action_id == second.action.action_id == action.action_id
    assert first.decision.approved is True

    gateway = DeviceGateway(tmp_path / "expiry.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "rm -rf /", action_id="danger-2")
    gateway.poll("mac-1")
    gateway.record_event("danger-2", "device-secret", {"type": "approval_required"})
    clock.advance(301)

    expired = gateway.decide("danger-2", approved=True)
    assert expired.status == "expired"
    assert gateway.decide("danger-2", approved=True).status == "expired"


def test_result_event_is_idempotent_and_screenshot_bytes_never_persist(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    analyzed: list[bytes] = []
    gateway = DeviceGateway(
        tmp_path / "cloud.sqlite3",
        device_id="mac-1",
        vision_analyzer=lambda _prompt, image: analyzed.append(image) or "screen analyzed",
    )
    gateway.heartbeat("mac-1")
    gateway.queue_action("take_screenshot", "look at screen", action_id="screen-1")
    gateway.poll("mac-1")
    image = b"jpeg-bytes"
    event = {
        "type": "result",
        "result": {"action_id": "screen-1", "status": "succeeded", "action": "take_screenshot"},
        "screenshot_b64": base64.b64encode(image).decode("ascii"),
    }

    first = gateway.record_event("screen-1", "device-secret", event)
    second = gateway.record_event("screen-1", "device-secret", event)
    assert first.result.status == second.result.status == "succeeded"
    assert analyzed == [image]
    raw = (tmp_path / "cloud.sqlite3").read_bytes()
    assert image not in raw
    assert b"screenshot_b64" not in raw


def test_terminal_result_is_rejected_before_agent_delivery(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1")
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "echo hi", action_id="before-delivery")

    with pytest.raises(ValueError, match="delivery"):
        gateway.record_event(
            "before-delivery",
            "device-secret",
            {"type": "result", "result": {"status": "succeeded"}},
        )


def test_terminal_result_is_rejected_after_approval_expiry(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    clock = FakeClock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "rm -rf /", action_id="expired-result")
    gateway.poll("mac-1")
    gateway.record_event("expired-result", "device-secret", {"type": "approval_required"})
    clock.advance(301)

    with pytest.raises(ValueError, match="expired"):
        gateway.record_event(
            "expired-result",
            "device-secret",
            {"type": "result", "result": {"status": "succeeded"}},
        )


def test_terminal_result_is_rejected_after_denial(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1")
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "rm -rf /", action_id="denied-result")
    gateway.poll("mac-1")
    gateway.record_event("denied-result", "device-secret", {"type": "approval_required"})
    gateway.decide("denied-result", approved=False, reason="no")

    with pytest.raises(ValueError, match="denied"):
        gateway.record_event(
            "denied-result",
            "device-secret",
            {"type": "result", "result": {"status": "succeeded"}},
        )


def test_record_event_fails_closed_when_device_token_is_unset(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway

    monkeypatch.delenv("JARVIS_DEVICE_TOKEN", raising=False)
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1")
    gateway.heartbeat("mac-1")
    gateway.queue_action("shell_command", "echo hi", action_id="no-token")
    gateway.poll("mac-1")

    with pytest.raises(PermissionError, match="device token"):
        gateway.record_event(
            "no-token",
            "device-secret",
            {"type": "approval_required"},
        )

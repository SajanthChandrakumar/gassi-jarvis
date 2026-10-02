"""Task 6 executable regressions for the split cloud/Mac trust boundaries."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


ROOT = Path(__file__).parents[1]


@dataclass
class FakeClock:
    now: float = 100.0

    def __call__(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _device_client(tmp_path, monkeypatch):
    from app.device.cloud import DeviceGateway
    from app.device.routes import router

    monkeypatch.setenv("JARVIS_API_TOKEN", "frontend-secret")
    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    gateway = DeviceGateway(
        tmp_path / "cloud.sqlite3",
        device_id="mac-1",
        clock=FakeClock(),
    )
    api = FastAPI()
    api.include_router(router)
    api.state.device_gateway = gateway
    return TestClient(api), gateway


def test_cloud_chat_and_research_remain_available_when_agent_is_offline(tmp_path, monkeypatch):
    import app.main as main_module
    from app.device.cloud import DeviceGateway

    token = "cloud-token"
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=FakeClock())
    monkeypatch.setattr(main_module, "device_gateway", gateway)
    main_module.app.state.device_gateway = gateway

    async def build_response(text, action="none", **kwargs):
        return {
            "status": "success",
            "jarvis_response": text,
            "audio_base64": "",
            "action_taken": action,
            "research_payload": kwargs.get("research_payload"),
            "device_action": kwargs.get("device_action"),
        }

    monkeypatch.setattr(main_module, "_build_response", build_response)
    monkeypatch.setattr(main_module, "get_session", lambda _session_id: {"history": []})
    monkeypatch.setattr(main_module, "record_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module,
        "get_gemini_response",
        lambda *_args, **_kwargs: SimpleNamespace(candidates=[], text="Ordinary chat still works."),
    )

    class ResearchTools:
        def dispatch(self, _name, _arguments):
            return SimpleNamespace(status=SimpleNamespace(value="success"))

    monkeypatch.setattr(main_module, "research_tools", ResearchTools())
    monkeypatch.setattr(main_module, "render_research_response", lambda _response: "Offline research result")
    monkeypatch.setattr(main_module, "response_payload", lambda _response: {"status": "success", "sources": []})

    client = TestClient(main_module.app)
    headers = {"Authorization": f"Bearer {token}"}
    chat = client.post(
        "/api/chat",
        headers=headers,
        json={
            "session_id": "offline-chat",
            "timestamp": "2026-08-24T12:00:00Z",
            "payload": {"type": "text", "content": "Hello"},
        },
    )
    research = client.post(
        "/api/research/run",
        headers=headers,
        json={"mode": "asset", "asset": "NVDA", "timeframe": "1y"},
    )

    assert gateway.status().available is False
    assert chat.status_code == 200
    assert chat.json()["jarvis_response"] == "Ordinary chat still works."
    assert research.status_code == 200
    assert research.json()["research_payload"]["status"] == "success"


def test_device_routes_keep_frontend_and_agent_credentials_separate(tmp_path, monkeypatch):
    client, _gateway = _device_client(tmp_path, monkeypatch)

    bad_agent = client.post(
        "/api/device-agent/poll",
        headers={"Authorization": "Bearer wrong"},
        json={"device_id": "mac-1"},
    )
    frontend_on_agent = client.post(
        "/api/device-agent/poll",
        headers={"Authorization": "Bearer frontend-secret"},
        json={"device_id": "mac-1"},
    )
    agent_on_frontend = client.get(
        "/api/device/status",
        headers={"Authorization": "Bearer device-secret"},
    )

    assert bad_agent.status_code == 401
    assert frontend_on_agent.status_code == 401
    assert agent_on_frontend.status_code == 401


def test_device_routes_reject_mismatched_identity_and_bad_poll_payload(tmp_path, monkeypatch):
    client, _gateway = _device_client(tmp_path, monkeypatch)
    headers = {
        "Authorization": "Bearer device-secret",
        "X-Jarvis-Device-ID": "other-mac",
    }

    mismatched_header = client.post(
        "/api/device-agent/poll",
        headers=headers,
        json={"device_id": "mac-1"},
    )
    mismatched_body = client.post(
        "/api/device-agent/poll",
        headers={"Authorization": "Bearer device-secret"},
        json={"device_id": "other-mac"},
    )

    assert mismatched_header.status_code == 403
    assert mismatched_body.status_code == 409


def test_routes_reject_unknown_event_kinds_and_malformed_payloads(tmp_path, monkeypatch):
    client, gateway = _device_client(tmp_path, monkeypatch)
    gateway.heartbeat("mac-1")
    action = gateway.queue_action("shell_command", "echo hi", action_id="malformed-1")
    gateway.poll("mac-1")
    headers = {"Authorization": "Bearer device-secret"}

    unknown_event = client.post(
        f"/api/device-agent/actions/{action.action_id}/events",
        headers=headers,
        json={"type": "not-a-device-event"},
    )
    malformed_result = client.post(
        f"/api/device-agent/actions/{action.action_id}/events",
        headers=headers,
        json={"type": "result", "result": {}},
    )

    assert unknown_event.status_code == 422
    assert malformed_result.status_code == 422

    with pytest.raises(ValueError, match="unsupported device action type"):
        gateway.queue_action("not-a-device-action", "echo hi")
    with pytest.raises(ValueError, match="non-empty"):
        gateway.queue_action("shell_command", " \t\n")


def test_payloads_reject_whitespace_without_normalizing_valid_flattened_actions():
    from app.device.models import ActionPayload, DeviceAction
    from app.device.state import hash_payload

    with pytest.raises(ValidationError):
        ActionPayload(action_type="shell_command", payload=" \t\n")
    with pytest.raises(ValidationError):
        DeviceAction.model_validate({"action_id": "raw-blank", "payload": " \t\n"})

    for action_type, payload in (
        ("shell_command", " echo preserved "),
        ("open_app", "Safari"),
        ("take_screenshot", "inspect"),
    ):
        action = DeviceAction.model_validate(
            {
                "action_id": f"flattened-{action_type}",
                "action_type": action_type,
                "payload": payload,
            }
        )
        assert action.command == payload
        assert hash_payload(action.payload) == hash_payload(
            ActionPayload(action_type=action_type, payload=payload)
        )


def test_frontend_token_can_read_device_status(tmp_path, monkeypatch):
    client, gateway = _device_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/device/status",
        headers={"Authorization": "Bearer frontend-secret"},
    )

    assert response.status_code == 200
    assert response.json()["device_id"] == gateway.device_id
    assert response.json()["available"] is False


def test_local_agent_requires_hitl_for_dangerous_unknown_sensitive_metachar_and_tainted_shell(tmp_path):
    from app.device.agent import MacAgent
    from app.device.models import ActionPayload, DeviceAction
    from app.security import evaluate_security_level

    class RecordingExecutor:
        def __init__(self):
            self.calls = []

        def security_level(self, command):
            return evaluate_security_level(command)

        def execute_shell_command(self, command, *, force=False):
            self.calls.append((command, force))
            return "should not execute in this test"

    cases = (
        ("dangerous", "rm -rf /", False),
        ("unknown", "an-unknown-command --flag", False),
        ("sensitive", "cat ~/.ssh/id_rsa", False),
        ("metachar", "echo safe; date", False),
        ("tainted", "echo safe", True),
    )
    for action_id, command, tainted in cases:
        executor = RecordingExecutor()
        agent = MacAgent(
            "http://127.0.0.1:8000",
            "device-secret",
            state_path=tmp_path / f"{action_id}.sqlite3",
            executor=executor,
            report=lambda _event: None,
        )
        action = DeviceAction(
            action_id=action_id,
            device_id="local-mac",
            payload=ActionPayload(
                action_type="shell_command",
                payload=command,
                tainted=tainted,
            ),
        )

        assert agent.receive_action(action) == "awaiting_approval"
        assert executor.calls == []
        assert agent.state.get_stored(action_id).status == "awaiting_approval"


def test_local_agent_rejects_unknown_action_kind_and_missing_payload(tmp_path):
    from app.device.agent import MacAgent

    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "malformed.sqlite3",
        executor=SimpleNamespace(security_level=lambda _command: 0),
        report=lambda _event: None,
    )

    with pytest.raises(ValidationError):
        agent.receive_action(
            {
                "action_id": "bad-kind",
                "device_id": "local-mac",
                "payload": {"action_type": "unknown", "payload": "x"},
            }
        )
    with pytest.raises(ValidationError):
        agent.receive_action(
            {
                "action_id": "missing-payload",
                "device_id": "local-mac",
                "payload": {"action_type": "shell_command"},
            }
        )


def test_local_approval_succeeds_just_before_and_expires_exactly_at_300_seconds(tmp_path):
    from app.device.agent import MacAgent
    from app.device.models import ActionPayload, DeviceAction

    clock = FakeClock()
    calls = []
    executor = SimpleNamespace(
        security_level=lambda _command: 2,
        execute_shell_command=lambda command, force=False: calls.append((command, force)) or "executed",
    )
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "ttl.sqlite3",
        executor=executor,
        monotonic=clock.monotonic,
        boot_identity="boot-a",
        report=lambda _event: None,
    )
    agent.receive_action(
        DeviceAction(
            action_id="ttl-299999",
            payload=ActionPayload(action_type="shell_command", payload="rm -rf /"),
        )
    )
    clock.advance(299.999)

    before_expiry = agent.receive_decision({"action_id": "ttl-299999", "approved": True})

    assert before_expiry.status == "succeeded"
    assert calls == [("rm -rf /", True)]

    agent.receive_action(
        DeviceAction(
            action_id="ttl-300",
            payload=ActionPayload(action_type="shell_command", payload="rm -rf /tmp/exact"),
        )
    )
    clock.advance(300.0)

    at_expiry = agent.receive_decision({"action_id": "ttl-300", "approved": True})

    assert at_expiry.status == "expired"
    assert calls == [("rm -rf /", True)]


def test_denied_and_substituted_actions_cannot_execute_and_completed_replay_is_safe(tmp_path):
    from app.device.agent import MacAgent
    from app.device.models import ActionPayload, DeviceAction

    calls = []
    executor = SimpleNamespace(
        security_level=lambda _command: 2,
        execute_shell_command=lambda command, force=False: calls.append((command, force)) or "executed",
    )
    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "lifecycle.sqlite3",
        executor=executor,
        boot_identity="boot-a",
        report=lambda _event: None,
    )
    dangerous = DeviceAction(
        action_id="denied",
        payload=ActionPayload(action_type="shell_command", payload="rm -rf /"),
    )
    assert agent.receive_action(dangerous) == "awaiting_approval"
    assert agent.receive_decision({"action_id": "denied", "approved": False}).status == "rejected"
    assert agent.receive_decision({"action_id": "denied", "approved": True}).status == "rejected"
    assert calls == []

    substitute = dangerous.model_copy(
        update={
            "action_id": "substituted",
            "payload": ActionPayload(action_type="shell_command", payload="echo substituted"),
        }
    )
    original = substitute.model_copy(
        update={
            "payload": ActionPayload(action_type="shell_command", payload="rm -rf /tmp/original"),
        }
    )
    assert agent.receive_action(original) == "awaiting_approval"
    with pytest.raises(ValueError, match="payload hash"):
        agent.receive_action(substitute)
    assert agent.receive_decision({"action_id": "substituted", "approved": True}).status == "succeeded"
    assert calls == [("rm -rf /tmp/original", True)]

    completed = DeviceAction(
        action_id="completed",
        payload=ActionPayload(action_type="shell_command", payload="echo once"),
    )
    # Use a fresh agent so this safe action is executed immediately.
    safe_agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "completed.sqlite3",
        executor=SimpleNamespace(
            security_level=lambda _command: 0,
            execute_shell_command=lambda command, force=False: calls.append((command, force)) or "once",
        ),
        report=lambda _event: None,
    )
    assert safe_agent.receive_action(completed).status == "succeeded"
    assert safe_agent.receive_action(completed).status == "succeeded"
    assert [command for command, _force in calls].count("echo once") == 1


def test_tainted_approval_uses_authoritative_classifier_and_forced_executor(monkeypatch, tmp_path):
    import app.device.executor as executor_module
    from app.device.agent import MacAgent
    from app.device.models import ActionPayload, DeviceAction

    classify = executor_module.evaluate_security_level
    seen_classifications = []

    def classify_with_trace(command):
        seen_classifications.append(command)
        return classify(command)

    execute_calls = []

    def execute_with_trace(command, *, force=False, cwd=None):
        execute_calls.append((command, force))
        return "approved execution"

    monkeypatch.setattr(executor_module, "evaluate_security_level", classify_with_trace)
    monkeypatch.setattr(executor_module, "_execute_shell_command", execute_with_trace)

    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "tainted-approval.sqlite3",
        executor=executor_module.MacExecutor(shell_cwd=tmp_path),
        report=lambda _event: None,
    )
    action = DeviceAction(
        action_id="tainted-approval",
        payload=ActionPayload(
            action_type="shell_command",
            payload="echo trusted",
            tainted=True,
        ),
    )

    assert agent.receive_action(action) == "awaiting_approval"
    result = agent.receive_decision({"action_id": action.action_id, "approved": True})

    assert result.status == "succeeded"
    assert seen_classifications == ["echo trusted"]
    assert execute_calls == [("echo trusted", True)]


def test_screenshot_bytes_are_bounded_and_not_stored_by_local_agent(tmp_path, monkeypatch, caplog):
    import app.device.agent as agent_module
    from app.device.models import ActionPayload, DeviceAction

    monkeypatch.setattr(agent_module, "MAX_SCREENSHOT_BYTES", 4)
    events = []

    class ScreenshotExecutor:
        def __init__(self, data):
            self.data = data

        def capture_screen(self):
            return self.data

    good_path = tmp_path / "screenshot.sqlite3"
    good = agent_module.MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=good_path,
        executor=ScreenshotExecutor(b"1234"),
        report=events.append,
    )
    good.receive_action(
        DeviceAction(
            action_id="screen-good",
            payload=ActionPayload(action_type="take_screenshot", payload="inspect"),
        )
    )
    encoded = base64.b64encode(b"1234").decode("ascii")
    raw_files = [good_path] + list(good_path.parent.glob(good_path.name + "-*"))
    raw = b"".join(path.read_bytes() for path in raw_files if path.exists())
    assert encoded in events[0]["screenshot_b64"]
    assert b"1234" not in raw
    assert b"screenshot_b64" not in raw
    assert encoded not in caplog.text

    oversized = agent_module.MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        state_path=tmp_path / "oversized.sqlite3",
        executor=ScreenshotExecutor(b"12345"),
        report=events.append,
    )
    result = oversized.receive_action(
        DeviceAction(
            action_id="screen-large",
            payload=ActionPayload(action_type="take_screenshot", payload="inspect"),
        )
    )
    assert result.status == "failed"
    assert "screenshot_b64" not in events[-1]


def test_cloud_screenshot_event_rejects_oversized_encoded_payload(tmp_path, monkeypatch):
    import app.device.cloud as cloud_module
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    monkeypatch.setattr(cloud_module, "MAX_SCREENSHOT_BYTES", 4)
    clock = FakeClock()
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=clock)
    gateway.heartbeat("mac-1")
    gateway.queue_action("take_screenshot", "inspect", action_id="screen-cloud")
    gateway.poll("mac-1")

    with pytest.raises(ValueError, match="screenshot exceeds size limit"):
        gateway.record_event(
            "screen-cloud",
            "device-secret",
            {
                "type": "result",
                "result": {"action_id": "screen-cloud", "status": "succeeded"},
                "screenshot_b64": base64.b64encode(b"12345").decode("ascii"),
            },
        )


def test_cloud_screenshot_result_does_not_log_bytes_or_base64(tmp_path, monkeypatch, caplog):
    from app.device.cloud import DeviceGateway

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    image = b"cloud-jpeg"
    encoded = base64.b64encode(image).decode("ascii")
    gateway = DeviceGateway(
        tmp_path / "cloud-logs.sqlite3",
        device_id="mac-1",
        vision_analyzer=lambda _prompt, _image: "analysis only",
    )
    gateway.heartbeat("mac-1")
    gateway.queue_action("take_screenshot", "inspect", action_id="screen-log")
    gateway.poll("mac-1")

    gateway.record_event(
        "screen-log",
        "device-secret",
        {
            "type": "result",
            "result": {"action_id": "screen-log", "status": "succeeded"},
            "screenshot_b64": encoded,
        },
    )

    assert image.decode("ascii") not in caplog.text
    assert encoded not in caplog.text


def test_frontend_api_url_joins_same_origin_and_configured_cross_origin_at_runtime():
    source_path = ROOT / "app/static/app.js"
    script = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function normalizeApiBase');
const end = source.indexOf('function recoverAuthorization', start);
const snippet = source.slice(start, end);
function helpers(base) {
  return new Function('window', snippet + '; return { normalizeApiBase, apiUrl, API_BASE_URL };')({ JARVIS_CONFIG: { apiBaseUrl: base } });
}
const cross = helpers('https://cloud.example.test/');
if (cross.API_BASE_URL !== 'https://cloud.example.test') throw new Error('cross-origin config was not normalized');
if (cross.apiUrl('/api/chat') !== 'https://cloud.example.test/api/chat') throw new Error('cross-origin endpoint was not joined');
const same = helpers('');
if (same.API_BASE_URL !== '') throw new Error('same-origin default changed');
if (same.apiUrl('/api/chat') !== '/api/chat') throw new Error('same-origin endpoint was not preserved');
const invalid = helpers('https://cloud.example.test/api');
if (invalid.API_BASE_URL !== '' || invalid.apiUrl('/api/chat') !== '/api/chat') throw new Error('non-origin path was accepted');
"""
    result = subprocess.run(
        ["node", "-e", script, str(source_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_cloud_main_import_and_start_do_not_require_mac_modules(tmp_path):
    script = r"""
import builtins
real_import = builtins.__import__
def block_mac_modules(name, *args, **kwargs):
    if name in {"app.security", "app.vision", "app.device.executor"}:
        raise ImportError("blocked Mac-only module: " + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = block_mac_modules
import app.main
from fastapi.testclient import TestClient
with TestClient(app.main.app) as client:
    response = client.get("/config.js")
    assert response.status_code == 200
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "GOOGLE_API_KEY": "test-only-key",
            "JARVIS_CLOUD_DB_PATH": str(tmp_path / "cloud.sqlite3"),
            "JARVIS_BRAIN_DIR": str(tmp_path / "brain"),
            "JARVIS_SESSIONS_FILE": str(tmp_path / "sessions.json"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _offline_research_data(symbol: str):
    from app.trading.research.canonical import (
        AssetIdentity,
        AssetResearchData,
        CanonicalAssetType,
        DataQuality,
        FreshnessStatus,
        PriceBar,
        PriceSeries,
        QualityStatus,
        ResearchProvenance,
    )

    retrieved_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    asset_type = CanonicalAssetType.CRYPTO if symbol == "BTC" else CanonicalAssetType.EQUITY
    asset = AssetIdentity(symbol, asset_type, currency="USD")
    bars = tuple(
        PriceBar(
            retrieved_at - timedelta(days=40 - index),
            value,
            value,
            value,
            value,
            Decimal("100"),
        )
        for index, value in enumerate(
            Decimal("100") + Decimal(index) * Decimal("1.5") for index in range(40)
        )
    )
    prices = PriceSeries(
        asset,
        bars,
        "1d",
        "USD",
        ResearchProvenance("offline-fixture", "price_history", retrieved_at),
        bars[-1].timestamp,
        FreshnessStatus.FRESH,
        DataQuality(QualityStatus.COMPLETE),
    )
    return AssetResearchData(asset, prices=prices, quality=DataQuality(QualityStatus.COMPLETE))


def test_research_endpoints_use_real_dispatch_serialization_and_preserve_provenance(monkeypatch):
    import app.main as main_module
    from app.trading.research.jarvis_tools import JarvisResearchTools
    from app.trading.research.openbb_client import ResearchConfigurationError
    from app.trading.research.orchestration import ResearchOrchestrator

    token = "research-token"
    monkeypatch.setattr(main_module, "API_TOKEN", token)
    for key in ("FMP_API_KEY", "FRED_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    class OfflineMacroService:
        def get_asset_research_data(self, symbol, **_kwargs):
            return _offline_research_data(symbol)

        def get_macro_series(self, *_args, **_kwargs):
            raise ResearchConfigurationError("offline", provider="econdb")

    monkeypatch.setattr(
        main_module,
        "research_tools",
        JarvisResearchTools(orchestrator=ResearchOrchestrator(OfflineMacroService())),
    )
    client = TestClient(main_module.app)
    headers = {"Authorization": f"Bearer {token}"}

    providers = client.get("/api/research/providers", headers=headers)
    macro = client.get("/api/research/macro", headers=headers)
    run = client.post(
        "/api/research/run",
        headers=headers,
        json={"mode": "asset", "asset": "NVDA", "timeframe": "1y"},
    )

    assert providers.status_code == 200
    provider_payload = providers.json()["providers"]
    provider_map = {item["provider"]: item for item in provider_payload}
    assert provider_map["yfinance"]["configuration_state"] == "built_in"
    assert provider_map["yfinance"]["credential_configured"] is True
    assert provider_map["fmp"]["configuration_state"] == "not_configured"
    assert provider_map["fmp"]["credential_configured"] is False
    assert "test-only-key" not in json.dumps(provider_payload)
    assert macro.status_code == 200
    assert len(macro.json()["failures"]) == 5
    assert all(item["provider"] == "econdb" for item in macro.json()["failures"])
    assert run.status_code == 200
    payload = run.json()["research_payload"]
    assert payload["status"] == "success"
    assert payload["sources"][0]["provider"] == "offline-fixture"
    assert payload["sources"][0]["source_category"] == "price_history"
    assert payload["sources"][0]["retrieved_at"] == "2026-08-24T00:00:00+00:00"


def test_localhost_two_process_transport_executes_one_queued_action(tmp_path, monkeypatch):
    from app.device.agent import MacAgent
    from app.device.cloud import DeviceGateway
    from app.device.routes import router

    monkeypatch.setenv("JARVIS_DEVICE_TOKEN", "device-secret")
    gateway = DeviceGateway(tmp_path / "cloud.sqlite3", device_id="mac-1", clock=FakeClock())
    api = FastAPI()
    api.include_router(router)
    api.state.device_gateway = gateway
    client = TestClient(api)
    calls = []

    class Executor:
        def security_level(self, _command):
            return 0

        def execute_shell_command(self, command, *, force=False):
            calls.append((command, force))
            return "local result"

    def transport(method, url, headers, body=None):
        response = client.request(method, url, headers=headers, json=body)
        assert response.status_code < 400, response.text
        return response.json()

    agent = MacAgent(
        "http://127.0.0.1:8000",
        "device-secret",
        device_id="mac-1",
        state_path=tmp_path / "agent.sqlite3",
        executor=Executor(),
        transport=transport,
    )
    assert agent.poll_once() is True
    action = gateway.queue_action("shell_command", "echo localhost", action_id="local-1")
    assert action.action_id == "local-1"
    assert agent.poll_once() is True
    assert calls == [("echo localhost", False)]
    assert gateway.get_action("local-1").result.output == "local result"

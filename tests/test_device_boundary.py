"""Focused contracts for the local Mac capability boundary."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_device_models_expose_typed_action_lifecycle_contracts():
    from app.device.models import (
        ActionPayload,
        DeviceAction,
        DeviceDecision,
        DeviceLifecycle,
        DeviceResult,
        DeviceStatus,
        DeviceUnavailable,
    )

    payload = ActionPayload(action_type="shell_command", payload="echo hi")
    action = DeviceAction(action_id="a-1", payload=payload)
    decision = DeviceDecision(action_id="a-1", approved=True)
    result = DeviceResult(action_id="a-1", status="succeeded", output="hi")
    unavailable = DeviceUnavailable(reason="agent offline")
    status = DeviceStatus(available=True, device_id="mac-1")
    lifecycle = DeviceLifecycle(action=action, decision=decision, result=result)

    assert payload.action_type == "shell_command"
    assert action.action_id == decision.action_id == result.action_id == "a-1"
    assert unavailable.available is False
    assert status.available is True
    assert lifecycle.result.status == "succeeded"


def test_executor_preserves_app_name_validation_and_shell_security():
    from app.device.executor import (
        execute_shell_command,
        is_safe_app_name,
        security_level,
    )

    assert is_safe_app_name("Safari")
    assert not is_safe_app_name('Safari"; do evil')
    assert security_level("echo hi") == 0
    assert security_level("rm -rf /") == 2
    assert "[SECURITY]" in execute_shell_command("rm -rf /tmp/not-run")


def test_executor_launches_validated_app_with_osascript(monkeypatch):
    from app.device import executor

    run = Mock()
    monkeypatch.setattr(executor.subprocess, "run", run)

    result = executor.open_app("Safari")

    run.assert_called_once_with(
        ["osascript", "-e", 'tell application "Safari" to activate'],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.status == "succeeded"
    assert result.action == "open_app: Safari"


def test_executor_captures_screen_through_device_boundary(monkeypatch):
    from app.device import executor

    capture = Mock(return_value=b"jpeg")
    monkeypatch.setattr(executor, "capture_and_compress_screen", capture)

    assert executor.capture_screen() == b"jpeg"
    capture.assert_called_once_with()


def test_main_routes_mac_tools_through_executor(monkeypatch):
    import app.main as main

    from app.device.models import DeviceResult
    from app.models import ChatRequest, MessagePayload

    open_app = Mock(return_value=DeviceResult(
        status="succeeded",
        action="open_app: Safari",
        output="Erledigt. Safari wurde geöffnet.",
    ))
    monkeypatch.setattr(main, "open_app", open_app)
    monkeypatch.setattr(main, "get_session", lambda session_id: {"history": []})
    monkeypatch.setattr(main, "get_pending_command", lambda session_id: None)
    monkeypatch.setattr(main, "record_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "crypto_asset_from_research_question", lambda text: None)

    async def build_response(**kwargs):
        return kwargs

    monkeypatch.setattr(main, "_build_response", build_response)

    function_call = SimpleNamespace(name="execute_mac_command", args={
        "action_type": "open_app",
        "payload": "Safari",
    })
    gemini_response = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(function_call=function_call)])
    )])
    monkeypatch.setattr(main, "get_gemini_response", lambda *args, **kwargs: gemini_response)

    request = ChatRequest(
        session_id="boundary-test",
        timestamp=datetime.now(timezone.utc),
        payload=MessagePayload(type="text", content="open Safari"),
    )
    result = asyncio.run(main.chat_with_jarvis.__wrapped__(None, request))

    assert result["text"] == "Erledigt. Safari wurde geöffnet."
    assert result["action"] == "open_app: Safari"
    open_app.assert_called_once_with("Safari")

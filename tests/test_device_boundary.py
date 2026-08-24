"""Focused contracts for the local Mac capability boundary."""

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_contract_import_does_not_require_mac_only_modules():
    script = """
import builtins

real_import = builtins.__import__

def block_mac_modules(name, *args, **kwargs):
    if name in {"app.security", "app.vision"}:
        raise ImportError(f"blocked Mac-only module: {name}")
    return real_import(name, *args, **kwargs)

builtins.__import__ = block_mac_modules
from app.device.models import DeviceResult

assert DeviceResult(status="succeeded").status == "succeeded"
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=".",
    )

    assert result.returncode == 0, result.stderr


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


def test_rejected_result_has_a_matching_lifecycle_status():
    from app.device.models import ActionPayload, ActionStatus, DeviceAction, DeviceLifecycle, DeviceResult

    action = DeviceAction(
        action_id="reject-1",
        payload=ActionPayload(action_type="open_app", payload='Bad"Name'),
    )
    result = DeviceResult(action_id="reject-1", status="rejected")
    lifecycle = DeviceLifecycle(
        action=action,
        result=result,
        status=ActionStatus.REJECTED,
    )

    assert result.status == ActionStatus.REJECTED
    assert lifecycle.status == ActionStatus.REJECTED


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


def test_executor_rejects_invalid_app_name_without_launching(monkeypatch):
    from app.device import executor

    run = Mock()
    monkeypatch.setattr(executor.subprocess, "run", run)

    result = executor.open_app('Safari"; do evil')

    assert result.status == "rejected"
    assert result.action == "open_app_rejected"
    assert "unzulässige Zeichen" in result.output
    run.assert_not_called()


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


@pytest.mark.parametrize(
    ("error", "action"),
    [
        (subprocess.TimeoutExpired("osascript", 10), "open_app_timeout"),
        (OSError("osascript missing"), "open_app_error"),
    ],
)
def test_executor_reports_app_launch_failures(monkeypatch, error, action):
    from app.device import executor

    monkeypatch.setattr(executor.subprocess, "run", Mock(side_effect=error))

    result = executor.open_app("Safari")

    assert result.status == "failed"
    assert result.action == action


def test_executor_forwards_force_to_shell_router(monkeypatch):
    from app.device import executor

    shell = Mock(return_value="forced")
    monkeypatch.setattr(executor, "_execute_shell_command", shell)

    assert executor.execute_shell_command("rm -rf /tmp/nope", force=True) == "forced"
    shell.assert_called_once_with("rm -rf /tmp/nope", force=True)


def test_executor_captures_screen_through_device_boundary(monkeypatch):
    from app.device import executor

    capture = Mock(return_value=b"jpeg")
    monkeypatch.setattr(executor, "capture_and_compress_screen", capture)

    assert executor.capture_screen() == b"jpeg"
    capture.assert_called_once_with()


def test_executor_preserves_screenshot_failure(monkeypatch):
    from app.device import executor

    capture = Mock(side_effect=PermissionError("screen recording unavailable"))
    monkeypatch.setattr(executor, "capture_and_compress_screen", capture)

    with pytest.raises(PermissionError, match="screen recording unavailable"):
        executor.capture_screen()


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

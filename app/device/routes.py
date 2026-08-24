"""Authenticated cloud and outbound-agent API routes.

The frontend token and the Mac-agent token intentionally have separate
dependencies.  There is no route that accepts arbitrary device payloads from a
browser; only the cloud orchestrator creates queue entries.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .cloud import MAX_SCREENSHOT_BYTES, DeviceGateway
from .models import DeviceDecision


router = APIRouter(tags=["device"])


class DevicePollRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)


def _gateway(request: Request) -> DeviceGateway:
    gateway = getattr(request.app.state, "device_gateway", None)
    if gateway is None:
        gateway = DeviceGateway()
        request.app.state.device_gateway = gateway
    return gateway


def _configured_token(request: Request, kind: str) -> str:
    state_name = "jarvis_api_token" if kind == "user" else "jarvis_device_token"
    value = getattr(request.app.state, state_name, None)
    if callable(value):
        value = value()
    if value is None:
        value = os.environ.get("JARVIS_API_TOKEN" if kind == "user" else "JARVIS_DEVICE_TOKEN", "")
    return str(value or "")


def validate_token_configuration(
    api_token: str | None,
    device_token: str | None,
    *,
    agent_routes_enabled: bool = True,
) -> None:
    """Reject one bearer secret serving both frontend and agent trust zones."""

    api_token = str(api_token or "")
    device_token = str(device_token or "")
    if agent_routes_enabled and api_token and device_token and secrets.compare_digest(api_token, device_token):
        raise ValueError("JARVIS_API_TOKEN and JARVIS_DEVICE_TOKEN must differ")


def _bearer(request: Request) -> str:
    return request.headers.get("Authorization", "").removeprefix("Bearer ").strip()


def _require_user(request: Request) -> None:
    expected = _configured_token(request, "user")
    device_token = _configured_token(request, "device")
    try:
        validate_token_configuration(expected, device_token)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Invalid bearer token configuration") from exc
    provided = _bearer(request)
    if expected:
        if not secrets.compare_digest(provided, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing API token")
        return
    # Local no-token compatibility is deliberately anonymous.  Any bearer is
    # rejected, including the device credential, so trust zones cannot merge.
    if provided:
        raise HTTPException(status_code=401, detail="Bearer token requires JARVIS_API_TOKEN")
    # Match the existing API's safe local-development behavior.
    if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=401, detail="Remote access requires JARVIS_API_TOKEN")


def _require_device(request: Request) -> str:
    expected = _configured_token(request, "device")
    api_token = _configured_token(request, "user")
    try:
        validate_token_configuration(api_token, expected)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Invalid bearer token configuration") from exc
    provided = _bearer(request)
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing device token")
    claimed_id = request.headers.get("X-Jarvis-Device-ID")
    gateway = getattr(request.app.state, "device_gateway", None)
    if claimed_id and gateway is not None and claimed_id != gateway.device_id:
        raise HTTPException(status_code=403, detail="Device identity mismatch")
    return provided


@router.get("/api/device/status")
async def device_status(request: Request) -> dict[str, Any]:
    _require_user(request)
    return _gateway(request).status().model_dump(mode="json")


@router.get("/api/device/actions/{action_id}")
async def device_action_status(action_id: str, request: Request) -> dict[str, Any]:
    _require_user(request)
    lifecycle = _gateway(request).get_action(action_id)
    if lifecycle is None:
        raise HTTPException(status_code=404, detail="Unknown device action")
    return lifecycle.model_dump(mode="json")


@router.post("/api/device/actions/{action_id}/decision")
async def device_action_decision(action_id: str, request: Request) -> dict[str, Any]:
    _require_user(request)
    try:
        body = await request.json()
        decision = DeviceDecision.model_validate({**body, "action_id": body.get("action_id", action_id)})
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Malformed action decision") from exc
    if decision.action_id != action_id:
        raise HTTPException(status_code=422, detail="Action id mismatch")
    try:
        lifecycle = _gateway(request).decide(
            action_id,
            approved=decision.approved,
            reason=decision.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown device action") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return lifecycle.model_dump(mode="json")


@router.post("/api/device-agent/poll")
async def device_agent_poll(request: Request) -> dict[str, list[dict[str, Any]]]:
    _require_device(request)
    try:
        body = DevicePollRequest.model_validate(await request.json())
        result = _gateway(request).poll(body.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@router.post("/api/device-agent/actions/{action_id}/events")
async def device_agent_event(action_id: str, request: Request) -> dict[str, Any]:
    token = _require_device(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Malformed device event") from exc
    screenshot = body.get("screenshot_b64") if isinstance(body, dict) else None
    if isinstance(screenshot, str) and len(screenshot) > ((MAX_SCREENSHOT_BYTES + 2) // 3) * 4 + 4:
        raise HTTPException(status_code=413, detail="Screenshot exceeds size limit")
    try:
        lifecycle = _gateway(request).record_event(action_id, token, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown device action") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return lifecycle.model_dump(mode="json")


__all__ = ["router", "validate_token_configuration"]

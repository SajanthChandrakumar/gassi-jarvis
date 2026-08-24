"""Typed contracts shared by the cloud gateway and local Mac capability code."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ActionType(StrEnum):
    """Actions the local device boundary can execute."""

    OPEN_APP = "open_app"
    SHELL_COMMAND = "shell_command"
    TAKE_SCREENSHOT = "take_screenshot"


class ActionStatus(StrEnum):
    """States in the device action lifecycle."""

    QUEUED = "queued"
    DELIVERED = "delivered"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DENIED = "denied"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class DeviceConnectionStatus(StrEnum):
    """Reachability states for the configured Mac device."""

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class ActionPayload(BaseModel):
    """Validated payload passed to one local device action."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action_type: ActionType
    payload: str = Field(..., min_length=1)
    tainted: bool = False


class DeviceAction(BaseModel):
    """Action envelope identified independently from its payload."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action_id: str = Field(..., min_length=1)
    payload: ActionPayload | str
    device_id: str = "local-mac"
    status: ActionStatus = ActionStatus.QUEUED
    created_at: datetime = Field(default_factory=_utc_now)
    requires_approval: bool = False
    action_type: ActionType | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, values):
        if not isinstance(values, dict):
            return values
        payload = values.get("payload")
        action_type = values.get("action_type")
        if isinstance(payload, str) and action_type:
            values = dict(values)
            values["payload"] = {"action_type": action_type, "payload": payload}
        return values

    @model_validator(mode="after")
    def synchronize_action_type(self):
        payload_type = self.payload.action_type if isinstance(self.payload, ActionPayload) else None
        if self.action_type is None and payload_type is not None:
            self.action_type = payload_type
        elif payload_type is not None and self.action_type != payload_type:
            raise ValueError("action_type must match payload.action_type")
        return self

    @property
    def command(self) -> str:
        """Return the raw local payload for executor compatibility."""

        return self.payload.payload if isinstance(self.payload, ActionPayload) else self.payload


class DeviceDecision(BaseModel):
    """Human approval/denial for a specific action id."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action_id: str = Field(..., min_length=1)
    approved: bool
    decided_at: datetime = Field(default_factory=_utc_now)
    reason: str | None = None


class DeviceResult(BaseModel):
    """Terminal or immediate result returned by local execution."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action_id: str | None = None
    status: Literal["succeeded", "failed", "rejected", "unavailable", "expired"]
    output: str = ""
    action: str = ""
    error: str | None = None
    finished_at: datetime = Field(default_factory=_utc_now)


class DeviceUnavailable(BaseModel):
    """Explicit result for a device that cannot currently execute work."""

    model_config = ConfigDict(extra="forbid")

    available: Literal[False] = False
    reason: str = Field(..., min_length=1)
    action_id: str | None = None


class ApprovalRequired(BaseModel):
    """Agent event indicating that human approval is required."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=1)
    status: Literal["awaiting_approval"] = "awaiting_approval"
    expires_at: datetime | None = None


class ApprovedAction(BaseModel):
    """Cloud decision delivered to the outbound agent."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=1)
    status: Literal["approved"] = "approved"


class RejectedAction(BaseModel):
    """Cloud rejection delivered to the outbound agent."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(..., min_length=1)
    status: Literal["rejected"] = "rejected"
    reason: str | None = None


class DeviceStatus(BaseModel):
    """Current reachability and identity of the configured Mac device."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    device_id: str = Field(..., min_length=1)
    available: bool = False
    status: DeviceConnectionStatus = DeviceConnectionStatus.OFFLINE
    last_seen_at: datetime | None = None
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def synchronize_availability(self):
        if self.status == DeviceConnectionStatus.ONLINE:
            self.available = True
        elif self.available:
            self.status = DeviceConnectionStatus.ONLINE
        return self


class DeviceLifecycle(BaseModel):
    """Combined action, decision, and result view for status polling."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action: DeviceAction
    decision: DeviceDecision | None = None
    result: DeviceResult | None = None
    unavailable: DeviceUnavailable | None = None
    analysis: str | None = None
    status: ActionStatus = ActionStatus.QUEUED
    updated_at: datetime = Field(default_factory=_utc_now)


# Descriptive aliases keep the contract discoverable to callers that use the
# full name while preserving the short names used by the first local adapter.
DeviceActionPayload = ActionPayload
DeviceActionDecision = DeviceDecision
DeviceActionResult = DeviceResult
DeviceUnavailableResult = DeviceUnavailable
DeviceActionRequest = DeviceAction
ActionResult = DeviceResult
AgentUnavailable = DeviceUnavailable


__all__ = [
    "ActionPayload",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    "AgentUnavailable",
    "ApprovalRequired",
    "ApprovedAction",
    "DeviceAction",
    "DeviceActionDecision",
    "DeviceActionPayload",
    "DeviceActionResult",
    "DeviceActionRequest",
    "DeviceConnectionStatus",
    "DeviceDecision",
    "DeviceLifecycle",
    "DeviceResult",
    "DeviceStatus",
    "DeviceUnavailable",
    "DeviceUnavailableResult",
    "RejectedAction",
]

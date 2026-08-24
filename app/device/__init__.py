"""Local device capability boundary."""

from importlib import import_module

from .models import (
    ActionResult,
    ActionPayload,
    ActionStatus,
    ActionType,
    AgentUnavailable,
    ApprovalRequired,
    ApprovedAction,
    DeviceAction,
    DeviceActionRequest,
    DeviceDecision,
    DeviceLifecycle,
    DeviceResult,
    DeviceStatus,
    DeviceUnavailable,
    RejectedAction,
)


_EXECUTOR_EXPORTS = {
    "MacExecutor",
    "capture_screen",
    "execute_shell_command",
    "is_safe_app_name",
    "open_app",
    "security_level",
}


def __getattr__(name: str):
    """Load Mac-only implementations only when an executor is requested."""

    if name in _EXECUTOR_EXPORTS:
        executor = import_module(f"{__name__}.executor")
        return getattr(executor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActionPayload",
    "ActionResult",
    "ActionStatus",
    "ActionType",
    "AgentUnavailable",
    "ApprovalRequired",
    "ApprovedAction",
    "DeviceAction",
    "DeviceActionRequest",
    "DeviceDecision",
    "DeviceLifecycle",
    "DeviceResult",
    "DeviceStatus",
    "DeviceUnavailable",
    "RejectedAction",
    "MacExecutor",
    "capture_screen",
    "execute_shell_command",
    "is_safe_app_name",
    "open_app",
    "security_level",
]

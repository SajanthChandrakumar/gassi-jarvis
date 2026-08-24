"""The only boundary for local macOS capabilities.

The cloud-facing route should pass device work here instead of importing
subprocess, the security router, or screenshot implementation directly.
"""

import re
import subprocess

from app.security import evaluate_security_level, execute_shell_command as _execute_shell_command
from app.vision import capture_and_compress_screen

from .models import DeviceResult


_SAFE_APP_NAME = re.compile(r"^[A-Za-z0-9 ._\-]{1,64}$")


def is_safe_app_name(name: str) -> bool:
    """Return whether an app name is safe to interpolate into AppleScript."""

    return isinstance(name, str) and _SAFE_APP_NAME.match(name) is not None


def validate_app_name(name: str) -> bool:
    """Compatibility alias for the app-name allowlist."""

    return is_safe_app_name(name)


def open_app(name: str) -> DeviceResult:
    """Open one allowlisted application using macOS AppleScript."""

    if not is_safe_app_name(name):
        return DeviceResult(
            status="rejected",
            action="open_app_rejected",
            output=f"Den App-Namen '{name}' habe ich abgelehnt — er enthält unzulässige Zeichen.",
        )

    try:
        subprocess.run(
            ["osascript", "-e", f'tell application "{name}" to activate'],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return DeviceResult(
            status="failed",
            action="open_app_timeout",
            output=f"Timeout beim Öffnen von {name}.",
        )
    except OSError as error:
        return DeviceResult(
            status="failed",
            action="open_app_error",
            output=f"Fehler beim Öffnen von {name}: {error}",
            error=str(error),
        )

    return DeviceResult(
        status="succeeded",
        action=f"open_app: {name}",
        output=f"Erledigt. {name} wurde geöffnet.",
    )


def security_level(command: str) -> int:
    """Classify a shell command using Jarvis' existing security router."""

    return evaluate_security_level(command)


def execute_shell_command(command: str, force: bool = False) -> str:
    """Classify and execute a shell command through the existing router."""

    return _execute_shell_command(command, force=force)


def capture_screen() -> bytes:
    """Capture a compressed screen image without persisting it here."""

    return capture_and_compress_screen()


class MacExecutor:
    """Small object adapter for future local-agent composition."""

    is_safe_app_name = staticmethod(is_safe_app_name)
    validate_app_name = staticmethod(validate_app_name)
    open_app = staticmethod(open_app)
    security_level = staticmethod(security_level)
    execute_shell_command = staticmethod(execute_shell_command)
    capture_screen = staticmethod(capture_screen)


__all__ = [
    "MacExecutor",
    "capture_screen",
    "execute_shell_command",
    "is_safe_app_name",
    "open_app",
    "security_level",
    "validate_app_name",
]

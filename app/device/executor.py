"""The only boundary for local macOS capabilities.

The cloud-facing route should pass device work here instead of importing
subprocess, the security router, or screenshot implementation directly.
"""

import os
import re
import subprocess
from pathlib import Path

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


def execute_shell_command(
    command: str,
    force: bool = False,
    *,
    cwd: str | Path | None = None,
) -> str:
    """Classify and execute a shell command through the existing router."""

    if cwd is None:
        return _execute_shell_command(command, force=force)
    return _execute_shell_command(command, force=force, cwd=str(cwd))


def capture_screen() -> bytes:
    """Capture a compressed screen image without persisting it here."""

    return capture_and_compress_screen()


class MacExecutor:
    """Small object adapter for future local-agent composition."""

    def __init__(self, shell_cwd: str | Path | None = None) -> None:
        configured = shell_cwd if shell_cwd is not None else os.environ.get("JARVIS_SHELL_CWD", "")
        path = Path(configured) if configured else None
        if path is None or not path.is_absolute() or not path.is_dir():
            raise ValueError("JARVIS_SHELL_CWD must be an existing absolute directory")
        self.shell_cwd = str(path)

    def is_safe_app_name(self, name: str) -> bool:
        return is_safe_app_name(name)

    def validate_app_name(self, name: str) -> bool:
        return validate_app_name(name)

    def open_app(self, name: str) -> DeviceResult:
        return open_app(name)

    def security_level(self, command: str) -> int:
        return security_level(command)

    def execute_shell_command(self, command: str, force: bool = False) -> str:
        return execute_shell_command(command, force=force, cwd=self.shell_cwd)

    def capture_screen(self) -> bytes:
        return capture_screen()


__all__ = [
    "MacExecutor",
    "capture_screen",
    "execute_shell_command",
    "is_safe_app_name",
    "open_app",
    "security_level",
    "validate_app_name",
]

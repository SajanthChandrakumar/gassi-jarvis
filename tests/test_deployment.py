"""Static deployment contracts for the cloud image and user Mac agent."""

from __future__ import annotations

import os
import plistlib
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cloud_and_device_requirements_keep_runtime_pins_and_split_mac_dependencies():
    cloud = _text("requirements-cloud.txt")
    device = _text("requirements-device.txt")

    assert "fastapi==0.136.3" in cloud
    assert "uvicorn==0.40.0" in cloud
    assert "openbb==4.7.2" in cloud
    assert "Pillow" not in cloud
    assert "pydantic==2.13.3" in device
    assert "Pillow==12.2.0" in device


def test_cloud_dockerfile_is_unprivileged_and_installs_cloud_requirements():
    dockerfile = _text("Dockerfile")

    assert "COPY requirements-cloud.txt" in dockerfile
    assert re.search(r"^USER\s+jarvis(?::jarvis)?\s*$", dockerfile, re.MULTILINE)
    assert "COPY . ." not in dockerfile
    assert "--no-cache-dir" in dockerfile
    assert "CMD [\"uvicorn\", \"app.main:app\"" in dockerfile


def test_cloud_docker_context_excludes_mac_capabilities_and_launchd_files():
    ignored = _text(".dockerignore")

    for path in (
        "app/device/agent.py",
        "app/device/executor.py",
        "app/device/state.py",
        "app/security.py",
        "app/vision.py",
        "deploy/launchd/",
        "scripts/run_local_compat.py",
    ):
        assert path in ignored
    assert "*.applescript" in ignored
    assert "*.scpt" in ignored


def test_compose_binds_localhost_and_persists_cloud_state():
    compose = _text("compose.yaml")

    assert "env_file:" in compose
    assert "JARVIS_CLOUD_ENV_FILE" in compose
    assert "127.0.0.1:${JARVIS_CLOUD_PORT:-8000}:8000" in compose
    assert "jarvis_chroma:/data/chroma" in compose
    assert "jarvis_sessions:/data/sessions" in compose
    assert "jarvis_device:/data/device" in compose
    assert "JARVIS_BRAIN_DIR: /data/chroma" in compose
    assert "JARVIS_SESSIONS_FILE: /data/sessions/jarvis_sessions.json" in compose
    assert "JARVIS_CLOUD_DB_PATH: /data/device/jarvis_cloud.sqlite3" in compose


def test_launch_agent_plist_is_valid_secret_free_and_keeps_agent_alive():
    plist_path = ROOT / "deploy/launchd/com.gassi.jarvis.mac-agent.plist"
    payload = plistlib.loads(plist_path.read_bytes())

    assert payload["Label"] == "com.gassi.jarvis.mac-agent"
    assert payload["KeepAlive"] is True
    assert payload["RunAtLoad"] is True
    assert payload["ProgramArguments"][:2] == ["/bin/sh", "-c"]
    serialized = plist_path.read_text(encoding="utf-8")
    assert "JARVIS_DEVICE_TOKEN" not in serialized
    assert "Bearer " not in serialized
    assert "launchctl bootstrap" not in serialized


def test_external_mac_env_example_is_0600_and_contains_placeholders_only():
    env_path = ROOT / "deploy/launchd/mac-agent.env.example"
    mode = os.stat(env_path).st_mode & 0o777
    text = env_path.read_text(encoding="utf-8")

    assert mode == 0o600
    for name in (
        "JARVIS_CLOUD_API_BASE_URL",
        "JARVIS_DEVICE_TOKEN",
        "JARVIS_DEVICE_ID",
        "JARVIS_DEVICE_AGENT_STATE_PATH",
        "JARVIS_SHELL_CWD",
        "JARVIS_AGENT_PROJECT_DIR",
        "JARVIS_AGENT_PYTHON",
    ):
        assert re.search(rf"^{name}=", text, re.MULTILINE)
    assert "CHANGE_ME" in text
    assert "AIza" not in text
    assert "sk-" not in text


def test_launchd_installer_is_opt_in_and_wrapper_reads_external_env():
    installer = _text("deploy/launchd/install.sh")
    wrapper = _text("deploy/launchd/run-mac-agent.sh")

    assert "mac-agent.env" in wrapper
    assert ". \"$ENV_FILE\"" in wrapper
    assert "exec \"${JARVIS_AGENT_PYTHON" in wrapper
    assert "LaunchAgents" in installer
    assert "launchctl bootstrap" not in installer
    assert "launchctl load" not in installer


def test_deployment_runbook_covers_tailscale_permissions_static_config_and_local_mode():
    docs = _text("docs/deployment.md")

    for phrase in (
        "Tailscale Serve",
        "app token",
        "Screen Recording",
        "Automation",
        "config.js",
        "scripts/run_local_compat.py",
        "JARVIS_DEVICE_TOKEN",
        "localhost",
    ):
        assert phrase in docs
    assert "apiBaseUrl" in docs
    assert "apiBaseUrl: \"https://" in docs
    assert "apiBaseUrl: \"https://" in docs and "/api" not in docs.split("apiBaseUrl: \"https://", 1)[1].split("\"", 1)[0]

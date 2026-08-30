"""Static deployment contracts for the cloud image and user Mac agent."""

from __future__ import annotations

import os
import plistlib
import re
import stat
import subprocess
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - optional local validation aid
    yaml = None


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

    if yaml is not None:
        parsed = yaml.safe_load(compose)
        cloud = parsed["services"]["cloud"]
        assert cloud["ports"] == ["127.0.0.1:${JARVIS_CLOUD_PORT:-8000}:8000"]
        assert set(parsed["volumes"]) == {"jarvis_chroma", "jarvis_sessions", "jarvis_device"}

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
    wrapper = Path.home() / ".local/share/jarvis/run-mac-agent.sh"
    assert payload["ProgramArguments"][2] == 'exec "$HOME/.local/share/jarvis/run-mac-agent.sh"'
    assert str(wrapper).endswith("/.local/share/jarvis/run-mac-agent.sh")
    serialized = plist_path.read_text(encoding="utf-8")
    assert "JARVIS_DEVICE_TOKEN" not in serialized
    assert "Bearer " not in serialized
    assert "launchctl bootstrap" not in serialized


def test_external_mac_env_example_is_0600_and_contains_placeholders_only():
    env_path = ROOT / "deploy/launchd/mac-agent.env.example"
    text = env_path.read_text(encoding="utf-8")

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


def test_launchd_installer_creates_0600_env_and_wrapper_loads_quoted_values(tmp_path):
    installer = _text("deploy/launchd/install.sh")
    wrapper = _text("deploy/launchd/run-mac-agent.sh")

    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/launchd/install.sh")],
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    installed_wrapper = home / ".local/share/jarvis/run-mac-agent.sh"
    installed_plist = home / "Library/LaunchAgents/com.gassi.jarvis.mac-agent.plist"
    env_file = home / ".config/jarvis/mac-agent.env"
    assert installed_wrapper.read_text(encoding="utf-8") == wrapper
    installed_payload = plistlib.loads(installed_plist.read_bytes())
    assert installed_payload["ProgramArguments"][2] == 'exec "$HOME/.local/share/jarvis/run-mac-agent.sh"'
    assert installed_wrapper.exists()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600

    marker = tmp_path / "command-expansion-marker"
    output = tmp_path / "stub-output"
    project_dir = tmp_path / "project dir"
    work_dir = tmp_path / "work dir"
    project_dir.mkdir()
    work_dir.mkdir()
    stub = tmp_path / "stub-agent"
    stub.write_text(
        "#!/bin/sh\nprintf '%s\\n%s\\n' \"$JARVIS_DEVICE_TOKEN\" \"$JARVIS_DEVICE_AGENT_STATE_PATH\" > \"$STUB_OUTPUT\"\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env_file.write_text(
        "\n".join(
            [
                "# comments and blank lines are accepted",
                'JARVIS_CLOUD_API_BASE_URL="https://cloud.example.test"',
                "JARVIS_DEVICE_TOKEN='literal $(touch %s)'" % marker,
                "JARVIS_DEVICE_ID=mac-quoted",
                'JARVIS_DEVICE_AGENT_STATE_PATH="/tmp/path with spaces/state.sqlite3"',
                'JARVIS_SHELL_CWD="%s"' % work_dir,
                'JARVIS_AGENT_PROJECT_DIR="%s"' % project_dir,
                'JARVIS_AGENT_PYTHON="%s"' % stub,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    run_env = os.environ.copy()
    run_env.update({"HOME": str(home), "STUB_OUTPUT": str(output)})
    run = subprocess.run([str(installed_wrapper)], env=run_env, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert output.read_text(encoding="utf-8").splitlines() == [
        "literal $(touch %s)" % marker,
        "/tmp/path with spaces/state.sqlite3",
    ]
    assert not marker.exists()

    assert "mac-agent.env" in wrapper
    assert "source" not in wrapper
    assert ". \"$ENV_FILE\"" not in wrapper
    assert "exec \"${JARVIS_AGENT_PYTHON" in wrapper
    assert "LaunchAgents" in installer
    assert "install -m 600" in installer
    assert "chmod 600" in installer
    assert "launchctl bootstrap" not in installer
    assert "launchctl load" not in installer


@pytest.mark.parametrize("bad_line", [
    "UNKNOWN_KEY=value",
    "JARVIS_DEVICE_ID=\"unterminated",
    "JARVIS_DEVICE_ID=unquoted value",
])
def test_wrapper_rejects_unknown_or_malformed_env_without_running_agent(tmp_path, bad_line):
    wrapper = ROOT / "deploy/launchd/run-mac-agent.sh"
    env_file = tmp_path / "mac-agent.env"
    env_file.write_text(bad_line + "\n", encoding="utf-8")
    env_file.chmod(0o600)
    marker = tmp_path / "stub-ran"
    stub = tmp_path / "stub-agent"
    stub.write_text("#!/bin/sh\ntouch \"%s\"\n" % marker, encoding="utf-8")
    stub.chmod(0o755)
    run_env = os.environ.copy()
    run_env.update({"HOME": str(tmp_path), "JARVIS_AGENT_ENV_FILE": str(env_file), "JARVIS_AGENT_PYTHON": str(stub)})

    result = subprocess.run([str(wrapper)], env=run_env, capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize("kind", ["symlink", "directory", "group-readable"])
def test_wrapper_rejects_unsafe_env_file(kind, tmp_path):
    wrapper = ROOT / "deploy/launchd/run-mac-agent.sh"
    target = tmp_path / "target"
    target.write_text("JARVIS_DEVICE_ID=mac\n", encoding="utf-8")
    target.chmod(0o600)
    if kind == "symlink":
        env_file = tmp_path / "mac-agent.env"
        env_file.symlink_to(target)
    elif kind == "directory":
        env_file = tmp_path / "mac-agent.env"
        env_file.mkdir()
    else:
        env_file = target
        env_file.chmod(0o640)
    run_env = os.environ.copy()
    run_env.update({"HOME": str(tmp_path), "JARVIS_AGENT_ENV_FILE": str(env_file)})

    result = subprocess.run([str(wrapper)], env=run_env, capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "env file" in result.stderr.lower()


def test_deployment_runbook_covers_tailscale_permissions_static_config_and_local_mode():
    docs = _text("docs/deployment.md")

    for phrase in (
        "Tailscale Serve",
        "identity/app-cap",
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

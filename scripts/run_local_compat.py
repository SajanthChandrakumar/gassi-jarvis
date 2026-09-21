"""Run the cloud and outbound Mac agent together for local migration testing.

This compatibility helper is intentionally opt-in and never installs a
LaunchAgent or exposes a listener beyond the local uvicorn process.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def main() -> int:
    cloud_url = os.environ.get("JARVIS_CLOUD_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("JARVIS_DEVICE_TOKEN", "")
    shell_cwd = os.environ.get("JARVIS_SHELL_CWD", "")
    if not token:
        raise SystemExit("JARVIS_DEVICE_TOKEN is required")
    if not shell_cwd or not Path(shell_cwd).is_absolute() or not Path(shell_cwd).is_dir():
        raise SystemExit("JARVIS_SHELL_CWD must be an existing absolute directory")

    env = os.environ.copy()
    env["JARVIS_CLOUD_API_BASE_URL"] = cloud_url
    cloud = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"], env=env)
    agent = subprocess.Popen([sys.executable, "-m", "app.device.agent"], env=env)
    processes = (cloud, agent)

    def stop(_signum: int, _frame: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        return cloud.wait()
    finally:
        stop(0, None)
        for process in processes:
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())

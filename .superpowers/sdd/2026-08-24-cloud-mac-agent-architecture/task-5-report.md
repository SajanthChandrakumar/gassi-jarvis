# Task 5 report: cloud and launchd deployment

## Outcome

Added a split cloud/device dependency surface and deployment metadata while
leaving the existing `requirements.txt` OpenBB and Uvicorn pins unchanged.
The cloud image installs only `requirements-cloud.txt`, runs as unprivileged
user `jarvis`, and receives no Mac executor, security, vision, AppleScript, or
launchd implementation through its ignored build context. Compose binds the
cloud port to localhost and persists ChromaDB, sessions, and the cloud device
queue in named volumes.

Added secret-free, user-scoped LaunchAgent assets: a `KeepAlive` plist, an
external `0600` env example, an env-loading wrapper, and an opt-in installer.
The installer was not run and the LaunchAgent was not installed or loaded.
`docs/deployment.md` covers Tailscale Serve app tokens, macOS Screen Recording
and Automation permissions, static-host `config.js`, and the existing local
two-process compatibility launcher.

## TDD evidence

The deployment contract tests were written before the artifacts. The first
focused run was RED:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_deployment.py
8 failed
```

The failures were the expected missing requirements, Docker metadata, context
exclusions, Compose, plist, env example, installer/wrapper, and runbook
contracts. After the minimal implementation, the focused GREEN run was:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_deployment.py
8 passed
```

## Validation

```text
/usr/bin/plutil -lint deploy/launchd/com.gassi.jarvis.mac-agent.plist
deploy/launchd/com.gassi.jarvis.mac-agent.plist: OK

sh -n deploy/launchd/install.sh deploy/launchd/run-mac-agent.sh
node --check app/static/app.js
git diff --check

GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
285 passed, 1 warning in 2.81s
```

The warning is the pre-existing Starlette/httpx compatibility deprecation.
Docker CLI is not installed in this environment, so no Docker build or run
was attempted; image validation is limited to Dockerfile/.dockerignore static
contracts. No deployment, install, launchd load, or push was performed.

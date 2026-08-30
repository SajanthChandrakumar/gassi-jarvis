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
`docs/deployment.md` covers Tailscale Serve identity/app-capability context, macOS Screen Recording
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

## Review-fix TDD and findings resolution

The review regression tests were added before the fixes. After correcting an
initial test-collection typo, the focused RED run was:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_deployment.py tests/test_frontend_config.py
8 failed, 18 passed, 1 warning
```

The focused GREEN run after implementation was:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_deployment.py tests/test_frontend_config.py
26 passed, 1 warning in 2.58s
```

Resolved findings:

- The LaunchAgent wrapper now rejects symlinks, non-regular files, and any
  group/other permissions; it accepts only the documented `JARVIS_*` keys,
  comments/blanks, and safely parsed quoted values. It performs no sourcing,
  eval, or command expansion, and the installer creates the external env file
  with mode `0600`. Temp-HOME tests run the installer and wrapper against a
  stub agent without loading launchd. The Application Support path is quoted.
- Both `/config.js` and the browser normalizer accept only explicit HTTP(S)
  origins with an empty or root path; `/api` and other non-root paths fall
  back to same-origin. Python and Node behavioral tests cover the boundary.
- The runbook now creates `~/.config/jarvis`, distinguishes static-host CORS
  origin from API origin, and explains that Tailscale identity/app-capability
  headers are not Jarvis auth; the Jarvis bearer tokens remain mandatory.
- The deployment tests parse the plist and Compose document when PyYAML is
  available, and verify the installed wrapper target and runtime loader.

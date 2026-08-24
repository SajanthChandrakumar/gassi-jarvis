# Task 7 report: document and verify the cloud/Mac architecture

## Outcome

Updated the architecture documentation to match the implemented three-zone
split:

- `README.md` is concise and now explains the frontend, cloud, and outbound
  Mac-agent zones, quick-start paths, token roles, origin configuration,
  action lifecycle, screenshot handling, cloud-safe services, and explicit
  out-of-scope portfolio APIs/trading.
- `architecture.md` documents the trust-zone data flow, Pydantic contracts,
  frontend/cloud and cloud/agent route surfaces, heartbeat/offline behavior,
  delivery leases, local/cloud approval TTLs, boot-bound monotonic expiry,
  payload-hash idempotency, screenshot in-memory bounds, configuration/origin
  rules, operations/recovery, and migration risks.
- `SECURITY.md` documents the threat model, separate bearer credentials,
  local classifier/HITL controls, the selected cloud-as-approval-relay trust
  limitation, screenshot non-persistence, permissions, incident recovery, and
  known one-device/legacy limitations.
- `docs/deployment.md` is a focused Compose/Tailscale/static-host/LaunchAgent
  runbook with mode-0600 env handling, Screen Recording/Automation
  permissions, localhost compatibility mode, status/lifecycle operations, and
  recovery/migration procedures.
- Included the pre-existing untracked plan:
  `docs/superpowers/plans/2026-08-24-cloud-mac-agent-architecture.md`.

The configured Obsidian/external note was not edited, as explicitly requested;
the controller is reconciling that note separately.

## Verification

All checks were run from this worktree using the compatible Python 3.13
environment and a non-secret test-only `GOOGLE_API_KEY`:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
311 passed, 1 warning in 5.79s

node --check app/static/app.js
/usr/bin/plutil -lint deploy/launchd/com.gassi.jarvis.mac-agent.plist
deploy/launchd/com.gassi.jarvis.mac-agent.plist: OK
sh -n deploy/launchd/install.sh deploy/launchd/run-mac-agent.sh
git diff --check

GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q \
  tests/test_task6_security.py -k localhost_two_process
1 passed, 17 deselected, 1 warning
```

The deployment/frontend contract subset also passed (`26 passed, 1 warning`).
A read-only Markdown link check covered the four changed docs and found all
local targets. Docker CLI is unavailable in this environment, so Docker
build/run was not attempted; validation is limited to the existing static
Dockerfile/Compose/context tests. No deployment, merge, push, or LaunchAgent
install/load was performed.

The only test warning is the pre-existing Starlette/httpx compatibility
deprecation warning.

## Remaining limitations

- The implementation supports one configured Mac identity only.
- Cloud-authenticated approval is an approval relay, not independent proof of
  a human gesture; cloud state and both bearer tokens remain in the HitL trust
  base.
- Existing legacy pending raw shell commands in `jarvis_sessions.json` require
  re-issuing as typed device actions; no direct cloud execution fallback is
  documented.
- Docker runtime/build smoke testing remains unverified because Docker CLI is
  unavailable. The docs do not claim deployment success.
- No live Mac, Calendar, provider, tunnel, or launchd operation was performed.

## Review resolution (fix round 1)

Applied the reviewer-requested corrections without another broad rewrite:

- Restored concise README onboarding: Python 3.13/macOS prerequisites,
  runtime plus `requirements-dev.txt` installation, Calendar OAuth, local and
  tunnel/Tailscale operation, forwarded-header caveats, API examples, PWA
  install/use, and the Homepage memory widget.
- Restored the deterministic research phase boundary and links for OpenBB,
  canonical data, relevance, asset reports, historical/statistical research,
  and natural-language orchestration. Research is explicitly cloud-only and
  never creates device intents.
- Corrected exact defaults/requirements for CORS, same-origin frontend config,
  log level, Compose port/env-file, brain/session/cloud/device state paths,
  required agent URL/token/sandbox/wrapper paths, and the one-device identity.
- Documented the point-in-time offline race: new requests observed offline are
  rejected, but already queued/leased work can reclaim/redeliver; frontend UI
  timeout does not cancel cloud work.
- Corrected trust semantics: the frontend token can decide; the device token
  cannot approve, but can forge authenticated agent events/results if
  compromised. Decisions carry `action_id`, `approved`, `reason`, and
  `decided_at`; browser decision requests never carry executable payload text.
- Explicitly recorded that committed examples contain placeholders only and
  no real secrets.
- Removed the general database-schema-migration claim and avoided implying
  that research causes device work.

Fix-round verification:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
311 passed, 1 warning in 6.28s

node --check app/static/app.js
/usr/bin/plutil -lint deploy/launchd/com.gassi.jarvis.mac-agent.plist
deploy/launchd/com.gassi.jarvis.mac-agent.plist: OK
sh -n deploy/launchd/install.sh deploy/launchd/run-mac-agent.sh
git diff --check
```

The Markdown link check covered five docs and 39 links; all local targets
exist. The localhost integration remains an in-process FastAPI `TestClient`
transport using independent cloud/agent state, not a real TCP two-process
listener test. Docker CLI remains unavailable, so Docker build/run was not
attempted. No external/Obsidian note was edited.

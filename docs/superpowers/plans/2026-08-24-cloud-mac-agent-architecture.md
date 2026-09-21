# Jarvis Cloud / Mac Agent Architecture Implementation Plan

**Goal:** Separate the always-on Linux cloud services from Mac-only device control while preserving the vanilla PWA, deterministic research, and Human-in-the-Loop safety.

**Architecture:** The PWA calls only FastAPI. The cloud owns Gemini, memory, Calendar, and research, and places device directives in a SQLite queue. A launchd-managed Mac process polls outbound, reclassifies and executes device actions locally, and reports structured events.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, sqlite3, vanilla HTML/CSS/JavaScript, Docker Compose, launchd, Tailscale.

## Global Constraints

- Keep `app/main.py` free of subprocess, AppleScript, screenshot, `app.security`, and `app.vision` imports or calls.
- Preserve `/api/chat`, research endpoints, voice/TTS, PWA installability, and authoritative deterministic `research_payload` semantics.
- The frontend never calls the Mac agent directly.
- Use one configured Mac identity and separate frontend/device bearer tokens.
- The Mac agent is the authoritative shell classifier and owns pending device payloads and the 300-second approval TTL.
- Reject new device work immediately while the agent is offline; never replay an executed action.
- Do not persist or log screenshot bytes.
- Keep Calendar cloud-side and do not create portfolio APIs, React, Kubernetes, deployment, merge, or push side effects.
- Standard tests require no internet, financial provider credentials, or live device access.

### Task 1: Isolate the Mac capability boundary

Create `app/device/models.py` with typed status, action payload, decision, result, unavailable, and lifecycle contracts. Create `app/device/executor.py` by moving app-name validation, AppleScript launching, shell classification/execution, and screenshot capture out of `app/main.py`. Preserve current behavior while routing the existing entrypoint through the executor. Add focused failing tests first, prove they fail for the missing boundary, implement minimally, run focused and full tests, then commit `refactor(device): isolate Mac capability boundary`.

### Task 2: Add the outbound Mac agent

Create `app/device/state.py` using stdlib SQLite for pending payloads, payload hashes, terminal results, and replay tombstones. Create `app/device/agent.py` with a two-second outbound poll loop, HTTPS-or-loopback URL validation, separate bearer auth, bounded reconnect backoff, 30-second delivery leases, local reclassification, local monotonic 300-second approval expiry, and record-before-report idempotency. The agent must execute its stored payload after an action-ID-only approval. Add failing state-machine and redelivery tests before implementation, then commit `feat(device): add outbound Mac agent`.

### Task 3: Route cloud actions through the authenticated agent

Create `app/device/cloud.py` with a SQLite single-device queue, 10-second offline detection, leases, idempotent events/decisions, bounded waits, and structured unavailable results. Create `app/device/routes.py` with frontend status/action/decision endpoints under `JARVIS_API_TOKEN` and poll/event endpoints under `JARVIS_DEVICE_TOKEN`. Wire `app/main.py` to the cloud gateway, extend `ChatResponse.device_action`, keep Calendar approval separate, and remove every direct local-execution import/call from the cloud entrypoint. Poll acts as heartbeat. Screenshot event bytes are size-limited, analyzed in memory with cloud Gemini, and excluded from SQLite/logs. Add a local two-process launcher. Test offline research, token separation, mismatched identity, malformed actions, action lifecycle, approval replay/expiry, and screenshot persistence before committing `feat(cloud): route device actions through authenticated agent`.

### Task 4: Configure the PWA API origin

Serve non-cached `/config.js` from `JARVIS_FRONTEND_API_BASE_URL`, defaulting to same origin. Load it before `app.js`; route every API fetch through one URL helper; preserve the service worker's API network-only behavior. Add structured device status, approval decision, and action-result polling without redesigning the Command Center. Write failing UI contract tests first and commit `feat(ui): support configurable cloud API origin`.

### Task 5: Add cloud and launchd deployment

Split cloud/device requirements without changing tested OpenBB/Uvicorn pins. Harden the cloud Docker image to run unprivileged and physically exclude Mac executor, security, vision, AppleScript, and launchd files. Add Compose with localhost binding, persistent Chroma/session/device volumes, and an external env example. Add a secret-free user LaunchAgent with `KeepAlive`, a `0600` external env example, and an installer that is committed but not run. Document Tailscale Serve, macOS Screen Recording/Automation permissions, static-host `config.js`, and local two-process mode. Validate Docker metadata and plist behavior, then commit `ops: add cloud and launchd deployment`.

### Task 6: Harden split-service security boundaries

Add any missing acceptance regressions for offline research, bad credentials, local classification, tainted forced approval, 300-second expiry, substitution/replay, redelivery idempotency, screenshot non-persistence, cross-origin frontend requests, cloud import boundaries, and unchanged research endpoints. Use behavior tests rather than source-text assertions where executable boundaries exist. Run focused checks and commit `test: harden split-service security boundaries`.

### Task 7: Document and verify the architecture

Update README, `architecture.md`, `SECURITY.md`, and a focused deployment runbook with the three trust zones, contracts, configuration, operating procedures, selected cloud-as-approval-relay limitation, offline semantics, and migration compatibility risks. Update the configured Obsidian Jarvis project note without secrets. Run the full credential-free suite, JavaScript syntax check, `plutil -lint`, Docker build/run boundary smoke test when Docker is available, localhost two-process smoke test, inspect the diff/status, and commit `docs: document cloud-device architecture`.

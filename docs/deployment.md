# Cloud and Mac-agent deployment runbook

This runbook describes the implemented split topology. It does not claim a
successful deployment, Docker build, or LaunchAgent load. Repository checks
validate metadata and scripts only; operators must review and run the commands
explicitly.

## Topology and trust

The three zones are:

- **Frontend:** vanilla PWA on the cloud root or a separate static host. It
  uses only `JARVIS_API_TOKEN` and calls FastAPI through the configured API
  origin.
- **Cloud:** FastAPI, Gemini, ChromaDB memory, sessions, Google Calendar,
  deterministic read-only research, and the SQLite device queue. It contains
  no Mac executor, shell classifier, screenshot, AppleScript, or launchd
  implementation in the cloud image.
- **Mac agent:** one launchd-managed, outbound-only process with the local
  executor and agent SQLite state. It uses only `JARVIS_DEVICE_TOKEN` and the
  configured `JARVIS_DEVICE_ID`; it opens no inbound port.

The frontend never calls the Mac agent. The cloud is an approval relay and
durable coordinator, not independent human attestation: an operator must treat
the cloud process, queue, `JARVIS_API_TOKEN`, and `JARVIS_DEVICE_TOKEN` as part
of the HitL trust base. The agent still reclassifies every shell command and
rejects payload substitution/replay.

## Cloud with Compose

Create an external env file, replace all placeholders, and keep it outside the
repository. Use long, independently generated values for both bearer tokens:

```bash
mkdir -p ~/.config/jarvis
cp deploy/cloud.env.example ~/.config/jarvis/cloud.env
chmod 600 ~/.config/jarvis/cloud.env
# Edit ~/.config/jarvis/cloud.env before starting anything.
JARVIS_CLOUD_ENV_FILE="$HOME/.config/jarvis/cloud.env" \
  docker compose -f compose.yaml up --build
```

`compose.yaml` binds the cloud to `127.0.0.1:${JARVIS_CLOUD_PORT:-8000}` and
persists three named volumes:

- `jarvis_chroma` → `/data/chroma` (`JARVIS_BRAIN_DIR`)
- `jarvis_sessions` → `/data/sessions` (`JARVIS_SESSIONS_FILE`)
- `jarvis_device` → `/data/device` (`JARVIS_CLOUD_DB_PATH`)

The image runs as the unprivileged `jarvis` user. Its Docker build context
excludes `app/device/agent.py`, `app/device/executor.py`,
`app/device/state.py`, `app/security.py`, `app/vision.py`, AppleScript files,
and launchd/development files. The cloud requirements preserve the tested
OpenBB and Uvicorn pins. Docker CLI availability is an environment concern;
when it is unavailable, do not infer build or runtime success from static
metadata.

## Private HTTPS exposure with Tailscale Serve

Keep the cloud listener local and expose it through Tailscale Serve:

```bash
tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Tailscale Serve identity/app-capability headers describe the transport
context. They do not replace Jarvis bearer authentication. The cloud still
requires `JARVIS_API_TOKEN` for frontend routes and `JARVIS_DEVICE_TOKEN` for
agent routes.

For a separately hosted PWA, set both the static-host CORS origin and the API
origin in the cloud env file:

```ini
JARVIS_ALLOWED_ORIGINS=https://jarvis-ui.example.test
JARVIS_FRONTEND_API_BASE_URL=https://jarvis-api.example.test
```

`JARVIS_FRONTEND_API_BASE_URL` is an HTTP(S) **origin/root** only: no
credentials, query, fragment, or `/api` path. Invalid values fall back to
same-origin. `GET /config.js` emits the validated value with
`Cache-Control: no-store`; a static host must provide the same contract before
`app.js` loads and must not serve a stale cached origin. All browser calls add
their existing `/api/...` path through one URL helper. The service worker
keeps `/config.js`, `/api/*`, and non-GET requests on the live network.

The static host equivalent is:

```js
window.JARVIS_CONFIG = { apiBaseUrl: "https://jarvis-api.example.test" };
```

The value is an origin/root, not `https://jarvis-api.example.test/api`.

## Mac LaunchAgent

The committed plist is secret-free and has `KeepAlive` and `RunAtLoad`. The
wrapper reads a regular, non-symlink external env file and accepts only the
documented keys. It requires mode `0600` (or stricter), an existing absolute
`JARVIS_SHELL_CWD`, and explicit project/Python paths:

```bash
mkdir -p ~/.config/jarvis
cp deploy/launchd/mac-agent.env.example ~/.config/jarvis/mac-agent.env
chmod 600 ~/.config/jarvis/mac-agent.env
# Edit and review this file; do not leave CHANGE_ME values.
```

Required Mac-agent values:

```ini
JARVIS_CLOUD_API_BASE_URL=https://jarvis-api.example.test
JARVIS_DEVICE_TOKEN=long-device-only-secret
JARVIS_DEVICE_ID=local-mac
JARVIS_DEVICE_AGENT_STATE_PATH="/Users/name/Library/Application Support/Jarvis/device-agent.sqlite3"
JARVIS_SHELL_CWD=/Users/name/JarvisSandbox
JARVIS_AGENT_PROJECT_DIR=/Users/name/Projects/gassi-jarvis
JARVIS_AGENT_PYTHON=/Users/name/Projects/gassi-jarvis/.venv/bin/python
```

`JARVIS_CLOUD_API_BASE_URL` must use HTTPS for a remote cloud. HTTP is
accepted only for `localhost`, `127.0.0.1`, or `::1` in local compatibility
mode. The agent polls every two seconds, backs off at most 30 seconds, and
sends its heartbeat with the same authenticated poll. The cloud reports the
device offline after 10 seconds and rejects new device actions while offline;
it does not queue surprise work for later execution. Delivered actions lease
for 30 seconds. Approval is 300 seconds locally and cloud-side, and the local
boot/process identity invalidates an old monotonic deadline after restart.

On macOS, grant the **Python/Terminal host running the agent**:

- **Screen Recording**, needed by `screencapture`;
- **Automation**, needed by AppleScript app activation.

These permissions belong only to the Mac zone; the cloud does not request or
receive them. Review the wrapper and plist, then optionally run
`deploy/launchd/install.sh`. The installer copies files and creates the
external env file; it does not load or start launchd during repository
validation. Loading is an explicit operator action after review.

## Local two-process compatibility mode

For migration and deterministic localhost testing, the existing one-command
helper starts uvicorn and the outbound agent together:

```bash
JARVIS_DEVICE_TOKEN=long-device-only-secret \
JARVIS_SHELL_CWD="$HOME/JarvisSandbox" \
JARVIS_CLOUD_API_BASE_URL=http://127.0.0.1:8000 \
python scripts/run_local_compat.py
```

`JARVIS_SHELL_CWD` must already exist and be absolute. This mode binds
FastAPI to loopback, does not install/load launchd, and is not a production
topology. Keep cloud and agent SQLite paths separate when testing.

## Operations

1. Start the cloud with the external cloud env and verify the local listener
   is bound only to the expected loopback port.
2. Start the agent manually or through the reviewed LaunchAgent env. Verify
   `GET /api/device/status` with the frontend token reports the expected
   `device_id` and a recent heartbeat.
3. Submit a safe device action through the normal chat route. Track its
   `action_id` with `GET /api/device/actions/{action_id}`. Approval decisions
   use the frontend token and action ID only.
4. If the Mac is offline, expect a structured unavailable response immediately;
   research, memory, chat, and cloud Calendar remain cloud-safe. Screenshot
   bytes are bounded and analyzed in memory only, never persisted in SQLite or
   logs.
5. Keep the cloud volume and local agent SQLite file backed up before planned
   upgrades. Preserve these files across restarts so idempotency hashes,
   decisions, terminal results, and replay tombstones remain effective.

## Incident response and recovery

If either bearer token, the cloud process, or the Mac is suspected compromised:

1. Stop/unload the Mac agent and stop cloud exposure through the tunnel.
2. Rotate `JARVIS_API_TOKEN` and `JARVIS_DEVICE_TOKEN` independently in their
   external files; restart only after reviewing pending action lifecycles.
3. Do not approve pending actions while investigating. Inspect action IDs,
   statuses, decisions, and result metadata without copying any screenshot
   content.
4. Restarting is safe for completed actions because the agent records terminal
   results before reporting them; a later poll/event is idempotent. A pending
   approval from a new boot/process expires fail-closed.
5. If queue or agent state is lost, do not guess whether an action ran. Treat
   its outcome as unknown and ask the user to issue a new action after the
   incident is closed.

## Migration and compatibility risks

- This phase supports exactly one `JARVIS_DEVICE_ID` (`local-mac` by default);
  a second Mac needs an explicit enrollment/routing design.
- Existing `jarvis_sessions.json` may contain a legacy raw pending shell
  command. The cloud no longer executes that value; ask the user to reissue
  the action so it becomes a typed device action. Calendar pending data keeps
  its separate cloud approval path.
- `scripts/run_local_compat.py` is a compatibility bridge, not an agent
  server. Do not expose its loopback HTTP URL remotely.
- Keep the local agent SQLite file when upgrading. Older agents may not know
  newer action types; use a staged upgrade and verify heartbeat/status before
  allowing new work.
- Static-host deployments must update CORS and the API origin together. A
  stale `config.js` or `/api`-suffixed origin can make the PWA unavailable;
  there is intentionally no frontend fallback to direct Mac access.

See [`architecture.md`](../architecture.md) for the complete contract and
[`SECURITY.md`](../SECURITY.md) for residual risks. No deployment, merge, push,
or LaunchAgent load is implied by this documentation.

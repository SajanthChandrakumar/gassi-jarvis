# Gassi-Jarvis

Gassi-Jarvis is a self-hosted, voice-first assistant and deterministic
financial-research workspace. The installable vanilla PWA talks to FastAPI;
macOS control is performed by one outbound-only Mac agent. Shell commands and
calendar writes remain Human-in-the-Loop (HitL) gated.

![Jarvis research workspace](docs/jarvis-pwa.png)

## Architecture at a glance

```text
Frontend / PWA
  └─ HTTPS + JARVIS_API_TOKEN ──> Cloud FastAPI
                                  ├─ Gemini, sessions, ChromaDB memory
                                  ├─ Google Calendar (separate HitL path)
                                  ├─ deterministic read-only research
                                  └─ SQLite device-intent queue
                                      ▲ HTTPS + JARVIS_DEVICE_TOKEN
                                      │ outbound POST poll/events only
                                  Mac agent (launchd)
                                  └─ local classifier, shell, AppleScript,
                                     screenshots, device SQLite state
```

These are three trust zones, not three public services:

1. The frontend is an untrusted display/client. It knows only the frontend
   bearer and never calls the Mac agent or receives the device bearer.
2. The cloud is the always-on orchestration zone. It owns Gemini, memory,
   Calendar, research, and the durable single-device queue, but imports no
   local shell, AppleScript, screenshot, or launchd implementation.
3. The Mac agent is the local capability zone. It makes outbound requests,
   stores accepted payloads locally, reclassifies shell commands, executes
   macOS actions, and reports typed results. It starts no listener.

The frontend has no frontend-to-agent path. See
[`architecture.md`](architecture.md) for contracts and lifecycle details and
[`SECURITY.md`](SECURITY.md) for the threat model.

## What is cloud-safe

The cloud can serve chat, voice/TTS, session and ChromaDB memory, Google
Calendar, and the bounded financial-research endpoints while the Mac is
offline. Research is read-only and deterministic: Gemini may present results,
but does not calculate authoritative values, fill missing data, recommend
trades, or place orders. A future portfolio module remains cloud-side, but is
not implemented. The existing research contracts are documented in
[`docs/natural-language-quant-research.md`](docs/natural-language-quant-research.md)
and [`docs/trading-financial-contract.md`](docs/trading-financial-contract.md).

## Run locally

Use Python 3.13 and a compatible virtual environment. For tests and imports,
set a non-secret dummy `GOOGLE_API_KEY` if no Gemini key is available.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_API_KEY=your_gemini_key
export JARVIS_API_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For migration testing, `scripts/run_local_compat.py` starts cloud FastAPI and
the outbound agent together on loopback. It requires an existing absolute
`JARVIS_SHELL_CWD` and `JARVIS_DEVICE_TOKEN`; it does not install or load
launchd.

## Cloud and Mac deployment

The supported split deployment keeps the cloud port bound to localhost and
uses external, mode-0600 environment files:

```bash
mkdir -p ~/.config/jarvis
cp deploy/cloud.env.example ~/.config/jarvis/cloud.env
chmod 600 ~/.config/jarvis/cloud.env
JARVIS_CLOUD_ENV_FILE="$HOME/.config/jarvis/cloud.env" \
  docker compose -f compose.yaml up --build
```

Expose the cloud through Tailscale Serve or another private HTTPS tunnel. The
Mac LaunchAgent assets are committed but opt-in; review them and grant the
agent's Python host macOS **Screen Recording** and **Automation** permissions
before loading the user LaunchAgent. No deployment or LaunchAgent load is
performed by repository tests. The full runbook is
[`docs/deployment.md`](docs/deployment.md).

## Configuration

Keep secrets outside the repository, Compose file, plist, frontend, and image.

| Variable | Owner / meaning |
|---|---|
| `GOOGLE_API_KEY` | Cloud Gemini credential. |
| `JARVIS_API_TOKEN` | Frontend/user bearer for `/api/*`; unset means localhost-only for local development. |
| `JARVIS_DEVICE_TOKEN` | Separate Mac-agent bearer for `/api/device-agent/*`; never use it in the PWA. |
| `JARVIS_DEVICE_ID` | Configured single device identity; defaults to `local-mac`. |
| `JARVIS_ALLOWED_ORIGINS` | Comma-separated browser origins allowed by CORS. |
| `JARVIS_FRONTEND_API_BASE_URL` | Optional HTTP(S) API origin emitted by `/config.js`; empty/root path only, never `/api`. |
| `JARVIS_CLOUD_API_BASE_URL` | Mac agent's cloud origin; HTTPS is required except explicit loopback HTTP. |
| `JARVIS_CLOUD_DB_PATH` | Cloud queue SQLite path. Compose sets `/data/device/jarvis_cloud.sqlite3`. |
| `JARVIS_DEVICE_AGENT_STATE_PATH` | Mac agent's local SQLite state path. |
| `JARVIS_SHELL_CWD` | Existing absolute sandbox directory required by the Mac agent. |
| `JARVIS_BRAIN_DIR`, `JARVIS_SESSIONS_FILE` | Cloud ChromaDB and session persistence paths. |
| `JARVIS_LOG_LEVEL` | Cloud log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `JARVIS_GCAL_CREDENTIALS`, `JARVIS_GCAL_TOKEN` | Optional cloud Calendar OAuth file paths. |
| `JARVIS_AGENT_PROJECT_DIR`, `JARVIS_AGENT_PYTHON` | Launchd wrapper project and Python paths. |

Optional OpenBB provider credentials (`FMP_API_KEY`, `TIINGO_TOKEN`,
`FRED_API_KEY`) affect research coverage only; unavailable providers are
reported as unavailable rather than replaced with invented values.

## Device lifecycle and API

Frontend routes use `Authorization: Bearer <JARVIS_API_TOKEN>`:

- `GET /api/device/status`
- `GET /api/device/actions/{action_id}`
- `POST /api/device/actions/{action_id}/decision`
- `POST /api/chat`, `/api/research/run`, and the read-only research/memory routes

Agent routes use `Authorization: Bearer <JARVIS_DEVICE_TOKEN>` plus the
configured `X-Jarvis-Device-ID`:

- `POST /api/device-agent/poll` — heartbeat and bounded action/decision batch
- `POST /api/device-agent/actions/{action_id}/events` — approval/result events

The agent polls every two seconds. The cloud marks it offline after ten
seconds without a heartbeat and rejects new device work immediately with a
structured unavailable result. Delivered actions have a 30-second lease;
approval has a local monotonic 300-second TTL. The action ID and payload hash
are idempotency keys. The Mac records terminal results before reporting them,
keeps replay tombstones, and never executes a redelivered or substituted
payload. Approvals carry only an action ID; the agent executes its stored
payload after local reclassification and approval.

Screenshot bytes are bounded to 10 MiB, decoded and analyzed in memory, and
are not written to either SQLite database or logs. The cloud's vision callback
receives only that in-memory byte buffer.

The cloud is an approval relay and durable coordinator, not the local safety
authority. A cloud compromise can enqueue work and decide queued approvals,
so the cloud token, queue, and Gemini orchestration remain part of the trust
base. The Mac agent still owns shell classification and fails closed for
dangerous, unknown, sensitive, metacharacter, or tainted commands; it also
rejects mismatched device identities and replay/substitution attempts.

## Calendar and financial boundaries

Calendar stays cloud-side. Reads are cloud API calls; event creation keeps its
separate approval flow and is not a Mac device action. Financial research is
bounded, read-only, provenance-preserving, and explicit about missing,
unsupported, stale, and failed data. Portfolio state, trading execution,
recommendations, and portfolio APIs are not implemented.

## Tests

```bash
GOOGLE_API_KEY=test-only-key .venv/bin/python -m pytest -q
node --check app/static/app.js
/usr/bin/plutil -lint deploy/launchd/com.gassi.jarvis.mac-agent.plist
sh -n deploy/launchd/install.sh deploy/launchd/run-mac-agent.sh
```

Tests are credential-free and do not require a live Mac, provider network,
Docker daemon, or LaunchAgent. When Docker is unavailable, image validation is
limited to static Dockerfile/Compose/context checks; do not infer deployment
success.

## Disclaimer

This is a personal research project, not a production-hardened product. Keep
both bearer tokens long and private, prefer a private HTTPS tunnel, restrict
`JARVIS_SHELL_CWD` to a scratch directory, and read [`SECURITY.md`](SECURITY.md)
before exposing the cloud.

## License

[MIT](LICENSE) © 2026 Sajanth Chandrakumar

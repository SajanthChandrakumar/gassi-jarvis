# Gassi-Jarvis

Gassi-Jarvis is a self-hosted, voice-first assistant and deterministic
financial-research workspace. The installable vanilla PWA talks to FastAPI;
macOS control is performed by one outbound-only Mac agent. Shell commands and
calendar writes remain Human-in-the-Loop (HitL) gated.

![Jarvis research workspace](docs/jarvis-pwa.png)

## Capabilities

- Browser speech input and optional German Edge-TTS responses.
- Multi-turn sessions, persistent ChromaDB memory, and read-only Google Search
  grounding for ordinary assistant questions.
- macOS screen analysis, allowlisted app activation, and shell actions through
  the outbound agent's local classifier and HitL boundary.
- Google Calendar reads and separately approved event creation.
- Installable PWA research workspace with evidence, provenance, quality, and
  explicit missing-data states.

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

Key modules are [`app/main.py`](app/main.py) (cloud gateway),
[`app/agent.py`](app/agent.py) (Gemini orchestration),
[`app/memory.py`](app/memory.py) (sessions/ChromaDB),
[`app/models.py`](app/models.py) (API contracts),
[`app/security.py`](app/security.py) (local shell classifier),
[`app/vision.py`](app/vision.py) (local screenshot capture), and
[`app/logging_config.py`](app/logging_config.py) (logging).

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

Supported development target: Python 3.13 on macOS (Apple Silicon is the
primary target). Install Python with `brew install python@3.13`, then create a
compatible virtual environment. The runtime and test dependencies are kept
separate:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt   # tests only
```

Create an external `.env` or export the runtime values. Generate a long token
with `python -c "import secrets; print(secrets.token_urlsafe(32))"`; the
examples below contain placeholders, not real secrets.

```ini
GOOGLE_API_KEY=CHANGE_ME
JARVIS_API_TOKEN=CHANGE_ME
JARVIS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
JARVIS_LOG_LEVEL=INFO
```

Start the cloud on loopback. When exposing it through a tunnel, trust
`X-Forwarded-For` only from that tunnel and pass
`--forwarded-allow-ips` for the tunnel's known proxy addresses; the header is
spoofable if the listener is reachable directly, so it is a rate-limit key,
not authentication.

```bash
export GOOGLE_API_KEY=your_gemini_key
export JARVIS_API_TOKEN=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  --forwarded-allow-ips '*'
```

Open `http://localhost:8000` for the installable PWA or
`http://localhost:8000/docs` for the FastAPI schema. On a phone, install the
PWA from the browser's **Add to Home Screen/Install** action; the PWA asks for
the frontend token and keeps it for 12 hours. The microphone uses browser
speech recognition and the backend returns optional Edge-TTS audio.

For migration testing, `scripts/run_local_compat.py` starts cloud FastAPI and
the outbound agent together on loopback. It requires an existing absolute
`JARVIS_SHELL_CWD` and `JARVIS_DEVICE_TOKEN`; its cloud URL defaults to
`http://127.0.0.1:8000` and can be overridden with
`JARVIS_CLOUD_API_BASE_URL`. It does not install or load launchd.

## Reach it from a phone

Use a private tunnel where possible:

- **Tailscale:** install Tailscale on the Mac and phone, then expose the
  loopback cloud with `tailscale serve --bg --https=443
  http://127.0.0.1:8000`. Tailscale transport identity does not replace
  `JARVIS_API_TOKEN`.
- **ngrok:** for a short-lived tunnel, run `ngrok http 8000` and use its HTTPS
  URL. Set that URL in `JARVIS_ALLOWED_ORIGINS` and never expose the Mac
  listener directly.

The local two-process mode and the static-host API-origin contract are covered
in [`docs/deployment.md`](docs/deployment.md).

## Google Calendar (optional)

Calendar is cloud-side and event creation remains separately HitL-gated. In
the [Google Cloud Console](https://console.cloud.google.com/), enable the
Google Calendar API and create an OAuth client ID for a **Desktop app**. Save
the downloaded JSON as `gcal_credentials.json` (or set
`JARVIS_GCAL_CREDENTIALS`), then run the one-time browser login:

```bash
python -m app.gcal
```

The OAuth token is written to `gcal_token.json` (or `JARVIS_GCAL_TOKEN`), and
both files are git-ignored. The `calendar.events` scope permits event reads and
writes but not whole-calendar management. Without setup, Calendar requests
return a friendly unavailable state.

## API examples

All frontend API calls use `Authorization: Bearer <JARVIS_API_TOKEN>`:

```bash
curl -H "Authorization: Bearer $JARVIS_API_TOKEN" \
  http://localhost:8000/api/device/status

curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $JARVIS_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"walk-01","timestamp":"2026-08-24T20:00:00Z","payload":{"type":"text","content":"Analyse NVDA"}}'
```

Successful responses retain this shape (fields may be empty or omitted by the
route):

```json
{
  "status": "success",
  "jarvis_response": "...",
  "action_taken": "finance_research:research_asset",
  "research_payload": {"reports": [], "warnings": []},
  "device_action": null
}
```

The chat response keeps `research_payload` structured and authoritative when a
research workflow runs. A device response may contain `device_action` with an
`action_id`; the browser polls its cloud lifecycle and submits decisions to the
cloud. A decision contains `action_id`, `approved`, optional `reason`, and
cloud-recorded `decided_at`; it never resends executable payload text.

## Optional Homepage dashboard

For a separate phone landing page, [Homepage](https://gethomepage.dev) can
poll the LLM-free `/api/memories/recent` endpoint with the frontend token. It
does not replace the PWA or gain a Mac-agent path:

```yaml
widget:
  type: customapi
  url: https://<machine>.<tailnet>.ts.net/api/memories/recent
  method: GET
  refreshInterval: 600000
  headers:
    Authorization: Bearer ${JARVIS_API_TOKEN}
  display: dynamic-list
  mappings:
    - field: memories
      label: Zuletzt gemerkt
```

Use the Tailscale Serve HTTPS URL when Homepage is remote or accessed from a
phone. If Homepage is co-located on the same host as the cloud listener, its
URL may instead be `http://127.0.0.1:8000/api/memories/recent`.

Bookmark Homepage or install the Jarvis PWA for phone use. Read
[`app/security.py`](app/security.py), [SECURITY.md](SECURITY.md), and
[`architecture.md`](architecture.md) before exposing the service.

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

| Variable | Default / requirement |
|---|---|
| `GOOGLE_API_KEY` | Required by the cloud Gemini integration (tests use a dummy value). |
| `JARVIS_API_TOKEN` | Empty by default; remote frontend requests require it, while empty-token mode is localhost-only. |
| `JARVIS_DEVICE_TOKEN` | Required by the Mac agent and agent routes; never use it in the PWA. |
| `JARVIS_DEVICE_ID` | `local-mac` by default; this phase supports one identity. |
| `JARVIS_ALLOWED_ORIGINS` | Defaults to `http://localhost:8000,http://127.0.0.1:8000`; set comma-separated browser origins for a tunnel/static host. |
| `JARVIS_FRONTEND_API_BASE_URL` | Empty by default, meaning same-origin. Otherwise an HTTP(S) origin/root only; never `/api`. |
| `JARVIS_CLOUD_API_BASE_URL` | Required by the agent; remote HTTPS only, with loopback HTTP allowed for compatibility mode. |
| `JARVIS_CLOUD_DB_PATH` | `jarvis_cloud.sqlite3` by default; Compose overrides `/data/device/jarvis_cloud.sqlite3`. |
| `JARVIS_CLOUD_PORT` | Compose interpolation only; `8000` by default. |
| `JARVIS_CLOUD_ENV_FILE` | Compose interpolation only; `./deploy/cloud.env` by default. |
| `JARVIS_DEVICE_AGENT_STATE_PATH` | `jarvis_device_agent.sqlite3` by default (relative to the agent process). |
| `JARVIS_SHELL_CWD` | Required by the agent; must be an existing absolute sandbox directory. |
| `JARVIS_BRAIN_DIR` | `<repo>/jarvis_brain` by default; Compose sets `/data/chroma`. |
| `JARVIS_SESSIONS_FILE` | `<repo>/jarvis_sessions.json` by default (derived next to the brain dir); Compose sets `/data/sessions/jarvis_sessions.json`. |
| `JARVIS_LOG_LEVEL` | `INFO` by default (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `JARVIS_GCAL_CREDENTIALS`, `JARVIS_GCAL_TOKEN` | Project-root `gcal_credentials.json`/`gcal_token.json` by default; optional cloud Calendar OAuth paths. |
| `JARVIS_AGENT_ENV_FILE` | `$HOME/.config/jarvis/mac-agent.env` by default for the wrapper. |
| `JARVIS_AGENT_PROJECT_DIR`, `JARVIS_AGENT_PYTHON` | Required by the LaunchAgent wrapper; project and Python executable paths. |

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
structured unavailable result. That availability check is point-in-time: an
action that was already queued or leased can race with disconnect, remain in
the cloud queue, and be reclaimed/redelivered after its lease. Frontend polling
or its five-minute UI timeout does not cancel a cloud action. Delivered actions
have a 30-second lease; approval has a local monotonic 300-second TTL. The
action ID and payload hash are idempotency keys. The Mac records terminal
results before reporting them, keeps replay tombstones, and never executes a
redelivered or substituted payload. Approvals carry only an action ID; the
agent executes its stored payload after local reclassification and approval.

The frontend's `JARVIS_API_TOKEN` can submit a decision to the cloud;
`JARVIS_DEVICE_TOKEN` cannot approve anything. A decision contains
`action_id`, `approved`, optional `reason`, and `decided_at`; executable
payload text is never sent by the browser decision request. A compromised
device token can nevertheless forge authenticated agent events/results for
known action IDs, so it is a separate but still sensitive trust credential.

Screenshot bytes are bounded to 10 MiB, decoded and analyzed in memory, and
are not written to either SQLite database or logs. The cloud's vision callback
receives only that in-memory byte buffer.

The cloud is an approval relay and durable coordinator, not the local safety
authority. A cloud compromise can enqueue work and decide queued approvals,
so the cloud token, queue, and Gemini orchestration remain part of the trust
base. The Mac agent still owns shell classification and rejects mismatched
device identities and replay/substitution attempts, but a compromised
`JARVIS_DEVICE_TOKEN` can forge agent event/result reports; it cannot call the
frontend decision route.

## Calendar and financial boundaries

Calendar stays cloud-side. Reads are cloud API calls; event creation keeps its
separate approval flow and is not a Mac device action. Financial research is
bounded, read-only, provenance-preserving, and explicit about missing,
unsupported, stale, and failed data. Portfolio state, trading execution,
recommendations, and portfolio APIs are not implemented. Research routes are
cloud-only and never create device intents.

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

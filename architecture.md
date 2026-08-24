# Gassi-Jarvis system architecture

Gassi-Jarvis has three explicit trust zones. The browser is a client, the
cloud is the orchestration and durable-intent zone, and one configured Mac is
the local capability zone. The browser never connects to the Mac agent.

## Trust zones and data flow

```mermaid
flowchart LR
    UI["Frontend / PWA"] -->|"HTTPS, JARVIS_API_TOKEN"| API["Cloud FastAPI"]
    subgraph CLOUD["Trust zone 2: cloud"]
      API --> GEMINI["Gemini / TTS"]
      API --> MEM["ChromaDB memory + sessions"]
      API --> CAL["Google Calendar"]
      API --> RESEARCH["Deterministic read-only research"]
      API --> QUEUE["SQLite single-device queue"]
    end
    AGENT["Trust zone 3: outbound Mac agent"] -->|"POST poll/events, JARVIS_DEVICE_TOKEN"| API
    AGENT --> LOCAL["Local classifier, shell, AppleScript, screenshots"]
    UI -. "No frontend-to-agent path" .-> AGENT
```

### Frontend zone

`app/static/index.html` and `app/static/app.js` are a vanilla PWA. Runtime
`GET /config.js` supplies an API origin and is deliberately `no-store`. The
browser's single URL helper targets the cloud origin for chat, research,
memory, device status, action status, and decisions. It holds only
`JARVIS_API_TOKEN` in its 12-hour local-storage TTL; it never receives
`JARVIS_DEVICE_TOKEN` and has no agent URL.

### Cloud zone

`app/main.py`, `app/agent.py`, `app/memory.py`, `app/gcal.py`, and
`app/trading/` run in the cloud image. The cloud owns Gemini orchestration,
TTS, ChromaDB memory, disk-persistent sessions, Calendar, and deterministic
financial research. `app/device/cloud.py` stores one configured Mac's action
intent, decisions, heartbeat, leases, terminal result, and optional text
analysis. It does not import or execute `app/device/executor.py`,
`app/security.py`, `app/vision.py`, AppleScript, or launchd. The Docker build
context excludes those local implementations.

The cloud is not a financial source of truth. Deterministic research remains
under `app/trading/` with provenance, freshness, quality, and explicit missing
or unsupported values. ChromaDB, `jarvis_sessions.json`, and LLM history are
not financial state. Gemini may orchestrate or present the structured output,
but cannot calculate authoritative values, recommend trades, or execute
orders. Calendar remains cloud-side; event creation uses its existing separate
HitL flow. A future portfolio module would remain cloud-side, but portfolio
APIs and trading execution are not implemented.

### Deterministic research phase boundary

The cloud research path is a separate read-only branch and never creates a
device intent. Its implemented progression is:

```text
OpenBB provider responses
  -> canonical research data
  -> deterministic relevance findings
  -> structured asset reports
  -> historical/statistical research
  -> bounded natural-language orchestration
```

- **OpenBB/data access:** [`docs/openbb-research.md`](docs/openbb-research.md)
  keeps providers behind `app.trading.research.OpenBBResearchClient` and
  preserves provider/retrieval outcomes without Gemini calculations.
- **Canonical data (Phase 2):**
  [`docs/canonical-research-data.md`](docs/canonical-research-data.md)
  normalizes identity, provenance, `as_of`, retrieval time, quality,
  freshness, and explicit missing values.
- **Relevance (Phase 3):**
  [`docs/research-relevance-engine.md`](docs/research-relevance-engine.md)
  deterministically scores evidence-backed findings while keeping relevance
  separate from confidence.
- **Asset reports (Phase 4):**
  [`docs/asset-research-reports.md`](docs/asset-research-reports.md) composes
  canonical observations and findings without fetching, calculating, or
  recommending.
- **Historical research (Phase 5):**
  [`docs/historical-research.md`](docs/historical-research.md) builds explicit
  event/forward-return context with look-ahead warnings.
- **Statistical research (Phase 6):**
  [`docs/statistical-research.md`](docs/statistical-research.md) performs
  deterministic returns, alignment, correlation, beta, distribution, regime,
  and volatility analysis with sample/quality limitations.
- **Natural-language bridge (Phase 7):**
  [`docs/natural-language-quant-research.md`](docs/natural-language-quant-research.md)
  exposes only bounded high-level research tools and returns structured
  `research_payload`; it cannot choose arbitrary provider routes or chain
  calculations.

The broader financial state contract is
[`docs/trading-financial-contract.md`](docs/trading-financial-contract.md).
Portfolio, trading execution, recommendations, and portfolio APIs remain
future/out of scope.

### Mac capability zone

`app/device/agent.py` is an outbound-only client. It opens no listener and
uses the standard-library HTTP client. `app/device/executor.py` is the only
local adapter for the existing shell classifier/executor, allowlisted
AppleScript app activation, and screenshot capture. `app/device/state.py`
stores accepted action payloads, payload hashes, decisions, terminal results,
and replay tombstones in a local SQLite file.

The LaunchAgent wrapper validates a mode-0600 external env file and starts
`python -m app.device.agent` with `KeepAlive`/`RunAtLoad`. It is committed but
not installed or loaded by repository checks.

## Public contracts

The shared Pydantic contracts live in [`app/device/models.py`](app/device/models.py).

| Contract | Important fields | Owner / direction |
|---|---|---|
| `DeviceStatus` | `device_id`, `available`, `status`, `last_seen_at`, reason | Cloud → frontend |
| `DeviceAction` | `action_id`, `device_id`, typed `ActionPayload`, `requires_approval`, creation time | Cloud → agent |
| `ActionPayload` | `action_type` (`open_app`, `shell_command`, `take_screenshot`), raw payload, `tainted` | Cloud → agent; stored unchanged locally |
| `DeviceDecision` | `action_id`, `approved`, optional `reason`, `decided_at` | Frontend → cloud → agent |
| `DeviceResult` | action id, terminal status, output/action/error, finished time | Agent → cloud → frontend |
| `DeviceUnavailable` | `available: false`, reason, optional action id | Cloud → frontend |
| `DeviceLifecycle` | action + optional decision/result/unavailable/analysis + status | Cloud → frontend |

The cloud queue has no browser-facing arbitrary-action creation route. Chat
orchestration creates typed device intents internally; research endpoints are
an independent cloud-only branch and never create device intents. Frontend/user
routes use `JARVIS_API_TOKEN`:

```text
GET  /api/device/status
GET  /api/device/actions/{action_id}
POST /api/device/actions/{action_id}/decision
POST /api/chat
POST /api/research/run
GET  /api/memories/recent
GET  /api/research/providers
GET  /api/research/macro
```

Agent routes use `JARVIS_DEVICE_TOKEN` and `X-Jarvis-Device-ID`:

```text
POST /api/device-agent/poll
POST /api/device-agent/actions/{action_id}/events
```

The two bearer credentials are not interchangeable. The configured device ID
must match both the poll body and the optional identity header. This phase is
intentionally single-device; a second Mac requires a future queue/identity
model rather than merely another env file.

## Action lifecycle

```text
cloud online check
  ├─ offline at check → DeviceUnavailable; a concurrent queued/leased action may remain
  └─ online → queued
               ↓ agent POST poll (heartbeat + 30 s delivery lease)
             delivered
               ├─ safe local action → running → succeeded/failed/rejected
               └─ local classifier / taint / explicit flag requires HitL
                     ↓ approval_required event
               awaiting_approval (300 s TTL)
                     ├─ action-ID decision approved → approved → running → result
                     ├─ action-ID decision denied → denied → rejected result
                     └─ local/cloud TTL or boot change → expired result
```

The agent polls every two seconds. A successful poll is also the heartbeat;
the cloud reports offline after 10 seconds without one. New work observed as
offline is refused immediately rather than intentionally retained for surprise
execution. This is a point-in-time check, however: a request can pass the
check just as the agent disconnects, so an already queued or leased action can
remain durable, have its 30-second lease reclaimed, and be redelivered later.
Reconnect backoff is bounded at 30 seconds. Frontend lifecycle polling has a
bounded UI timeout but there is no cancel route; a frontend timeout does not
cancel the cloud action.

The cloud and local agent both enforce the five-minute approval window. The
agent's monotonic deadline is authoritative for execution and is tied to a
boot/process identity so a restart cannot extend an old approval. The cloud
expires its lifecycle view as well. A frontend decision contains
`action_id`, `approved`, optional `reason`, and cloud-recorded `decided_at`; the
browser never resends executable payload text. The agent can execute only the
payload it already stored for that ID.

Action IDs and payload hashes make insertion and redelivery idempotent. A
same-ID/different-payload substitution is rejected. The agent records a
terminal result and replay tombstone before reporting it; a report failure can
therefore be retried without running the action twice. Conflicting decisions
or terminal results are rejected.

## Screenshot handling

The Mac capture is bounded to 10 MiB. The agent keeps the bytes in memory and
sends a bounded base64 event. The cloud checks the encoded and decoded limits,
decodes the bytes only for the configured Gemini vision callback, and stores
only returned text analysis in the queue row. Screenshot bytes are never
written to local/cloud SQLite, session JSON, or structured logs. A failed or
oversized capture produces a typed result and no image persistence.

## Cloud as approval relay: explicit limitation

The cloud coordinates the user-facing decision and forwards an action-ID-only
decision. The frontend's `JARVIS_API_TOKEN` can submit the decision; the
agent's `JARVIS_DEVICE_TOKEN` cannot call the decision route. The Mac agent
remains authoritative for shell classification and reclassifies every shell
payload locally, but it authenticates the decision only as an authenticated
cloud decision; it cannot prove that a human clicked the frontend.
Consequently, a compromised cloud process or frontend token with cloud access
can approve a queued dangerous action or enqueue new work. A compromised
device token cannot approve through the frontend route, but can forge
authenticated agent approval-required/result events for known action IDs. The
cloud queue and both tokens are part of the HitL trust base. This design limits
payload substitution and accidental replay, but it does not make a compromised
cloud or agent credential an untrusted approval source.

## Runtime configuration and origin contract

Cloud values are normally supplied by an external env file. The important
variables are:

| Variable | Contract |
|---|---|
| `GOOGLE_API_KEY` | Cloud Gemini credential. |
| `GOOGLE_API_KEY` | Required by the cloud Gemini integration; tests use a dummy value. |
| `JARVIS_API_TOKEN` | Empty by default; remote frontend routes require it, while empty-token mode is localhost-only. |
| `JARVIS_DEVICE_TOKEN` | Required by agent poll/event routes; separate from the frontend token and cannot approve actions. |
| `JARVIS_DEVICE_ID` | `local-mac` by default; one configured identity in this phase. |
| `JARVIS_ALLOWED_ORIGINS` | Defaults to `http://localhost:8000,http://127.0.0.1:8000`; set comma-separated browser origins. |
| `JARVIS_FRONTEND_API_BASE_URL` | Empty by default, meaning same-origin. Otherwise HTTP(S) origin/root only; credentials, query, fragment, `/api`, and other paths fall back to same-origin. |
| `JARVIS_CLOUD_DB_PATH` | `jarvis_cloud.sqlite3` by default; Compose overrides `/data/device/jarvis_cloud.sqlite3`. |
| `JARVIS_CLOUD_PORT` | Compose interpolation only; `8000` by default. |
| `JARVIS_CLOUD_ENV_FILE` | Compose interpolation only; `./deploy/cloud.env` by default. |
| `JARVIS_BRAIN_DIR` | `<repo>/jarvis_brain` by default; Compose sets `/data/chroma`. |
| `JARVIS_SESSIONS_FILE` | `<repo>/jarvis_sessions.json` by default next to the brain dir; Compose sets `/data/sessions/jarvis_sessions.json`. |
| `JARVIS_CLOUD_API_BASE_URL` | Required by the agent; remote HTTPS only, with loopback HTTP allowed for compatibility mode. |
| `JARVIS_DEVICE_AGENT_STATE_PATH` | `jarvis_device_agent.sqlite3` by default, relative to the agent process. |
| `JARVIS_SHELL_CWD` | Required by the agent; must be an existing absolute local sandbox. |
| `JARVIS_LOG_LEVEL` | `INFO` by default (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `JARVIS_GCAL_CREDENTIALS` / `JARVIS_GCAL_TOKEN` | Project-root `gcal_credentials.json`/`gcal_token.json` by default; optional OAuth overrides. |
| `JARVIS_AGENT_ENV_FILE` | `$HOME/.config/jarvis/mac-agent.env` by default for the LaunchAgent wrapper. |
| `JARVIS_AGENT_PROJECT_DIR` / `JARVIS_AGENT_PYTHON` | Required by the LaunchAgent wrapper. |

`GET /config.js` returns `window.JARVIS_CONFIG = { apiBaseUrl: "..." }` with
`Cache-Control: no-store`. A static host must provide the same origin/root
contract before `app.js` loads; never configure a value ending in `/api`.
`sw.js` leaves `/config.js`, `/api/*`, and every non-GET request on the live
network.

## Operations, incident response, and recovery

Normal operations:

1. Keep the cloud bound to `127.0.0.1` and expose it through Tailscale Serve
   or another private HTTPS tunnel. Tailscale identity/app-capability headers
   are transport context, not either Jarvis bearer.
2. Keep cloud and Mac env files outside Git with mode `0600`. Rotate both
   tokens independently and update the corresponding process.
3. Check `GET /api/device/status` with the frontend token. `online` means a
   recent heartbeat, not proof that a particular action completed; poll
   `GET /api/device/actions/{action_id}` for lifecycle/result.
4. On macOS grant the agent's Python host **Screen Recording** for
   `screencapture` and **Automation** for AppleScript app activation. These
   permissions belong only in the Mac zone.

For a suspected incident, revoke/replace both bearer tokens, stop or unload
the Mac LaunchAgent, and inspect cloud/device logs and SQLite metadata without
copying screenshot bytes. Do not approve pending actions while investigating.
Because terminal results are recorded before reporting, restarting either
process is safe for completed actions: a later poll/event replay converges on
the stored result. Pending approvals from a new Mac boot/process expire
fail-closed. Back up the cloud volumes and the local agent SQLite file before
planned migration. Lost state cannot be reconstructed from the frontend;
preserve the state file and verify the running agent understands the action
models before allowing new work.

## Compatibility and migration risks

- The system remains one configured Mac. Adding a second device is not
  supported by the current queue identity model.
- `scripts/run_local_compat.py` preserves a loopback two-process migration
  mode, but it is not a production topology and does not install/load
  launchd.
- Existing `jarvis_sessions.json` can contain legacy pending shell commands.
  The cloud no longer executes a legacy raw command; ask for the action again
  so it becomes a typed device action. Calendar pending entries retain their
  separate cloud approval path.
- A separately hosted PWA must set both its CORS origin and the API origin
  contract. A stale cached `config.js`, an API path instead of an origin, or a
  missing frontend token produces an unavailable/unauthorized client rather
  than a direct Mac fallback.
- The cloud and agent must use compatible action models and device IDs. Keep
  the local state file during agent upgrades so hashes, decisions, terminal
  results, and tombstones survive; an old agent cannot safely be assumed to
  understand newer action types.

## Related implementation references

- [`app/device/models.py`](app/device/models.py) — typed contracts.
- [`app/device/cloud.py`](app/device/cloud.py) — queue, heartbeat, leases,
  expiry, idempotency, and in-memory screenshot analysis.
- [`app/device/agent.py`](app/device/agent.py) — outbound poll loop,
  reclassification, local TTL, and durable result reporting.
- [`app/device/routes.py`](app/device/routes.py) — separated auth surfaces.
- [`docs/deployment.md`](docs/deployment.md) — Compose, Tailscale, static
  host, launchd, and local compatibility runbook.
- [`SECURITY.md`](SECURITY.md) — security controls and residual risks.

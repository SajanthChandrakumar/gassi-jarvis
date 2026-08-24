# Security model

Gassi-Jarvis is a single-user, self-hosted assistant. The browser, cloud, and
Mac agent are separate trust zones, but the cloud and its bearer tokens remain
part of the approval trust base. This is a personal research project, not a
production-hardened product.

## Trust boundaries

### Frontend

The PWA is an untrusted client. It sends user requests only to the configured
FastAPI origin and authenticates with `JARVIS_API_TOKEN`. It has no route,
credential, or network path to the Mac agent. The token is held locally for a
12-hour TTL; a static-host `config.js` contains only a validated HTTP(S)
origin and is served without caching.

### Cloud

The cloud token-gates frontend routes and owns Gemini, memory, Calendar,
deterministic research, and a durable single-device queue. It must not import
or execute the local shell classifier, AppleScript, screenshot, or launchd
implementation. `JARVIS_DEVICE_TOKEN` is accepted only by the outbound-agent
poll/event routes. The cloud queue stores action intent and result metadata,
not screenshot bytes.

### Mac agent

The Mac process is the only local capability boundary. It makes outbound
HTTPS requests (loopback HTTP is allowed only for the explicit local
compatibility runner), validates the configured device identity, stores the
delivered payload before execution, reclassifies shell commands locally, and
starts no listener. Its local SQLite file preserves payload hashes,
decisions, terminal results, and replay tombstones.

There is no frontend-to-agent path. A user token cannot poll the agent, and a
device token cannot read frontend routes.

## Authentication and transport

- `JARVIS_API_TOKEN` is the frontend/user bearer. It protects chat, research,
  memory, device status, action status, and approval decisions. If unset,
  frontend routes retain the local-development behavior of accepting only
  localhost requests.
- `JARVIS_DEVICE_TOKEN` is a separate bearer for
  `POST /api/device-agent/poll` and
  `POST /api/device-agent/actions/{action_id}/events`. It is never embedded in
  the PWA, `config.js`, Compose YAML, plist, or committed examples.
- `JARVIS_DEVICE_ID` defaults to `local-mac` and identifies the one supported
  Mac. Poll body and `X-Jarvis-Device-ID` mismatches are rejected.
- Remote agent URLs must be HTTPS and cannot contain URL credentials. HTTP is
  accepted only for `localhost`, `127.0.0.1`, or `::1` in local compatibility
  mode.
- CORS (`JARVIS_ALLOWED_ORIGINS`) limits which browser origins can read
  responses; it is not authentication. Tailscale Serve identity/app-capability
  headers describe transport context; they do not replace either Jarvis
  bearer.
- Keep both env files outside the repository and mode `0600`. Rotate the two
  tokens independently after an incident.

## Device action controls

The cloud checks its heartbeat before creating an action. An agent is online
only when its last poll is within 10 seconds. New actions while offline return
`DeviceUnavailable` immediately and are not queued for surprise execution.
The outbound poll interval is two seconds, a delivered action lease is 30
seconds, reconnect backoff is bounded at 30 seconds, and approval expires
after 300 seconds.

The cloud and local agent use typed action IDs and payload hashes:

1. The cloud creates one `DeviceAction` for one configured device.
2. The agent receives it through its authenticated poll, validates the device
   ID, and stores the exact payload/hash before it can execute.
3. The Mac classifier independently evaluates every shell command. Dangerous,
   unknown, sensitive-path, metacharacter, or tainted commands require HitL;
   classifier failure fails closed. Explicit `requires_approval` also cannot
   lower the local requirement.
4. The cloud receives `approval_required`, and the frontend submits a
   `DeviceDecision` containing only `action_id`, approval state, and an
   optional reason.
5. An approved action executes the locally stored payload with the existing
   executor. A denial produces a rejected result. A timeout or boot identity
   change produces an expired result.
6. The agent records the terminal result and replay tombstone before sending
   the result event. Same-ID substitutions, conflicting decisions, and
   conflicting terminal replays are rejected.

The local monotonic approval deadline is tied to a boot/process identity. A
restart therefore invalidates an old monotonic epoch instead of extending a
pending approval. The cloud also expires its lifecycle view at the same TTL.

## Shell and HitL threat levels

The existing `app/security.py` classifier remains the local authority:

| Level | Examples | Default |
|---|---|---|
| 0 | `echo`, `date`, `whoami` | Execute locally. |
| 1 | `ls`, `pwd`, safe `cat`/`find` | Execute unless sensitive or tainted. |
| 2 | `rm`, `sudo`, `curl`, unknown commands, sensitive reads | Require approval. |

Pipes, redirects, command separators, shell substitutions, backticks, and
newlines force level 2. Sensitive paths and dangerous `find` flags are
inspected. App names pass a strict allowlist before AppleScript. The existing
executor uses a configurable `JARVIS_SHELL_CWD`; point it at a scratch
directory rather than a personal home directory where practical.

Screenshots, web-search output, calendar titles, and recalled memories are
untrusted content. A reply built from them is marked tainted; a shell command
proposed immediately afterward is forced through local HitL. This is a
bounded indirect-injection mitigation, not a proof against delayed attacks.

## Cloud as approval relay: residual trust

The Mac agent authenticates an approval as a cloud decision, not as a
cryptographically verifiable human gesture. Therefore a compromised cloud,
cloud database, `JARVIS_API_TOKEN` with cloud access, or `JARVIS_DEVICE_TOKEN`
can enqueue actions and approve a pending dangerous action by ID. Local
reclassification still prevents a dangerous command from executing without an
approval state, and payload hashes prevent replacing an already stored payload
under the same ID, but the agent cannot distinguish a malicious cloud approval
from a human-originated one. The cloud, queue, and both credentials must be
protected as part of HitL.

## Screenshot and data handling

Screenshot payloads are capped at 10 MiB decoded (with a bounded base64 input)
at both agent and cloud boundaries. Bytes exist only in the capture/event/
vision call path. They are not stored in agent SQLite, cloud SQLite,
`jarvis_sessions.json`, ChromaDB, or application logs. Only optional returned
text analysis is retained in the cloud lifecycle. Do not add request-body or
exception logging around screenshot events.

Cloud financial research is deterministic and read-only. Provider provenance,
retrieval time, freshness, quality, unavailable sections, and explicit missing
values remain visible. Gemini is not a calculation engine, recommender, or
trading executor. ChromaDB and sessions are assistant state, never the
financial source of truth. Portfolio APIs and portfolio/trading execution are
not implemented.

## Deployment and permissions

- Bind Compose to `127.0.0.1`; expose it through a private HTTPS tunnel.
- Keep cloud and agent env files external and mode `0600`; do not put tokens in
  frontend assets, Compose, plist, or the image.
- On macOS grant only the agent's Python host **Screen Recording** permission
  for `screencapture` and **Automation** permission for AppleScript app
  activation. The cloud receives neither permission.
- The cloud image runs as unprivileged `jarvis` and its build context excludes
  Mac-only executor/security/vision/launchd material. This is a packaging
  boundary, not a substitute for runtime authentication.
- The committed LaunchAgent installer is opt-in and does not load launchd.
  Review `deploy/launchd/mac-agent.env`, plist, and wrapper before loading.

## Incident response and recovery

1. If a token, cloud process, or Mac host is suspected, stop/unload the Mac
   agent and rotate both tokens. Do not approve pending actions during
   investigation.
2. Inspect action IDs, statuses, decisions, and result metadata. Avoid copying
   screenshot data; the implementation should not have persisted it.
3. Restarting the cloud or agent does not rerun terminal actions: terminal
   state is recorded before report delivery and replayed idempotently.
4. A pending approval from a new Mac boot/process expires fail-closed. Preserve
   the agent SQLite file during upgrades so hashes and tombstones survive.
5. Back up cloud volumes and the local agent state before migration. A deleted
   queue/state file cannot be reconstructed from the PWA; ask the user to
   reissue any action whose lifecycle is unknown.

## Known limitations

- `app/security.py` still ultimately invokes shell execution through the
  existing `shell=True` boundary. The classifier is the defense between model
  output and the shell; a missed parser case would be serious.
- The cloud approval relay is a trust base as described above; local HitL does
  not provide independent human attestation.
- The indirect-injection guard covers the immediately following shell turn,
  not a delayed attack after unrelated conversation.
- The system supports one configured device. Multi-device routing, device
  enrollment/rotation, and hardware-backed approval are future work.
- A cloud or agent outage returns explicit unavailable/expired states, but no
  automatic action replay after a human-visible timeout is attempted.
- Provider credentials are optional and research coverage can be partial,
  stale, unsupported, or failed. No fallback value is fabricated.

Report vulnerabilities without including live credentials or personal data.

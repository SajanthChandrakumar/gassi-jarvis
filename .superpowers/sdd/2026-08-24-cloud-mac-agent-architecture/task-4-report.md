# Task 4 report: configure the PWA API origin

## Outcome

Implemented the configurable cloud API origin while preserving the vanilla PWA
and existing research, voice, TTS, token, and service-worker behavior.

- Added unauthenticated `GET /config.js`, generated at request time from
  `JARVIS_FRONTEND_API_BASE_URL`. An empty value means same-origin requests.
  The response is explicitly `Cache-Control: no-store`.
- Loaded `/config.js` before `/static/app.js` in the PWA shell.
- Added one `apiUrl()` helper and routed every frontend API request through it:
  chat, research workflows, provider status, macro context, device status,
  action status, and approval decisions.
- Added a compact Mac-agent status block and structured action lifecycle block.
  Device actions are shown from `ChatResponse.device_action`; approvals use the
  authenticated cloud decision endpoint and pending actions poll the cloud
  action endpoint until a terminal state. The frontend never contacts the Mac
  agent directly.
- Kept `/api/*` network-only in the service worker and intentionally kept
  `/config.js` out of the cache shell.

## TDD and verification

The new UI/config tests were written before implementation. The first valid
RED run was:

```text
8 failed, 14 passed
```

The failures covered missing script ordering/API helper/device contracts and a
404 for `/config.js`.

Focused GREEN and syntax check:

```text
node --check app/static/app.js
22 passed, 1 warning
```

Full credential-free suite:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
269 passed, 1 warning
```

`git diff --check` also passed. The warning is the existing Starlette/httpx
deprecation warning from the installed test-client compatibility layer.

## Files changed

- `app/main.py`
- `app/static/index.html`
- `app/static/app.js`
- `app/static/styles.css`
- `tests/test_command_center_ui.py`
- `tests/test_frontend_config.py`

## Commit and concerns

Commit message: `feat(ui): support configurable cloud API origin`

The commit SHA is reported in the task handoff. No deployment, docs outside
this report, trading code, agent lifecycle semantics, or direct Mac-agent
access was changed. The existing Starlette/httpx warning remains the only test
warning.

## Read-only review of `bd99872..4245125`

Review scope: source and diff inspection only, with `git diff --check` as the
only verification command. No source changes, commits, broad test runs, or
deployment actions were performed.

### Findings

1. **[P1] Runtime API base URL is not validated before bearer-bearing requests.**
   `app/main.py:358-359` emits any non-empty environment string, while
   `app/static/app.js:2,7` only strips trailing slashes and concatenates it with
   an endpoint. Values such as `//other-host`, a non-HTTP scheme, or a URL with
   query/fragment text can redirect requests (and `Authorization`) to an
   unintended origin or produce malformed URLs. The helper also does not
   normalize the configured value as an origin. Validate with `URL`, allow only
   the intended HTTP(S) form, reject credentials/query/fragment, and join paths
   structurally. Add tests for empty, one trailing slash, malformed, and
   cross-origin values.

2. **[P1] Device polling can continue indefinitely in duplicate chains and can
   resurrect stale approval controls.** `app/static/app.js:96-102` starts a new
   `pollDeviceAction` chain after every decision without cancelling or
   generation-checking the chain started by `addAnswer`. Two in-flight GETs can
   render out of order: an older `awaiting_approval` response can add Approve /
   Decline buttons after a newer approved/expired response. The cloud correctly
   rejects conflicting decisions, but the UI can present an approval that is no
   longer valid and multiple chains multiply polling traffic. Keep one
   per-action controller/generation, ignore stale responses, and cancel it when
   a decision is submitted or the action reaches a terminal state.

3. **[P2] Polling failure/termination leaves the card falsely pending.** At
   `app/static/app.js:100-102`, a successful non-terminal response schedules
   fixed two-second polls for at most 151 attempts, while network/HTTP failures
   are retried only three times and then silently stop. The card remains at its
   last `queued`/`approved` status with no unavailable/error state, so the user
   cannot tell whether the action completed or polling died. Render an explicit
   status after retry exhaustion and test both transient recovery and terminal
   timeout behavior.

4. **[P2] New device endpoints do not participate in the existing token-recovery
   flow.** `app/static/app.js:64-66,96-102` sends a stored token when present, but
   `loadDeviceStatus`, `submitDeviceDecision`, and `pollDeviceAction` treat 401 as
   generic unavailable/decision failure/retry. They never clear an expired token
   and prompt or otherwise surface authorization as `send` and
   `runResearchWorkflow` do (`app/static/app.js:110-111`). A remote PWA can show
   a device action yet be unable to approve it after token expiry, and status
   polling can waste retries. Route these calls through the same explicit 401
   handling and stop polling on authorization failure.

### Verified without findings

- `/config.js` is loaded before deferred `app.js` in
  `app/static/index.html:17-18`; the response is `no-store` at
  `app/main.py:355-364`.
- All application API fetches in `app/static/app.js` use `apiUrl`; action IDs
  are path-encoded and new lifecycle/result values are inserted with
  `textContent`/`dataset`, so the added device UI does not introduce an
  obvious DOM-XSS sink.
- `app/static/sw.js:40-50` leaves `/api/*`, `/config.js`, and all non-GET
  requests on the network; `/config.js` is not in `SHELL`.
- The diff is scoped to runtime config, one compact device-status block,
  lifecycle rendering, and contract tests; no unrelated Command Center
  redesign or financial/research backend changes were found.

## Review-fix implementation

The four review findings were reproduced with new failing contracts before the
frontend fixes. The focused RED run showed 14 failures, including every
invalid-origin case and the missing URL/auth/poll-controller contracts.

Implemented fixes:

1. `GET /config.js` now accepts only explicit HTTP(S) URLs, rejects
   protocol-relative URLs, bad schemes, credentials, query strings, fragments,
   malformed ports, and whitespace/control characters, and normalizes trailing
   slashes. Invalid values log a generic warning without echoing the value and
   fall back to same-origin. Browser/static-host config repeats the same
   defense, and `apiUrl()` joins endpoint paths with `URL`.
2. Device polling now has one map-owned controller and generation per action.
   Starting a replacement, submitting a decision, clearing/new-session, and
   terminal/unavailable/auth states cancel prior timers/controllers. Responses
   are ignored unless their action, article, and generation are still current.
3. Polling retries transient failures up to a bounded limit, resets retries on
   recovery, and reports explicit unavailable or timed-out status after retry
   or duration exhaustion.
4. `apiFetch()` centralizes bearer headers and 401 recovery. A shared promise
   prevents concurrent prompts; device status, decision, and action polling
   stop with explicit authorization state when recovery is unavailable.

Review-fix verification:

```text
node --check app/static/app.js
30 focused tests passed, 1 warning
```

Full suite:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
277 passed, 1 warning
```

`git diff --check` passed. The fix is limited to
frontend runtime/config behavior and its focused tests; no deployment, docs
outside this report, trading code, or device lifecycle semantics were changed.

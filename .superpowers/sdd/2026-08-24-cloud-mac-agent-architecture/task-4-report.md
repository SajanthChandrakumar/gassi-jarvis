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

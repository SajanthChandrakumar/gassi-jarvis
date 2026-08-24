# Task 2 report: add the outbound Mac agent

## Outcome

Implemented the standalone outbound Mac agent and its durable local state
store. `app/device/agent.py` is a client-only process: it has no listener and
connects to the cloud only through authenticated outbound requests. It uses
stdlib `urllib` for HTTP and lazily imports the Mac executor, keeping the
cloud-safe device contracts free of `app.security`, `app.vision`, and other
Mac-only imports.

## Safety and lifecycle behavior

- Cloud URLs must use HTTPS; HTTP is accepted only for `localhost`,
  `127.0.0.1`, or `::1` compatibility mode.
- Every poll and result event uses a separate `Authorization: Bearer`
  device token and includes the configured device identity.
- Polling defaults to two seconds. Connection failures use bounded exponential
  reconnect delays capped at 30 seconds.
- Accepted payloads are persisted in SQLite with a SHA-256 payload hash.
  Same-id substitutions raise an error, and delivery leases last 30 seconds.
- Shell commands are classified again on the Mac. Dangerous, unknown,
  metacharacter, sensitive-path, or tainted-context commands require approval
  even when the cloud directive does not request it.
- Approval decisions contain only an action ID and boolean decision. The agent
  executes the locally stored payload, never data supplied in the approval.
- Approval expiry uses the local monotonic clock and is 300 seconds. Expired
  and denied approvals cannot execute.
- Terminal results and replay tombstones are committed before reporting, so a
  redelivery returns the stored result without executing again.
- Screenshots are size bounded, relayed in memory when reported, and omitted
  from SQLite and agent logs.
- `main()` reads cloud URL, device token, device identity, state path, and the
  required absolute existing `JARVIS_SHELL_CWD` from environment/CLI. It does
  not start any inbound endpoint.

## TDD and verification evidence

The focused state-machine tests were red before the implementation because
`app.device.agent` did not exist:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_device_agent.py
6 failed, 2 passed
ModuleNotFoundError: No module named 'app.device.agent'
```

After implementation and the state-store hardening:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_device_agent.py
8 passed

GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
250 passed, 1 warning
```

The one warning is the pre-existing Starlette deprecation warning from the
installed `httpx` compatibility layer. Python bytecode compilation also
passed for the new agent and state modules.

## Scope and handoff concerns

- This task changed only `app/device/agent.py`, `app/device/state.py`, its
  focused tests, and this report. The untracked architecture plan was left
  untouched.
- The focused polling contract currently uses a body-free authenticated GET
  to `/api/device-agent/poll`, matching the pre-written Task 2 test and
  localhost compatibility intent. If the cloud route is implemented as the
  plan's POST-only endpoint, Task 3 should either accept this GET heartbeat or
  make the method an explicit shared contract before integration.
- Cloud-side event durability, offline status, frontend routing, launchd
  installation, Docker packaging, and deployment remain for later tasks.
- No launch agent was loaded, no process was deployed, and no secrets were
  added.

# Task 2 read-only review

Scope: `87ee2120339ca9a2484e5e0166e884d8ddc9a5eb` through
`a94507f5714b2f908f87e7cb11c9f107ae5d9634`.

## Verdicts

- **Spec verdict: FAIL.** The implementation is outbound-only and has the
  requested URL/auth/backoff/lease/hash primitives, but the planned poll
  contract and approval lifecycle are not complete.
- **Quality verdict: NEEDS CHANGES.** The focused suite passes (`8 passed`),
  but it does not cover the failing integration paths below and one test
  explicitly locks in the GET contract mismatch.

## Findings

1. **[P1] Poll method does not implement the public contract.**
   `app/device/agent.py:436-444` calls `self._request("GET", self.poll_url)`.
   The architecture plan's public contract is `POST
   /api/device-agent/poll`; a POST-only Task 3 route will return 405 and the
   agent will never receive work. `tests/test_device_agent.py:160-165`
   asserts GET rather than detecting this mismatch.

2. **[P1] Approval decisions cannot reach the running outbound agent.**
   `app/device/agent.py:421-434` extracts only `actions`/`action` values, and
   `app/device/agent.py:451-454` sends only those values to
   `receive_action`. Although `receive_decision` exists at
   `app/device/agent.py:366-415`, no poll response is parsed into it and no
   other listener or outbound decision-poll exists. An action that enters
   `awaiting_approval` at `app/device/agent.py:347-362` therefore has no
   deployed path to receive the action-ID-only approval and execute its
   stored payload. The Task 3 poll response contract must carry decisions (or
   provide an equivalent authenticated outbound mechanism), and the agent
   must process them.

3. **[P1] Approval expiry is not enforced when no decision arrives.**
   `app/device/agent.py:335-336` returns `awaiting_approval` immediately on
   every redelivery. The 300-second monotonic deadline is checked only inside
   `receive_decision` at `app/device/agent.py:393-402`. Once the deadline
   passes, a redelivered action remains awaiting forever and no terminal
   `expired` result is recorded or reported. Expiry must be checked before
   the awaiting-status early return (and must be exercised by a redelivery
   test).

4. **[P2] Approval-required reporting is lossy.**
   `_report_event` catches and drops all reporting errors at
   `app/device/agent.py:192-210`. The only approval notification is emitted
   at `app/device/agent.py:355-361`; subsequent deliveries hit the early
   return at `app/device/agent.py:335-336` and do not retry it. A transient
   cloud outage can therefore leave the cloud unaware that approval is
   required, with no durable event/outbox to recover it. Terminal results do
   get replay-reported, but approval-required events do not.

5. **[P2] Persisted monotonic deadlines are unsafe across a reboot.**
   The schema persists `approval_deadline` as a bare float at
   `app/device/state.py:64-74`; the agent writes `time.monotonic() + 300` at
   `app/device/agent.py:347-353` and later compares a fresh monotonic reading
   at `app/device/agent.py:393-394`. If the OS monotonic origin resets across
   a reboot while the SQLite file survives, an old approval can appear
   unexpired and execute well beyond 300 seconds. Persist a boot/session
   identity with the deadline, or invalidate pending approvals when the
   monotonic epoch is not the same.

## Verified strengths

- `app/device/agent.py:41-64` enforces HTTPS except explicit loopback HTTP;
  `app/device/agent.py:128-133` uses a dedicated bearer token and device
  identity header.
- `app/device/state.py:110-152` rejects same-ID payload substitutions and
  `app/device/state.py:244-283` records terminal results/tombstones before
  `_report_result` at `app/device/agent.py:224-230`.
- `app/device/state.py:187-205` implements the 30-second delivery lease, and
  `app/device/agent.py:445-449` bounds reconnect backoff at 30 seconds.
- `app/device/agent.py:177-190` reclassifies shell commands locally and
  fails closed on classifier errors. `main()` at
  `app/device/agent.py:481-517` starts no listener.

---

# Implementer fix report

## Review findings addressed

1. Polling now sends `POST /api/device-agent/poll` with a minimal
   `{"device_id": "..."}` heartbeat body and the separate device bearer.
2. Poll responses use explicit `actions` and `decisions` arrays. Actions are
   persisted and classified first; decisions contain only `action_id`,
   `approved`, and optional reason and are passed to `receive_decision`.
3. Awaiting approvals are checked for expiry on action redelivery and on
   every poll, even when the cloud returns no action or decision. Expired
   requests become terminal `expired` results and are reported.
4. Awaiting approval state is a durable retry outbox. Every poll retries its
   idempotent approval-required event until the cloud accepts it; transient
   report errors do not lose the event.
5. Approval deadlines now persist a boot identity. Linux uses
   `/proc/sys/kernel/random/boot_id`, macOS uses `sysctl -n kern.boottime`, and
   an unpredictable process identity is used as a fail-closed fallback. A
   pending approval from another boot/session expires without execution.
6. Existing SQLite state files are migrated with the new boot-identity column
   without deleting or rewriting existing payloads.

## TDD RED/GREEN evidence

The review regression tests were added before the fix implementation and
initially failed as expected:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_device_agent.py
6 failed, 7 passed
```

The failures covered the old GET poll method, unprocessed decisions, missing
expiry on redelivery/poll, lossy approval reporting, and the missing injected
boot identity.

After the fix:

```text
GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q tests/test_device_agent.py tests/test_device_boundary.py
25 passed

GOOGLE_API_KEY=test-only-key /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
255 passed, 1 warning
```

The warning remains the pre-existing Starlette deprecation warning for the
installed `httpx` compatibility layer. No Task 3 routes, `main.py`, frontend,
deployment, or trading files were changed.

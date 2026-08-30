# Task 6 report: harden split-service security boundaries

## Outcome

Added executable regression coverage for the remaining cloud/Mac trust-zone
acceptance bullets. The tests use deterministic clocks, fake executors,
in-memory ASGI transport, and subprocess import checks; they do not use the
network, provider credentials, live macOS control, or screenshot persistence.

One implementation defect was exposed and fixed: `ActionPayload.payload` had a
default empty string, so a malformed agent directive could validate locally.
It now rejects empty and whitespace-only strings while preserving valid payload
bytes exactly for hashing and execution. Unknown action types were already
rejected by the typed `ActionType` contract and cloud queue.

## Coverage matrix

| Acceptance boundary | Executable coverage |
| --- | --- |
| Cloud research and ordinary chat remain available while the Mac agent is disabled/offline | `test_cloud_chat_and_research_remain_available_when_agent_is_offline`; existing `tests/test_research_run_endpoint.py` |
| Bad device token, frontend token on agent routes, and device token on frontend routes are rejected | `test_device_routes_keep_frontend_and_agent_credentials_separate` |
| Mismatched device identity is rejected in both header and poll body | `test_device_routes_reject_mismatched_identity_and_bad_poll_payload`; existing gateway identity tests |
| Unknown event/action kinds and malformed payloads are rejected before execution | `test_routes_reject_unknown_event_kinds_and_malformed_payloads`; `test_local_agent_rejects_unknown_action_kind_and_missing_payload` |
| Dangerous, unknown, sensitive-path, metacharacter, and tainted shell directives require local HITL | `test_local_agent_requires_hitl_for_dangerous_unknown_sensitive_metachar_and_tainted_shell`; existing `tests/test_security.py` classification matrix |
| Approval TTL is exactly 300 seconds and expiry cannot execute | `test_local_approval_expires_at_exactly_300_seconds`; existing cloud expiry coverage |
| Denied, substituted, replayed, and completed actions cannot execute twice | `test_denied_and_substituted_actions_cannot_execute_and_completed_replay_is_safe`; existing state hash/tombstone and cloud terminal lifecycle tests |
| Screenshot bytes are bounded and excluded from local/cloud SQLite and logs | `test_screenshot_bytes_are_bounded_and_not_stored_by_local_agent`; `test_cloud_screenshot_event_rejects_oversized_encoded_payload`; existing cloud screenshot idempotency test |
| Same-origin default and configured cross-origin frontend requests join safely | `test_frontend_api_url_joins_same_origin_and_configured_cross_origin_at_runtime`; existing `/config.js` and Node normalization tests |
| Cloud main imports/starts with Mac-only modules blocked | `test_cloud_main_import_and_start_do_not_require_mac_modules`; existing contract import boundary |
| Research endpoints preserve offline/provider status and deterministic provenance | `test_research_endpoints_use_real_dispatch_serialization_and_preserve_provenance`; existing trading canonical/provenance suite |
| Localhost two-process behavior works through authenticated poll/event transport | `test_localhost_two_process_transport_executes_one_queued_action` |

## TDD evidence

The new focused suite initially showed the expected RED failure:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/pytest -q \
  tests/test_task6_security.py
1 failed, 13 passed
```

The failure was the missing-payload contract accepting a directive without a
payload. After the minimal model fix:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/pytest -q \
  tests/test_task6_security.py
14 passed, 1 warning
```

Focused cloud/device/frontend/research regression set:

```text
71 passed, 1 warning
```

Full credential-free suite:

```text
307 passed, 1 warning in 6.26s
```

Additional checks passed:

```text
node --check app/static/app.js
git diff --check
```

The warning is the pre-existing Starlette/httpx compatibility deprecation.

## Fix round 1

The reviewer follow-up added RED proofs for blank payloads, real research
dispatch/serialization, the 299.999/300.000-second TTL boundary, executor
history for denied/substituted/completed actions, authoritative shell
classification for tainted approval, positive frontend status auth, cloud
screenshot log secrecy, and interpreter portability. The first run of those
new proofs was:

```text
3 failed, 15 passed, 1 warning
```

The minimal fixes were:

- validate payload content with a Pydantic validator but never strip or rewrite
  the stored/hash input;
- always run the local shell classifier before applying explicit/tainted HITL
  requirements;
- use `sys.executable` for the blocked-Mac import/start subprocess;
- route the research endpoint test through real `JarvisResearchTools`,
  `ResearchOrchestrator`, canonical serialization, and deterministic offline
  fixture data, while checking concrete provider configuration states.

Fix-round verification:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/pytest -q \
  tests/test_task6_security.py
18 passed, 1 warning

GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/pytest -q
311 passed, 1 warning in 5.98s

node --check app/static/app.js
git diff --check
```

The localhost proof remains an in-process FastAPI `TestClient` transport, not
a real TCP two-process test; it still exercises authenticated poll/event route
behavior with separate cloud and agent SQLite state. No Obsidian note was
changed during this fix round.

## Gaps and concerns

- Docker is not installed in this environment, so no Docker build/run smoke
  test was attempted; deployment metadata remains covered by Task 5.
- The localhost integration uses FastAPI `TestClient` as a deterministic
  in-process transport rather than binding a real TCP listener. It exercises
  the same authenticated POST poll and event routes and both independent
  gateway/agent SQLite stores.
- No live provider, internet, macOS screen, AppleScript, shell, launchd,
  deployment, merge, push, or launchd load side effect was performed.
- The pre-existing Starlette/httpx deprecation warning remains.

The pre-existing untracked architecture plan was left untouched.

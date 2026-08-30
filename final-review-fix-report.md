# Final review fix report

This release-blocker pass was implemented with focused RED/GREEN regression
tests. The existing credential-free suite remains offline and uses only a
non-secret test `GOOGLE_API_KEY`.

## Fixes

1. Cloud `approval_required` transitions set a 300-second deadline only on the
   first queued/delivered transition. Duplicate events retain the original
   deadline and cannot revert approved or terminal actions.
2. Cloud decisions and result events use SQLite conditional updates under the
   gateway lock, verify affected rows, elect one approve/deny winner, preserve
   the first terminal result, and return exact idempotent replays.
3. The Mac agent uses a urllib opener that rejects every redirect. A 3xx is a
   transport failure; bearer authorization is never sent to a redirected host
   or an HTTPS-to-HTTP target.
4. Unset frontend-token mode remains loopback-compatible without credentials,
   but rejects any supplied bearer. Frontend routes never accept the device
   bearer, and equal non-empty frontend/device tokens fail app configuration.
5. Persisted approved/running local actions are converted at agent startup to
   a stored failed/unknown terminal result requiring user reissue. Redelivery
   reports the stored result and never executes the ambiguous action again.
6. `MacAgent` and `MacExecutor` require `JARVIS_SHELL_CWD` to be an absolute,
   existing directory when a real executor is constructed. Injected test
   executors remain path-independent; device execution has no home fallback.

## Verification

RED: the new release tests initially failed on deadline reset, redirect
handling, token fallback, equal-token startup, crash recovery, and CWD
validation.

GREEN:

```text
GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q \
  tests/test_final_release_security.py
12 passed, 1 warning

GOOGLE_API_KEY=test-only-key PYTHONPATH=. \
  /Users/Sajanth/Desktop/Draft/gassi-jarvis/.venv/bin/python -m pytest -q
323 passed, 1 warning
```

The warning is the pre-existing Starlette/httpx compatibility deprecation.

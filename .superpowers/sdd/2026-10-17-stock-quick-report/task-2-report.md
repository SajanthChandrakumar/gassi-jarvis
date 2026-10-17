# Task 2 — report presentation

## Implementation

- Reworked the existing asset-report renderer into a compact header and responsive chart/evidence plus supporting-data layout. Snapshot metrics (including previous close and 52-week bounds), financial sections, earnings, filings and news remain available; financial, valuation and earnings details use native disclosures.
- Added a timestamp-scaled closing-price chart with price/date axes, pointer and keyboard selection with a shared live readout, selected/original-count metadata, explicit downsampling, and an expandable exact-value table. Flat series remain finite; fewer than two valid points show an insufficiency notice without a line.
- Rendered the first three supplied findings followed by an expandable remainder in backend order, with observed/comparison values, periods, as-of dates and provenance. Risks resolve to those findings; quality warnings, missing fields, stale states and provider failures remain visible.
- Limited news and filing rows to the specified counts and made links absolute HTTP(S)-only with `noopener noreferrer`. Added matched EPS comparison from the same historical observation only, including true zero and negative values, dates, currency state, separate series labels and an exact-data disclosure.
- Removed the renderer’s implicit USD fallback. Missing/invalid currency now leaves a numeric value with an explicit unknown-currency label; ratio and percentage formatting remain distinct. No provider, API, calculation, recommendation, runtime package or production test hook was added.

## Files

- `app/static/app.js`
- `app/static/styles.css`
- `tests/test_command_center_ui.py`
- `tests/test_stock_report_renderer.py` — Node built-ins exercise the actual renderer with a small DOM shim.

## TDD evidence

RED was run against the original `HEAD` renderer using the same behavior harness. It failed because the original report rendered a zero with missing currency as `$0.00` instead of an unknown-currency value:

```text
TASK_TMP=$(mktemp -d /private/tmp/gassi-stock-report.XXXXXX); mkdir -p "$TASK_TMP/numba" "$TASK_TMP/brain"; NUMBA_CACHE_DIR="$TASK_TMP/numba" JARVIS_BRAIN_DIR="$TASK_TMP/brain" JARVIS_SESSIONS_FILE="$TASK_TMP/sessions.json" JARVIS_CLOUD_DB_PATH="$TASK_TMP/cloud.sqlite" JARVIS_INBOX_FILE="$TASK_TMP/inbox.md" GOOGLE_API_KEY=test-only-key .venv/bin/python -c 'import subprocess; from tests.test_stock_report_renderer import _run_renderer_check; old=subprocess.run(["git","show","HEAD:app/static/app.js"],capture_output=True,text=True,check=True).stdout
try: _run_renderer_check(old)
except AssertionError as error: print("EXPECTED RED against HEAD:\n" + str(error)); raise SystemExit(0)
raise SystemExit("Expected original renderer behavior check to fail")'
```

Relevant RED output:

```text
EXPECTED RED against HEAD:
AssertionError [ERR_ASSERTION]: The input did not match the regular expression /Observed price0 \(currency unknown\)/.
Input: 'Market snapshotTSTTest assetObserved price$0.00As of 01 Feb 2026, 01:00...'
```

GREEN focused verification:

```text
node --check app/static/app.js && TASK_TMP=$(mktemp -d /private/tmp/gassi-stock-report.XXXXXX) && mkdir -p "$TASK_TMP/numba" "$TASK_TMP/brain" && NUMBA_CACHE_DIR="$TASK_TMP/numba" JARVIS_BRAIN_DIR="$TASK_TMP/brain" JARVIS_SESSIONS_FILE="$TASK_TMP/sessions.json" JARVIS_CLOUD_DB_PATH="$TASK_TMP/cloud.sqlite" JARVIS_INBOX_FILE="$TASK_TMP/inbox.md" GOOGLE_API_KEY=test-only-key .venv/bin/python -m pytest tests/test_command_center_ui.py tests/test_stock_report_renderer.py -q
```

```text
29 passed in 0.06s
```

The behavior test covers real zero versus null, unknown currency, ratio/percent display, irregular date spacing, keyboard readout, flat and one-point history, matched EPS pairs, historical `earnings_date`, and exclusion of unpaired/future scheduled observations.

## Full verification

The full suite was run once with all runtime/cache paths isolated under a fresh `/private/tmp` directory:

```text
TASK_TMP=$(mktemp -d /private/tmp/gassi-stock-report-full.XXXXXX) && mkdir -p "$TASK_TMP/numba" "$TASK_TMP/brain" && NUMBA_CACHE_DIR="$TASK_TMP/numba" JARVIS_BRAIN_DIR="$TASK_TMP/brain" JARVIS_SESSIONS_FILE="$TASK_TMP/sessions.json" JARVIS_CLOUD_DB_PATH="$TASK_TMP/cloud.sqlite" JARVIS_INBOX_FILE="$TASK_TMP/inbox.md" GOOGLE_API_KEY=test-only-key .venv/bin/python -m pytest -q
```

```text
438 passed, 2 warnings in 9.46s
```

The two warnings are existing Starlette/httpx and OpenBB `ClientSession` deprecation warnings. `git diff --check` and `node --check app/static/app.js` also completed with no output/errors.

## Self-review and handoff

- Scope remained renderer, report/chart CSS and rendering tests; primary form bindings, chat flow, shell HTML and service worker were not edited. Existing compare/history/relationship renderer names and paths remain intact.
- Source identity, date/provenance and missing/zero distinctions are preserved; JavaScript work is limited to display formatting and chart geometry.
- No implementation concern found. The live-browser acceptance pass is controller-owned and remains separate from this local test evidence.
- Scoped local commit subject: `feat(report): render compact stock quick reports` (no push or merge).

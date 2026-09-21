# Swiss and US Macro Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Switzerland and the United States as two clearly separated, simultaneously visible macroeconomic panels backed by canonical OpenBB data.

**Architecture:** Extend the existing macro payload with a backward-compatible `countries` collection while retaining the current top-level US `series` and `failures`. Reuse the canonical macro service with an explicit country on every request, then render the grouped result with native DOM and CSS; unavailable provider data remains explicit.

**Tech Stack:** Python 3.12, FastAPI, canonical OpenBB research layer, vanilla JavaScript, CSS, pytest.

**Spec:** Approved in chat on 2026-09-12: Switzerland first, USA second, both visible; comparable metrics, provenance and date; no fabricated replacements.

## Global Constraints

- Keep all provider access behind `OpenBBResearchClient` and canonical normalization.
- Preserve provenance, `as_of`, freshness, quality, missing values, and typed failure states.
- Keep the existing top-level US `series` and `failures` response fields for compatibility.
- Do not add dependencies, recommendations, trading behavior, or placeholder financial values.
- Desktop panels are side by side and mobile panels stack.

---

### Task 1: Country-scoped canonical macro payload

**Files:**
- Modify: `app/trading/research/jarvis_tools.py`
- Test: `tests/trading/test_macro_context.py`

**Interfaces:**
- Consumes: `CanonicalResearchService.get_macro_series(..., country: str)`.
- Produces: `macro_context_payload(service)` with legacy `series`/`failures` and `countries: [{code, label, series, failures}]`.

- [x] **Step 1: Write the failing test**

Add a service double that records the explicit `country`, returns distinct Swiss/US values, and raises one Swiss provider error. Assert country order `CH`, `US`, country-scoped calls, isolated failures, and unchanged top-level US fields.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/trading/test_macro_context.py -v`
Expected: FAIL because `countries` is absent and country is not passed.

- [x] **Step 3: Write minimal implementation**

Add fixed country definitions and fetch every `(country, spec)` pair through the existing service. Return grouped results and alias the US group's existing lists at the top level.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/trading/test_macro_context.py -v`
Expected: PASS.

### Task 2: Two-country macro presentation

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Test: `tests/test_command_center_ui.py`

**Interfaces:**
- Consumes: `/api/research/macro` `countries` groups with `code`, `label`, `series`, and `failures`.
- Produces: `.macro-countries` containing labeled `.macro-country` panels and `.macro-grid` metrics.

- [x] **Step 1: Write the failing test**

Assert the UI includes grouped-country rendering, visible Switzerland/United States labels, and responsive country-panel CSS.

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k macro -v`
Expected: FAIL because grouped rendering and country-panel styles are absent.

- [x] **Step 3: Write minimal implementation**

Render each country with a heading, metric grid, per-country unavailable count, and existing provider/date metadata. Fall back to the legacy payload as one US group if `countries` is absent. Use CSS grid for two desktop columns and one mobile column.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k macro -v`
Expected: PASS.

### Task 3: Full and browser verification

**Files:**
- Verify only; do not broaden implementation scope.

**Interfaces:**
- Consumes: the completed backend and frontend changes.
- Produces: test and visible browser evidence.

- [x] **Step 1: Run focused and full automated checks**

Run: `.venv/bin/pytest tests/trading/test_macro_context.py tests/test_macro_context_endpoint.py tests/test_command_center_ui.py -v`

Run: `NUMBA_CACHE_DIR=/private/tmp/gassi-jarvis-numba .venv/bin/pytest -q`

Run: `.venv/bin/python -m py_compile app/trading/research/jarvis_tools.py`

Run: `git diff --check`

- [ ] **Step 2: Test in the integrated browser**

Open `http://127.0.0.1:8002/`, verify both country headings are visible, confirm Switzerland appears first, inspect explicit unavailable states, and repeat at a narrow mobile viewport.

- [x] **Step 3: Review scope and limitations**

Inspect `git diff` and `git status --short`; preserve unrelated existing changes. Record which Swiss indicators are provider-backed and which remain explicitly unavailable.

## Recorded outcome

- The final automated run passed 352 tests with one Starlette deprecation warning.
- The PWA loaded the versioned CSS and JavaScript without browser-console errors.
- The live port-8002 instance returned the explicit macro-unavailable state, so
  the two populated country panels were not visually verified in that run.
- The Swiss policy-rate slot still points to FRED `IRSTCI01CHM156N`, an OECD
  call-money/interbank series rather than an official SNB policy-rate series;
  an empty two-year result remains explicit instead of being replaced.

# Stock Quick Report Implementation Plan

**Goal:** A compact data-first stock/ETF report from existing canonical data, with Jarvis remaining a supplementary assistant.
**Spec:** `docs/superpowers/specs/2026-10-17-stock-quick-report-design.md` (approved in chat).
**Architecture:** Preserve the native HTML/CSS/JavaScript PWA, existing FastAPI endpoints and deterministic OpenBB/canonical/report pipeline.
**Execution:** Luna XHigh implementers and reviewers, in sequence because Tasks 2 and 3 share frontend files. Work in the user-approved existing checkout on `codex/stock-quick-report`; preserve main/dev. Local task commits only, no push/merge.

## Global Constraints

- No new providers, runtime packages, framework, realtime promise, financial calculations in JS, automatic AI summary, recommendation, price target or trading action.
- Use existing data and retain identity, provenance, periods, source dates, quality, availability, Decimal/null/zero distinctions.
- Existing chat, voice, HitL, compare/history/relationship and Swiss/US macro context remain accessible.
- English UI and restrained existing visual style; responsive native components.
- Use apply_patch, preserve unrelated work, TDD with observed RED/GREEN evidence. Use `.venv/bin/python`; isolate GOOGLE_API_KEY=test-only-key and NUMBA/runtime paths under /private/tmp. Do not install packages or start a personal-state server.

### Task 1: Timeframes and faithful full-span chart data

**Own:** `app/models.py`, `app/trading/research/report_service.py`, `app/trading/research/reports.py`, `tests/trading/test_asset_research_reports.py`, `tests/test_research_run_endpoint.py` (create this focused route test if absent).

Read the approved spec and project quant skill. Preserve all Global Constraints above. This task changes no frontend files, other financial calculations, provider routes or dependency pins.

1. Write failing behavior tests for `1m`/`3m` and unchanged default/legacy timeframes via the real request model/route; mock the slow research boundary, not route behavior. A failing Gemini function must not affect `/api/research/run`.
2. Write failing sampling tests with more than 180 literal source closes: first/last must survive, count is bounded, original values/timestamps survive, repeat inputs are deterministic. Cover <=180, empty/missing prices, a zero close and flat prices. Avoid mirror expectations computed by the sampling helper.
3. Extend ResearchRunRequest timeframes with `1m`, `3m`, retaining `1y` default and every old value.
4. Replace tail truncation with uniform original-index sampling: for n>180 choose floor(i*(n-1)/179) for i=0..179. For n<=180 retain every valid-close observation. Add `price_history_total: int | None = None` to AssetResearchReport, populated with the original valid-close count; preserve existing report wire fields and compatibility.
5. Focused RED/GREEN, then one isolated full-suite run and diff self-review before a scoped local commit. No push, merge or outside-scope staging.

**Produces:** unchanged `price_history` point shape `{timestamp,close}`, whole-scope sampling <=180 plus optional integer `price_history_total`; existing direct API accepts new timeframes.
**Report:** generated task-1-report.md beside the extracted brief, including commands and RED/GREEN outputs, files, commit and concerns.

### Task 2: Compact report rendering and accessible charts

**Own:** renderer functions in `app/static/app.js`, report/chart styles in `app/static/styles.css`, and rendering-specific tests. Do not change primary form bindings, chat flow, shell HTML or service worker; Task 3 owns those changes after your review.

Read the approved spec and project quant skill. Preserve all Global Constraints above. Task 1 supplies the optional `price_history_total`; older cached/exported reports may omit it. Keep existing public renderer function names callable by the app and preserve compare/history/relationship outputs.

1. Follow TDD. Exercise produced UI behavior/values using the least additional test machinery possible; do not add a runtime package or testing hook to production solely for tests. Existing static contract tests can be adjusted for legitimate contract changes; controller also verifies real browser behavior.
2. Compact stock header and a desktop chart/supporting-data layout, stacking on mobile. Group financial/valuation/earnings metric details with native disclosure elements. Preserve evidence and coverage sections and visible failures/staleness. Use data quality, not a probability of investment success.
3. Upgrade closing-price SVG chart with real date coordinates, readable date/price axes, shared selected-point readout for pointer/touch and keyboard, and a native expandable exact-data table. Indicate selected-point count and original total when known; explicitly label actual downsampling. Flat curves must remain valid; fewer than two finite points show an insufficiency notice without a fake line. Use no fabricated currency or observations.
4. Render first three existing key_findings and an expandable remainder in backend order, with observed/comparison values, comparison period/as-of and provider source. Do not rescore, deduplicate away distinct evidence or invent narratives. Resolve risk finding IDs to the existing evidence and show coverage/warnings.
5. Show at most three supplied news records and five filings with safe HTTP(S) links, date/publisher and noopener on new tabs; unavailable states are explicit.
6. EPS actual/estimate comparison uses only records having finite non-null reported_eps and estimated_eps, paired from the same observation with a supplied period_end (or unambiguous historical earnings_date). Scheduled-only entries never become actuals or zero; include true zero/negative values, date, currency state and distinct actual/estimate labels. No cross-period matching or invented series.
7. Remove implicit USD fallback in the stock quick-report rendering path when currency is missing; show numeric values with an explicit unknown-currency label. Avoid relabeling percentages/ratios as money.
8. Focused RED/GREEN, then one isolated full suite and diff self-review before a scoped local commit. No push/merge or unrelated restructuring.

**Consumes:** existing report sections/findings/risks/earnings/news/filings/provenance plus Task 1 optional total. **Produces:** enhanced existing report renderers, no new backend API.
**Report:** task-2-report.md beside its brief with test evidence, commit and concerns.

### Task 3: Direct report entry, assistant separation and final UI integration

**Own:** `app/static/index.html`, entry/request-state bindings in `app/static/app.js`, shell/layout styles in `app/static/styles.css`, `app/static/sw.js`, `tests/test_command_center_ui.py`, focused entry-state tests, README.md and docs/ui-phase-1-command-center.md. Preserve the reviewed Task 2 renderer behavior.

Read the approved spec and project quant skill. Preserve all Global Constraints above. Task 1 supports `1m`/`3m`; Task 2 renders the report. Primary search must never depend on Gemini.

1. TDD for direct entry and request-state behavior. Make the primary ticker form call existing runResearchWorkflow `/api/research/run` in asset mode, with a visible timeframe control for 1m,3m,6m,1y,2y,5y,all and default1y. Validate ticker without silently interpreting free conversation as a stock request.
2. Keep an explicit separate Jarvis chat/voice entry wired to existing `/api/chat`, session, TTS, microphone, hands-free and HitL flows. Preserve IDs or update all consumers/tests coherently. Do not route task capture or approval responses through ticker validation.
3. Reduce the oversized hero. Put the active report ahead of utility panels; recent/watchlist/provider/device/tools and clearly separate Swiss/US macro context remain accessible using native disclosures/sections. Keep compare/history/relationship modes.
4. On a new request, identify the requested ticker/timeframe, show loading state and prevent superseded/aborted responses from overwriting the latest view. On failure, explicitly label that request failed and do not show an older report as its successful result; older saved reports remain recognizable as previous research. Retain existing authenticated apiFetch helper and safe text rendering.
5. Synchronize versioned HTML/CSS/JS service-worker asset references and corresponding contract tests. Keep config.js and /api network-only.
6. Update README/UI contract for direct entry, data-first role, sampling, chart interactions/EPS and limitations. Link future screenshot `docs/screenshots/jarvis-quick-report.jpg` (controller captures it after verification).
7. Focused RED/GREEN, then one isolated full suite and diff self-review before a scoped local commit. No remote writes, deployment, branch cleanup or new packages.

**Produces:** integrated primary report workflow and preserved supplementary assistant. **Report:** task-3-report.md beside its brief with evidence, commit and concerns.

## Controller acceptance

After each task: package exact task commit range, independent Luna XHigh task review for spec AND quality; fix scoped findings through the implementer. At end: full suite, real browser on isolated runtime, desktop/mobile and controlled missing/failure data cases; capture screenshot, independently review full branch, then leave feature branch for user handoff without merging or pushing. Resolve Obsidian vault only from configured path; if unavailable report that note remains pending, do not invent a vault.

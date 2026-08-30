# Editorial Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current HUD-like Command Center with a calm, command-first editorial research workspace that presents the expanded canonical evidence clearly on desktop and mobile.

**Architecture:** Keep the frontend dependency-free and split the current monolithic document into semantic HTML, CSS, and JavaScript. Render only `research_payload`, keep local watchlist/saved research bounded, and display section-level provenance and limitations without financial calculations or raw provider errors in the browser.

**Tech Stack:** Native HTML5, CSS, browser JavaScript, FastAPI static serving, inline SVG for presentation-only chart scaling, pytest static contracts, Node `--check`, in-app browser verification.

**Spec:** `docs/superpowers/specs/2026-08-20-research-first-command-center-design.md`

**Prerequisite:** Complete and verify `docs/superpowers/plans/2026-08-20-free-tier-research-data.md` first. This plan consumes its quote, metrics, filings, earnings, macro, provider-state, and safe-failure contracts.

## Global Constraints

- No React, bundler, client router, component framework, or new runtime dependency.
- No glass, backdrop blur, translucent panel, panel gradient, decorative orb, glowing border, HUD microcopy, or status-chip cluster.
- Use opaque near-black/graphite surfaces and cyan only for focus, selection, and live activity.
- The browser formats and arranges canonical values but does not calculate, rank, infer, or repair financial evidence.
- Preserve `/api/chat`, `/api/research/run`, voice input, HitL, local watchlist, saved research, JSON/CSV exports, reduced motion, and authentication.
- Do not label configured provider credentials as live or active.
- Do not render raw exception strings, provider subscription URLs, or credential values.
- Mobile starts with the research command, has no horizontal overflow, and keeps provenance accessible.

## File map

- `app/static/index.html`: semantic shell and accessible landmarks only.
- `app/static/styles.css`: tokens, editorial layout, report composition, responsive and motion rules.
- `app/static/app.js`: API calls, bounded local state, workflow forms, canonical renderers, voice, HitL, exports.
- `app/static/sw.js`: cache/version the three static application assets.
- `tests/test_command_center_ui.py`: static structure, copy, style, behavior, and no-glass/no-HUD contracts.
- `tests/test_research_payload_response.py`: backend payload fields consumed by the renderer.
- `docs/ui-phase-1-command-center.md`: final interaction and rendering contract.

---

### Task 1: Split the static application without behavior loss

**Files:**
- Modify: `app/static/index.html:1-167`
- Create: `app/static/styles.css`
- Create: `app/static/app.js`
- Modify: `app/static/sw.js`
- Modify: `tests/test_command_center_ui.py`

**Interfaces:**
- Produces: `/static/styles.css` and `/static/app.js` loaded by `index.html`.
- Preserves: all existing DOM behavior functions until later tasks replace their markup.
- Consumes: existing FastAPI `/static/*` mount and `/sw.js` route.

- [ ] **Step 1: Write failing static-asset tests**

```python
STATIC = UI_PATH.parent
CSS_PATH = STATIC / "styles.css"
JS_PATH = STATIC / "app.js"

def _css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")

def _js() -> str:
    return JS_PATH.read_text(encoding="utf-8")

def test_command_center_loads_separate_native_assets():
    ui = _ui()
    assert '<link rel="stylesheet" href="/static/styles.css">' in ui
    assert '<script src="/static/app.js" defer></script>' in ui
    assert "<style>" not in ui
    assert "<script>" not in ui
    assert (STATIC / "styles.css").is_file()
    assert (STATIC / "app.js").is_file()


def test_service_worker_versions_every_command_center_asset():
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")
    for path in ("/", "/static/styles.css", "/static/app.js"):
        assert repr(path) in worker or f'"{path}"' in worker
```

- [ ] **Step 2: Run static UI tests and confirm failure**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k "separate_native_assets or service_worker_versions" -v`

Expected: FAIL because the CSS and JavaScript are inline.

- [ ] **Step 3: Extract assets mechanically**

Move the complete current `<style>` body into `styles.css` and the complete
current inline script body into `app.js`. Replace them with:

```html
<link rel="stylesheet" href="/static/styles.css">
<script src="/static/app.js" defer></script>
```

Do not alter selectors, function names, or behavior during this step.

- [ ] **Step 4: Version the split assets in the service worker**

```javascript
const CACHE_NAME = 'jarvis-command-center-v3';
const APP_SHELL = [
  '/',
  '/static/styles.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png',
];
```

Keep the existing install, activate, and same-origin fetch behavior; delete old
cache versions on activate.

- [ ] **Step 5: Parse JavaScript and run static tests**

Run: `node --check app/static/app.js`

Expected: exit 0.

Run: `.venv/bin/pytest tests/test_command_center_ui.py -v`

Expected: PASS after assertions are updated to read `styles.css` and `app.js`
through `_css()` and `_js()` helpers.

- [ ] **Step 6: Commit the behavior-preserving split**

```bash
git add app/static/index.html app/static/styles.css app/static/app.js app/static/sw.js tests/test_command_center_ui.py
git commit -m "refactor(ui): split command center assets"
```

---

### Task 2: Build the command-first editorial shell

**Files:**
- Modify: `app/static/index.html`
- Modify: `app/static/styles.css`
- Modify: `app/static/app.js`
- Modify: `tests/test_command_center_ui.py`

**Interfaces:**
- Produces DOM IDs: `appShell`, `researchForm`, `researchInput`, `modeTabs`, `workspace`, `contextPanel`, `recentResearch`, `watchlistState`.
- Preserves function entry points: `send`, `openWorkflow`, `runResearchWorkflow`, `renderSavedResearch`, `renderWatchlist`.
- Consumes authenticated `/api/research/providers` and `/api/research/macro` asynchronously without blocking the prompt.

- [ ] **Step 1: Write failing semantic-layout and anti-slop tests**

```python
def test_editorial_shell_prioritizes_research_command_and_useful_empty_state():
    ui = _ui()
    assert '<h1>Research an asset</h1>' in ui
    assert 'id="researchForm"' in ui
    assert 'id="researchInput"' in ui
    assert 'id="modeTabs"' in ui
    assert 'id="workspace"' in ui
    assert 'id="recentResearch"' in ui
    assert ui.index('id="researchForm"') < ui.index('id="workspace"')


def test_editorial_shell_removes_hud_and_decorative_patterns():
    ui, css = _ui(), _css()
    for stale in ("orb-shell", "orb-ring", "orb-core", "Jarvis research session", "Phase 7 · read-only research", "quality & provenance in response", "no investment advice", "Working method", "Read a result"):
        assert stale not in ui
        assert stale not in css
    assert "text-transform: uppercase" not in css
    assert "radial-gradient" not in css
```

- [ ] **Step 2: Run the layout tests and confirm failure**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k "editorial_shell" -v`

Expected: FAIL on the current orb, rails, copy, and DOM IDs.

- [ ] **Step 3: Replace the main shell with semantic command-first markup**

```html
<body>
  <div class="app-shell" id="appShell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="Jarvis home">Jarvis</a>
      <div class="topbar-actions">
        <span class="connection" id="connectionState">Ready</span>
        <button class="quiet-button" id="clearBtn" type="button">New session</button>
      </div>
    </header>

    <main>
      <section class="command" aria-labelledby="pageTitle">
        <p class="section-label">Independent market research</p>
        <h1 id="pageTitle">Research an asset</h1>
        <p class="command-copy">Prices, fundamentals, filings, macro context, and source quality in one report.</p>
        <form class="research-form" id="researchForm">
          <label class="sr-only" for="researchInput">Asset or research question</label>
          <input id="researchInput" autocomplete="off" placeholder="NVDA, ETH, or compare NVDA with AMD">
          <button type="submit">Research</button>
          <button class="voice-button" id="micBtn" type="button" aria-label="Start voice input">Voice</button>
        </form>
      </section>

      <div class="research-layout">
        <nav class="mode-tabs" id="modeTabs" aria-label="Research modes">
          <button type="button" data-mode="asset" aria-current="page">Asset</button>
          <button type="button" data-mode="compare">Compare</button>
          <button type="button" data-mode="history">History</button>
          <button type="button" data-mode="relationship">Relationship</button>
        </nav>
        <div class="workspace-column">
          <section class="empty-workspace" id="emptyWorkspace">
            <div><h2>Recent research</h2><div id="recentResearch"></div></div>
            <div><h2>Watchlist</h2><div id="watchlistState"></div></div>
            <div id="macroState"></div>
            <div id="providerState"></div>
          </section>
          <section class="workspace" id="workspace" aria-live="polite" aria-busy="false"></section>
        </div>
        <aside class="context-panel" id="contextPanel" aria-label="Research sources and limitations" hidden></aside>
      </div>
    </main>
    <audio id="audioPlayer"></audio>
    <div class="toast" id="toast" role="status" aria-live="polite"></div>
  </div>
</body>
```

Keep the validated workflow panel as a dialog-like inline section immediately
after the mode tabs; it remains native markup and is shown by `openWorkflow`.

- [ ] **Step 4: Define the restrained visual tokens and page grid**

```css
:root {
  color-scheme: dark;
  --bg: #090b0d;
  --surface: #101418;
  --surface-raised: #161b20;
  --surface-hover: #1b2127;
  --line: #262d33;
  --line-strong: #39434b;
  --text: #f3f5f6;
  --muted: #9aa3aa;
  --subtle: #69737b;
  --accent: #78d6ef;
  --positive: #78bc91;
  --negative: #d88888;
  --warning: #d5aa68;
  --radius: 12px;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.app-shell { width: min(1320px, 100%); margin: auto; padding: 20px clamp(18px, 4vw, 56px) 64px; }
.command { width: min(820px, 100%); padding: clamp(64px, 10vw, 120px) 0 44px; }
.research-layout { display: grid; grid-template-columns: 150px minmax(0, 1fr) 260px; gap: 40px; align-items: start; }
.mode-tabs { display: grid; gap: 4px; position: sticky; top: 20px; }
.context-panel[hidden], .empty-workspace[hidden] { display: none; }
```

Use one-pixel opaque borders and shadows only for the focused prompt or menus.
Remove Google Font requests and all mono/uppercase decorative labels.

- [ ] **Step 5: Rebind behavior to the new IDs without changing API payloads**

Change the submit listener to `researchForm`/`researchInput`, map the free-form
command to the existing `/api/chat` path, keep mode workflows on
`/api/research/run`, set `workspace.ariaBusy`, and hide `emptyWorkspace` only
while loading or displaying a result.

Load provider configuration and macro context as optional reference data after
the shell is interactive. Failure leaves these panels absent and never blocks
research:

```javascript
const referenceContext = { providers: [], macro: null };

async function loadReferenceContext() {
  const [providers, macro] = await Promise.allSettled([
    fetchJson('/api/research/providers'),
    fetchJson('/api/research/macro'),
  ]);
  if (providers.status === 'fulfilled') referenceContext.providers = providers.value.providers || [];
  if (macro.status === 'fulfilled') referenceContext.macro = macro.value;
  document.dispatchEvent(new CustomEvent('jarvis:reference-context'));
}

document.addEventListener('DOMContentLoaded', () => {
  bindCommandCenter();
  void loadReferenceContext();
});
```

- [ ] **Step 6: Run JavaScript and static UI tests**

Run: `node --check app/static/app.js && .venv/bin/pytest tests/test_command_center_ui.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the editorial shell**

```bash
git add app/static/index.html app/static/styles.css app/static/app.js tests/test_command_center_ui.py
git commit -m "feat(ui): build editorial research shell"
```

---

### Task 3: Render a document-style asset report

**Files:**
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Modify: `tests/test_command_center_ui.py`
- Modify: `tests/test_research_payload_response.py`

**Interfaces:**
- Consumes: report `asset`, `as_of`, `sections`, `price_history`, `data_coverage`, `sources`, `filings`, and `news`.
- Produces: `renderAssetReport(payload) -> HTMLElement`.
- Produces: `renderComparisonReport`, `renderHistoricalReport`, and `renderRelationshipReport` with the same document hierarchy.
- Produces: `formatMoney`, `formatCompact`, `formatRatio`, `formatPercent`, `formatDate`, `formatTimestamp`.

- [ ] **Step 1: Write failing renderer-contract tests**

```python
def test_asset_renderer_has_document_sections_and_compact_formatters():
    js = _js()
    for name in ("renderAssetReport", "renderAssetHeader", "renderPriceHistory", "renderMetricSections", "renderComparisonReport", "renderHistoricalReport", "renderRelationshipReport", "formatMoney", "formatCompact", "formatRatio", "formatPercent"):
        assert f"function {name}" in js
    for heading in ("Market snapshot", "Price history", "Fundamentals", "Valuation"):
        assert heading in js


def test_research_payload_includes_ui_evidence_contract():
    payload = {
        "status": "success",
        "reports": [{
            "asset": {"symbol": "NVDA", "currency": "USD"},
            "price_history": [{"timestamp": "2026-08-20T00:00:00+00:00", "close": "216.61"}],
            "filings": [{"form_type": "10-Q", "url": "https://www.sec.gov/Archives/example.htm"}],
            "sections": [
                {"key": "snapshot", "metrics": [{"key": "last_price", "value": "216.61"}]},
                {"key": "valuation", "metrics": [{"key": "pe_ratio", "value": "31.8"}]},
                {"key": "fundamentals", "metrics": [{"key": "revenue", "value": "100"}]},
            ],
        }],
    }
    response = asyncio.run(main_module._build_response(
        "Research report created.",
        action="finance_research:research_asset",
        research_payload=payload,
        generate_audio=False,
    ))
    report = response["research_payload"]["reports"][0]
    assert report["asset"]["symbol"] == "NVDA"
    assert report["price_history"]
    assert report["filings"][0]["form_type"] == "10-Q"
    assert {section["key"] for section in report["sections"]} >= {"snapshot", "valuation", "fundamentals"}
```

- [ ] **Step 2: Run renderer-contract tests and confirm failure**

Run: `.venv/bin/pytest tests/test_command_center_ui.py tests/test_research_payload_response.py -k "document_sections or ui_evidence_contract" -v`

Expected: FAIL because the current renderer creates one `.answer` card and lacks the expanded payload.

- [ ] **Step 3: Add locale-safe compact formatting helpers**

```javascript
const numberFormat = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 });

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatCompact(value) {
  const number = finiteNumber(value);
  return number === null ? 'Not available' : compactFormat.format(number);
}

function formatMoney(value, currency = 'USD') {
  const number = finiteNumber(value);
  if (number === null) return 'Not available';
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency, notation: Math.abs(number) >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: 2,
  }).format(number);
}

function formatRatio(value) {
  const number = finiteNumber(value);
  return number === null ? 'Not available' : numberFormat.format(number) + 'x';
}

function formatPercent(value) {
  const number = finiteNumber(value);
  return number === null ? 'Not available' : numberFormat.format(number) + '%';
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Date unavailable' : new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).format(date);
}

function formatTimestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Time unavailable' : new Intl.DateTimeFormat('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date);
}
```

Metric keys own their display kind in one immutable map; do not guess formatting
from magnitude.

- [ ] **Step 4: Render the asset header and primary chart**

```javascript
function element(tag, className = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

function reportSection(title) {
  const section = element('section', 'report-section');
  const heading = element('h2');
  heading.textContent = title;
  section.append(heading);
  return section;
}

function sectionByKey(report, key) {
  return (Array.isArray(report.sections) ? report.sections : []).find(section => section.key === key) || null;
}

function metricMap(section) {
  return Object.fromEntries((section?.metrics || []).map(item => [item.key, item.value]));
}

function textBlock(tag, className, title, copy = '') {
  const node = element(tag, className);
  const heading = element('h2');
  heading.textContent = title;
  node.append(heading);
  if (copy) {
    const paragraph = element('p');
    paragraph.textContent = copy;
    node.append(paragraph);
  }
  return node;
}

function metricBlock(labelText, valueText) {
  const node = element('div', 'hero-metric');
  const label = element('span');
  const value = element('strong');
  label.textContent = labelText;
  value.textContent = valueText;
  node.append(label, value);
  return node;
}

function metadataLine(items) {
  const node = element('p', 'report-meta');
  node.textContent = items.filter(Boolean).join(' · ');
  return node;
}

function sourceFor(report, category) {
  const source = (report.sources || []).find(item => item.source_category === category);
  return source?.provider ? 'Source: ' + providerName(source.provider) : null;
}

function renderAssetHeader(report) {
  const snapshot = sectionByKey(report, 'snapshot');
  const values = metricMap(snapshot);
  const header = element('header', 'report-header');
  header.append(
    textBlock('div', 'report-identity', report.asset?.symbol || 'Asset', report.asset?.name || ''),
    metricBlock('Observed price', formatMoney(values.last_price, report.asset?.currency || 'USD')),
    metadataLine([
      report.asset?.exchange,
      report.as_of ? 'As of ' + formatTimestamp(report.as_of) : null,
      sourceFor(report, 'equity_quote'),
    ]),
  );
  return header;
}
```

`renderPriceHistory` keeps inline SVG presentation scaling but formats the two
endpoint labels through `formatMoney` and `formatDate`; it never computes a
return, moving average, or ranking.

```javascript
function renderPriceHistory(report) {
  const rows = (report.price_history || []).filter(row => finiteNumber(row.close) !== null);
  if (rows.length < 2) return null;
  const closes = rows.map(row => finiteNumber(row.close));
  const low = Math.min(...closes);
  const high = Math.max(...closes);
  const span = high - low || 1;
  const points = closes.map((close, index) => {
    const x = (index / (rows.length - 1)) * 100;
    const y = 100 - ((close - low) / span) * 100;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');
  const section = reportSection('Price history');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `Observed closing prices from ${formatDate(rows[0].timestamp)} to ${formatDate(rows.at(-1).timestamp)}`);
  const line = document.createElementNS(svg.namespaceURI, 'polyline');
  line.setAttribute('points', points);
  line.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(line);
  section.append(svg, metadataLine([
    `${formatMoney(rows[0].close, report.asset?.currency || 'USD')} on ${formatDate(rows[0].timestamp)}`,
    `${formatMoney(rows.at(-1).close, report.asset?.currency || 'USD')} on ${formatDate(rows.at(-1).timestamp)}`,
  ]));
  return section;
}
```

- [ ] **Step 5: Render observed metric and fundamental sections**

`renderMetricSections` visits a fixed order:

```javascript
const REPORT_ORDER = ['snapshot', 'valuation', 'fundamentals', 'estimates'];
const METRIC_LABELS = {
  last_price: 'Observed price', previous_close: 'Previous close',
  market_cap: 'Market cap', enterprise_value: 'Enterprise value',
  pe_ratio: 'P/E', forward_pe: 'Forward P/E', price_to_sales: 'Price / sales',
  price_to_book: 'Price / book', ev_to_ebitda: 'EV / EBITDA',
  free_cash_flow_yield: 'Free-cash-flow yield', revenue: 'Revenue',
  operating_income: 'Operating income', net_income: 'Net income',
  free_cash_flow: 'Free cash flow', cash: 'Cash', total_debt: 'Debt',
};
```

Each section is separated by a divider, not wrapped in a large panel. Use a
responsive metric list with label, value, period/as-of, and a source footnote.
Skip absent metrics entirely.

```javascript
const METRIC_KIND = {
  last_price: 'money', previous_close: 'money', market_cap: 'money',
  enterprise_value: 'money', revenue: 'money', operating_income: 'money',
  net_income: 'money', free_cash_flow: 'money', cash: 'money', total_debt: 'money',
  pe_ratio: 'ratio', forward_pe: 'ratio', price_to_sales: 'ratio',
  price_to_book: 'ratio', ev_to_ebitda: 'ratio', free_cash_flow_yield: 'percent',
};

function formatMetric(metric, currency) {
  const kind = METRIC_KIND[metric.key];
  if (kind === 'money') return formatMoney(metric.value, currency);
  if (kind === 'ratio') return formatRatio(metric.value);
  if (kind === 'percent') return formatPercent(metric.value);
  return finiteNumber(metric.value) === null
    ? String(metric.value ?? 'Not available')
    : numberFormat.format(Number(metric.value));
}

function renderMetricList(metrics, labels, currency) {
  const list = element('dl', 'metric-list');
  metrics.filter(metric => metric.value !== null && metric.value !== undefined).forEach(metric => {
    const item = element('div', 'metric-row');
    const label = element('dt');
    const value = element('dd');
    label.textContent = labels[metric.key] || readableLabel(metric.key);
    value.textContent = formatMetric(metric, metric.unit || currency);
    item.append(label, value);
    list.append(item);
  });
  return list;
}

function renderMetricSections(report) {
  const fragment = document.createDocumentFragment();
  REPORT_ORDER.forEach(key => {
    const source = sectionByKey(report, key);
    if (!source?.metrics?.some(metric => metric.value !== null && metric.value !== undefined)) return;
    const section = reportSection(source.title || readableLabel(key));
    section.append(renderMetricList(source.metrics, METRIC_LABELS, report.asset?.currency || 'USD'));
    if (source.provenance?.length) {
      section.append(metadataLine(source.provenance.map(item => providerName(item.provider))));
    }
    fragment.append(section);
  });
  return fragment;
}

function renderAssetReport(payload) {
  const report = payload.reports?.[0];
  if (!report) return textBlock('section', 'report-empty', 'Research unavailable', 'No canonical report was returned.');
  const article = element('article', 'asset-report');
  article.tabIndex = -1;
  article.append(renderAssetHeader(report));
  const chart = renderPriceHistory(report);
  if (chart) article.append(chart);
  article.append(renderMetricSections(report));
  return article;
}
```

- [ ] **Step 6: Replace generic answer-card rendering for research actions**

Implement `renderComparisonReport` as two aligned asset columns followed by
the canonical comparison dimensions; `renderHistoricalReport` as an event
table with observation dates, windows, and canonical metrics; and
`renderRelationshipReport` as an observed coefficient/beta block with sample
size and period. They share `reportSection`, `renderMetricList`, and context
rendering, never add rankings or interpretations, and collapse to one column on
mobile.

In `addAnswer`, dispatch finance payloads by the presence of `reports`,
`comparison`, `historical_results`, or `statistical_results`:

```javascript
function renderResearchPayload(payload) {
  if (payload.comparison) return renderComparisonReport(payload);
  if (payload.historical_results?.length) return renderHistoricalReport(payload);
  if (payload.statistical_results?.length) return renderRelationshipReport(payload);
  return renderAssetReport(payload);
}
```

Non-finance chat and HitL remain compact conversation cards. Do not render
`jarvis_response` as the dominant finance summary; use it only as a concise
status line when useful.

- [ ] **Step 7: Run parsing, payload, and static UI tests**

Run: `node --check app/static/app.js && .venv/bin/pytest tests/test_command_center_ui.py tests/test_research_payload_response.py -v`

Expected: PASS.

- [ ] **Step 8: Commit document-style reports**

```bash
git add app/static/app.js app/static/styles.css tests/test_command_center_ui.py tests/test_research_payload_response.py
git commit -m "feat(ui): render editorial asset reports"
```

---

### Task 4: Earnings, filings, news, sources, and limitations

**Files:**
- Modify: `app/static/app.js`
- Modify: `app/static/styles.css`
- Modify: `tests/test_command_center_ui.py`

**Interfaces:**
- Consumes: canonical report filings/news, coverage, sources, safe failures, provider attempts, macro context, and provider configuration.
- Produces: `renderEarnings`, `renderFilings`, `renderDirectNews`, `renderMacroContext`, `renderProviderConfiguration`, `renderContextPanel`, `renderSectionNotice`.
- Preserves: export and watchlist actions.

- [ ] **Step 1: Write failing evidence and safe-error tests**

```python
def test_report_renderer_exposes_filings_news_and_section_context():
    js = _js()
    for name in ("renderEarnings", "renderFilings", "renderDirectNews", "renderMacroContext", "renderProviderConfiguration", "renderContextPanel", "renderSectionNotice"):
        assert f"function {name}" in js
    assert "Recent filings" in js
    assert "Directly relevant news" in js
    assert "Sources" in js
    assert "Coverage" in js


def test_ui_never_renders_raw_provider_plan_errors():
    js = _js()
    assert "Premium Query Parameter" not in js
    assert "subscription page" not in js
    assert "financialmodelingprep.com" not in js
    assert "failure.message" not in js
```

- [ ] **Step 2: Run the evidence tests and confirm failure**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k "filings_news or provider_plan_errors" -v`

Expected: FAIL because the current renderer joins warning strings into the result.

- [ ] **Step 3: Render bounded earnings and filings**

```javascript
function renderFilings(report) {
  const filings = Array.isArray(report.filings) ? report.filings.slice(0, 5) : [];
  if (!filings.length) return null;
  const section = reportSection('Recent filings');
  const list = element('ol', 'filing-list');
  filings.forEach(filing => {
    const link = element('a', 'filing-link');
    link.href = filing.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = filing.form_type;
    const meta = element('span', 'filing-meta');
    meta.textContent = [filing.description, formatDate(filing.filing_date)].filter(Boolean).join(' · ');
    const item = element('li', 'filing-row');
    item.append(link, meta);
    list.append(item);
  });
  section.append(list);
  return section;
}

function renderEarnings(report) {
  const source = sectionByKey(report, 'earnings');
  if (!source?.metrics?.length) return null;
  const section = reportSection('Earnings and consensus');
  section.append(renderMetricList(source.metrics, {
    eps_consensus: 'Consensus EPS', revenue_consensus: 'Consensus revenue',
    eps_actual: 'Actual EPS', revenue_actual: 'Actual revenue',
  }, report.asset?.currency || 'USD'));
  const note = element('p', 'section-note');
  note.textContent = 'Observed provider consensus; not investment advice.';
  section.append(note);
  return section;
}
```

`renderEarnings` labels future values `Consensus EPS` and `Consensus revenue`;
actual/surprise rows appear only when actual values exist. Add one quiet line:
`Observed provider consensus; not investment advice.`

- [ ] **Step 4: Render at most three filtered news articles**

Use the already backend-filtered `report.news`. Show headline, publisher, and
publication date. Do not repeat excerpts by default; expose an excerpt only
when it is non-empty in a native `<details>` element.

```javascript
function renderDirectNews(report) {
  const news = Array.isArray(report.news) ? report.news.slice(0, 3) : [];
  if (!news.length) return null;
  const section = reportSection('Directly relevant news');
  const list = element('ol', 'news-list');
  news.forEach(article => {
    const item = element('li', 'news-row');
    const link = element('a');
    link.href = article.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = article.title;
    item.append(link, metadataLine([article.publisher, formatDate(article.published_at)]));
    if (article.excerpt) {
      const details = element('details');
      const summary = element('summary');
      const excerpt = element('p');
      summary.textContent = 'Summary';
      excerpt.textContent = article.excerpt;
      details.append(summary, excerpt);
      item.append(details);
    }
    list.append(item);
  });
  section.append(list);
  return section;
}
```

- [ ] **Step 5: Move coverage, sources, and notices into context**

```javascript
function renderContextPanel(report, payload) {
  const panel = document.getElementById('contextPanel');
  panel.replaceChildren();
  const macro = renderMacroContext(referenceContext.macro);
  if (macro) panel.append(macro);
  panel.append(sectionList('Sources', sourceRows(report.sources || payload.sources || [])));
  panel.append(sectionList('Coverage', coverageRows(report.data_coverage || [])));
  const notices = safeNotices(report.data_coverage || []);
  if (notices.length) panel.append(sectionList('Limitations', notices));
  const providers = renderProviderConfiguration(referenceContext.providers);
  if (providers) panel.append(providers);
  panel.append(renderResultActions(payload, report));
  panel.hidden = panel.childElementCount === 0;
}

function renderMacroContext(payload) {
  const series = Array.isArray(payload?.series) ? payload.series : [];
  const rows = series.flatMap(item => {
    const latest = item.observations?.at(-1);
    if (!latest || finiteNumber(latest.value) === null) return [];
    return [`${item.asset?.name || readableLabel(item.asset?.symbol)}: ${numberFormat.format(Number(latest.value))} ${item.unit || ''} · ${formatDate(latest.timestamp)}`];
  });
  return rows.length ? sectionList('Market context', rows) : null;
}

function renderProviderConfiguration(providers) {
  const rows = (providers || [])
    .filter(item => item.configuration_state !== 'not_configured')
    .map(item => `${providerName(item.provider)} · ${item.configuration_state === 'built_in' ? 'Built in' : 'Configured'}`);
  return rows.length ? sectionList('Data connections', rows) : null;
}

function renderEmptyReferenceContext() {
  const macroState = document.getElementById('macroState');
  const providerState = document.getElementById('providerState');
  const macro = renderMacroContext(referenceContext.macro);
  const providers = renderProviderConfiguration(referenceContext.providers);
  macroState.replaceChildren(...(macro ? [macro] : []));
  providerState.replaceChildren(...(providers ? [providers] : []));
}

document.addEventListener('jarvis:reference-context', renderEmptyReferenceContext);

function sectionList(title, rows) {
  if (!rows.length) return document.createDocumentFragment();
  const section = element('section', 'context-section');
  const heading = element('h2');
  const list = element('ul');
  heading.textContent = title;
  rows.forEach(row => {
    const item = element('li');
    item.textContent = row;
    list.append(item);
  });
  section.append(heading, list);
  return section;
}

function sourceRows(sources) {
  return sources.map(source => {
    const attempts = (source.attempts || [])
      .filter(attempt => attempt.outcome === 'failure')
      .map(attempt => `${providerName(attempt.provider)} ${readableLabel(attempt.code)}`);
    return [
      providerName(source.provider), readableLabel(source.source_category),
      source.retrieved_at ? formatTimestamp(source.retrieved_at) : null,
      attempts.length ? `Fallback after ${attempts.join(', ')}` : null,
    ].filter(Boolean).join(' · ');
  });
}

function coverageRows(coverage) {
  return coverage.map(item => [
    readableLabel(item.section), readableLabel(item.availability), readableLabel(item.freshness),
  ].filter(Boolean).join(' · '));
}

function renderSectionNotice(item, failureCode = null) {
  const section = readableLabel(item.section || 'section');
  const stableCopy = FAILURE_COPY[failureCode] || null;
  if (stableCopy) return `${section}: ${stableCopy}`;
  if (item.availability === 'missing') return `${section}: No data was returned for this scope.`;
  if (item.freshness === 'stale') return `${section}: The latest observation is stale.`;
  if (Array.isArray(item.missing_fields) && item.missing_fields.length) {
    return `${section}: Missing ${item.missing_fields.map(readableLabel).join(', ')}.`;
  }
  return null;
}

function safeNotices(coverage) {
  return coverage.flatMap(item => {
    const failures = Array.isArray(item.failures) ? item.failures : [];
    const codes = failures.map(failure => failure.code).filter(code => FAILURE_COPY[code]);
    const notices = codes.map(code => renderSectionNotice(item, code)).filter(Boolean);
    if (!notices.length) {
      const fallback = renderSectionNotice(item);
      if (fallback) notices.push(fallback);
    }
    return notices;
  });
}

function renderResultActions(payload, report) {
  const actions = element('div', 'result-actions');
  actions.append(
    actionButton('Save', () => saveResearch(payload)),
    actionButton('Watch', () => addToWatchlist(report.asset)),
    actionButton('Export JSON', () => exportJson(payload)),
    actionButton('Export CSV', () => exportCsv(report)),
  );
  return actions;
}
```

Extend `renderAssetReport` after its metric sections with `renderEarnings`,
`renderFilings`, and `renderDirectNews` in that order, appending only non-null
nodes, then call `renderContextPanel(report, payload)`. This keeps the Task 3
renderer valid before these evidence renderers are introduced.

`safeNotices` uses section, availability, freshness, missing fields, and stable
failure code. It never inserts raw `message` from an unknown payload. Known
codes map through:

```javascript
const FAILURE_COPY = {
  entitlement_required: 'Not included in the configured provider tier.',
  rate_limited: 'Temporarily rate limited by the provider.',
  no_data: 'No data was returned for this scope.',
  unsupported_endpoint: 'This provider does not support the requested section.',
  missing_credential: 'An optional provider credential is not configured.',
};
```

- [ ] **Step 6: Preserve exports, watchlist, saved research, and HitL**

Keep canonical JSON export unchanged. CSV stays presentation-oriented but adds
`section`, `provider`, `as_of`, and `retrieved_at` columns when present. Saved
research remains capped at six results. Existing remove actions and HitL
approve/decline behavior remain intact.

- [ ] **Step 7: Run UI and JavaScript tests**

Run: `node --check app/static/app.js && .venv/bin/pytest tests/test_command_center_ui.py -v`

Expected: PASS.

- [ ] **Step 8: Commit evidence context and safe errors**

```bash
git add app/static/app.js app/static/styles.css tests/test_command_center_ui.py
git commit -m "feat(ui): present sources filings and limitations"
```

---

### Task 5: Responsive, accessible, and motion-safe composition

**Files:**
- Modify: `app/static/styles.css`
- Modify: `app/static/app.js`
- Modify: `app/static/index.html`
- Modify: `tests/test_command_center_ui.py`

**Interfaces:**
- Produces: desktop three-area composition, tablet tabs, mobile single column.
- Preserves: keyboard focus, `aria-live`, `aria-busy`, reduced motion, voice status.

- [ ] **Step 1: Write failing responsive and accessibility tests**

```python
def test_editorial_ui_has_responsive_and_accessible_contracts():
    ui, css, js = _ui(), _css(), _js()
    assert '@media (max-width: 960px)' in css
    assert '@media (max-width: 680px)' in css
    assert 'prefers-reduced-motion: reduce' in css
    assert 'overflow-x: hidden' not in css
    assert 'aria-live="polite"' in ui
    assert 'aria-busy="false"' in ui
    assert 'focus-visible' in css
    assert "workspace.setAttribute('aria-busy'" in js
```

- [ ] **Step 2: Run responsive/accessibility tests and confirm failure**

Run: `.venv/bin/pytest tests/test_command_center_ui.py -k "responsive_and_accessible" -v`

Expected: FAIL until the new layout contracts are present.

- [ ] **Step 3: Add tablet and mobile layout rules**

```css
@media (max-width: 960px) {
  .research-layout { grid-template-columns: 1fr; gap: 32px; }
  .mode-tabs { display: flex; overflow-x: auto; position: static; }
  .context-panel { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
}

@media (max-width: 680px) {
  .app-shell { padding: 14px 16px 48px; }
  .topbar { min-height: 48px; }
  .command { padding: 52px 0 32px; }
  .research-form { grid-template-columns: minmax(0, 1fr) auto; }
  .voice-button { grid-column: 1 / -1; width: 100%; }
  .mode-tabs { overflow-x: auto; scrollbar-width: none; }
  .empty-workspace, .metric-list, .context-panel { grid-template-columns: 1fr; }
  .report-header { grid-template-columns: 1fr; }
}
```

Do not hide overflowing content globally. Every grid child gets `min-width: 0`,
long links use `overflow-wrap: anywhere`, and numeric labels do not force a
minimum width.

- [ ] **Step 4: Keep state announcements and motion preferences accurate**

```javascript
function setWorkspaceBusy(isBusy) {
  workspace.setAttribute('aria-busy', String(isBusy));
  connectionState.textContent = isBusy ? 'Researching' : 'Ready';
}
```

Focus the report heading after a completed keyboard submission without
scroll-jacking pointer users. Disable smooth scroll, shimmer movement, and
transitions under `prefers-reduced-motion: reduce`.

- [ ] **Step 5: Run parsing and UI tests**

Run: `node --check app/static/app.js && .venv/bin/pytest tests/test_command_center_ui.py -v`

Expected: PASS.

- [ ] **Step 6: Commit responsive and accessibility work**

```bash
git add app/static/index.html app/static/styles.css app/static/app.js tests/test_command_center_ui.py
git commit -m "fix(ui): refine responsive research workspace"
```

---

### Task 6: UI documentation and completion verification

**Files:**
- Modify: `docs/ui-phase-1-command-center.md`
- Modify: `docs/jarvis-pwa.png` only if a verified screenshot is intentionally retained
- Test: complete repository and live local Command Center

**Interfaces:**
- Consumes: all backend and frontend deliverables.
- Produces: verified documentation, screenshots if retained, and final acceptance evidence.

- [ ] **Step 1: Update the UI contract document**

Replace the old orb/rail/card description with the command-first shell, document
report section ordering, format rules, context-panel behavior, local utility
limits, safe failure copy, breakpoints, reduced motion, and the deliberate
decision to remain framework-free.

- [ ] **Step 2: Run static and JavaScript gates**

Run: `node --check app/static/app.js`

Expected: exit 0.

Run: `.venv/bin/pytest tests/test_command_center_ui.py tests/test_research_payload_response.py tests/test_macro_context_endpoint.py tests/test_research_run_endpoint.py -v`

Expected: PASS.

- [ ] **Step 3: Run the complete credential-free suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass, with only previously documented dependency warnings.

- [ ] **Step 4: Start or reload the local server**

Run: `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001`

Expected: server listens on `http://127.0.0.1:8001/`. If another verified
Jarvis process already owns the port, restart that process rather than starting
a second server.

- [ ] **Step 5: Verify the desktop empty and result states in the in-app browser**

At a 1440 x 1000 viewport, verify:

- the command is reachable without scrolling;
- the useful empty state shows recent research and watchlist;
- an NVDA report renders header, chart, metrics, fundamentals, earnings,
  filings, directly relevant news, sources, and section limitations;
- no raw provider exception or subscription URL appears;
- numbers are compact and no content overlaps or overflows.

- [ ] **Step 6: Verify tablet and mobile states**

At 900 x 900 and 390 x 844 viewports, verify empty, loading, complete, partial,
fallback, and failed-section states. Confirm horizontal overflow by evaluating:

```javascript
document.documentElement.scrollWidth === document.documentElement.clientWidth
```

Expected: `true` at every viewport. Confirm mode tabs remain keyboard reachable,
the report becomes one column, and sources/limitations remain accessible.

- [ ] **Step 7: Verify interaction and reduced motion**

Use keyboard-only navigation through prompt, modes, workflow fields, report
links, exports, saved research, watchlist removal, and new session. Emulate
reduced motion and confirm no animated orb, shimmer, or smooth scrolling runs.
Verify voice-unavailable and connection-error states remain readable.

- [ ] **Step 8: Inspect final diff and commit documentation**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intentional task files and pre-existing
user-owned changes remain.

```bash
git add docs/ui-phase-1-command-center.md
git commit -m "docs: document editorial command center"
```

- [ ] **Step 9: Update the configured Jarvis Obsidian project note**

Resolve `JARVIS_OBSIDIAN_VAULT` or `.codex/obsidian-vault-path`, then append a
credential-free dated entry to `Jarvis/Gassi Jarvis Quant Research.md` with the
provider policy, new canonical sections, verification results, explicit
free-tier limitations, UI direction, and next intended phase. Do not copy raw
provider payloads or keys.

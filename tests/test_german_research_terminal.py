"""Behavior checks for the German, identity-first research terminal."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
HTML = STATIC / "index.html"
APP_JS = STATIC / "app.js"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"


TERMINAL_CHECK = r"""
const assert = require('node:assert/strict');
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.attributes = {}; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  replaceChildren(...children) { this._text = ''; this.children = children; }
}
const document = { createElement: tag => new Element(tag) };
const source = require('node:fs').readFileSync(0, 'utf8');
const start = source.indexOf('    function buildResearchSearchUrl');
const end = source.indexOf('    function renderSearchResults', start);
const finish = source.indexOf('    function setState', end);
assert.ok(start >= 0 && end > start && finish > end, 'terminal helpers are available');
const helpers = source.slice(start, finish) + '\nreturn { buildResearchSearchUrl, buildResearchRunPayload, renderSearchResults, selectResearchAsset, isCurrentResearchRequest };';
const api = new Function('document', 'encodeURIComponent', helpers)(document, encodeURIComponent);

assert.equal(api.buildResearchSearchUrl('Nestlé & Co', 'equity'), '/api/research/search?query=Nestl%C3%A9%20%26%20Co&asset_type=equity');
const primary = { symbol: 'NESN', name: 'Nestlé S.A.', exchange: 'SIX', currency: 'CHF', asset_type: 'equity', isin: 'CH0038863350' };
assert.deepEqual(api.buildResearchRunPayload(primary, '1y'), {
  mode: 'asset', asset: 'NESN', asset_type: 'equity', exchange: 'SIX', currency: 'CHF', timeframe: '1y'
});
const benchmark = { symbol: 'CHSPI', name: 'SPI ETF', exchange: 'SIX', currency: 'CHF', asset_type: 'etf' };
assert.deepEqual(api.buildResearchRunPayload(primary, '3m', 'compare', benchmark), {
  mode: 'compare', asset: 'NESN', asset_type: 'equity', exchange: 'SIX', currency: 'CHF', timeframe: '3m',
  benchmark: 'CHSPI', benchmark_asset_type: 'etf', benchmark_exchange: 'SIX', benchmark_currency: 'CHF'
});
assert.deepEqual(api.buildResearchRunPayload(primary, '1y', 'asset', null, true), {
  mode: 'asset', asset: 'NESN', asset_type: 'equity', exchange: 'SIX', currency: 'CHF', timeframe: '1y', refresh: true
});

const list = new Element('div');
let selected = null;
api.renderSearchResults([primary], list, value => { selected = value; });
assert.equal(selected, null, 'search results require explicit selection');
assert.match(list.children[0].textContent, /Name: Nestlé S\.A\..*Ticker: NESN.*Handelsplatz: SIX.*Währung: CHF.*ISIN: CH0038863350/);
list.children[0].listeners.click();
assert.equal(selected, primary, 'selecting a result preserves its identity fields');

const selectedButton = { attributes: {}, setAttribute(name, value) { this.attributes[name] = String(value); } };
let focused = false;
const searchResults = { hidden: false, querySelectorAll: () => [selectedButton] };
const selectedAssetPanel = { hidden: true, textContent: '' };
const reportButton = { disabled: true, focus() { focused = true; } };
const coreState = { textContent: '' };
assert.equal(api.selectResearchAsset(primary, selectedButton, { searchResults, selectedAssetPanel, reportButton, coreState }), primary);
assert.equal(searchResults.hidden, true, 'confirming identity collapses the candidate list');
assert.equal(selectedAssetPanel.hidden, false);
assert.equal(selectedButton.attributes['aria-pressed'], 'true');
assert.equal(reportButton.disabled, false);
assert.equal(focused, true, 'selection moves keyboard focus to the report action');
assert.match(selectedAssetPanel.textContent, /Ticker: NESN.*ISIN: CH0038863350/);
const olderRequest = {};
const latestRequest = {};
assert.equal(api.isCurrentResearchRequest(latestRequest, latestRequest), true);
assert.equal(api.isCurrentResearchRequest(latestRequest, olderRequest), false, 'superseded async work cannot update the UI');
"""


def _run_terminal_check() -> None:
    result = subprocess.run(
        [NODE, "-e", TERMINAL_CHECK],
        cwd=ROOT,
        env=os.environ.copy(),
        input=APP_JS.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_terminal_helpers_encode_search_and_preserve_selected_identity() -> None:
    assert Path(NODE).is_file(), "Node.js is required for these frontend behavior checks"
    _run_terminal_check()


def test_german_terminal_has_explicit_asset_types_and_timeframes() -> None:
    html = HTML.read_text(encoding="utf-8")

    assert '<html lang="de">' in html
    for asset_type, label in (("equity", "Aktie"), ("etf", "ETF"), ("crypto", "Krypto")):
        assert f'data-asset-type="{asset_type}"' in html
        assert label in html
    for timeframe in ("1m", "3m", "6m", "1y", "2y", "5y", "all"):
        assert f'value="{timeframe}"' in html
    assert 'id="searchResults"' in html
    assert 'id="runReportBtn"' in html
    assert 'id="systemPanel"' in html
    assert "Systemstatus und Mac-Status" in html
    assert 'id="coreState" aria-live="polite"' in html
    assert '/static/styles.css?v=12' in html
    assert '/static/app.js?v=12' in html


def test_service_worker_uses_the_current_terminal_assets() -> None:
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")

    assert "jarvis-command-center-v14" in worker
    assert "'/static/styles.css?v=12'" in worker
    assert "'/static/app.js?v=12'" in worker


def test_terminal_uses_direct_research_endpoint_and_safe_rendering() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "apiFetch(buildResearchSearchUrl(query, assetType)," in js
    assert "apiFetch('/api/research/run'" in js
    assert "buildResearchRunPayload(selection, timeframe" in js
    assert "renderSearchResults(results, container, onSelect)" in js
    assert "result?.asset_type === assetType" in js
    assert "renderSearchResults(data.results[0]" not in js
    assert "innerHTML =" not in js
    assert "searchResults.hidden = false" in js
    assert "document.getElementById('workspace').scrollIntoView" in js
    assert js.count("!isCurrentResearchRequest(controller, requestController)") >= 5
    assert "controller = null; clearLoading(); setState('idle')" in js


def test_report_is_german_compact_and_has_identity_followups() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "findings.slice(0, 5)" in js
    assert "Historische Analyse" in js
    assert "Vergleich" in js
    assert "Kennzahlen" in js
    assert "Quellen" in js


def test_report_exposes_verified_units_partial_state_and_financial_history() -> None:
    js = APP_JS.read_text(encoding="utf-8")

    assert "if (kind === 'money') return formatMoney(metric.value, metric.unit)" in js
    assert "function renderOverviewMetrics" in js
    assert "function renderFinancialHistory" in js
    assert "report.financial_history" in js
    assert "report.is_partial" in js
    assert "safeHttpUrl(coverage.reference_url)" in js
    assert "safeHttpUrl(extra.website)" in js
    assert "report.asset?.currency" in js
    assert "Währung unbekannt" in js

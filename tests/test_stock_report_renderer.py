"""Behavior checks for the native stock-report renderer using Node's built-ins."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "app.js"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"


RENDERER_CHECK = r"""
const assert = require('node:assert/strict');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = {}; this.value = ''; this._text = ''; this.classes = new Set();
    this.classList = { toggle: (name, force) => { if (force) this.classes.add(name); else this.classes.delete(name); } };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set className(value) { this._className = value; this.classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  get className() { return this._className || ''; }
  append(...items) { for (const item of items) { this._text = ''; this.children.push(item); } }
  appendChild(item) { this.append(item); return item; }
  setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'class') this.className = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  getBoundingClientRect() { return { left: 0, width: 520 }; }
}
const document = { createElement: tag => new Element(tag), createElementNS: (_ns, tag) => new Element(tag), createDocumentFragment: () => new Element('fragment') };
const fullSource = require('node:fs').readFileSync(0, 'utf8');
const start = fullSource.indexOf('    const PRESENTATION_LABELS =');
const end = fullSource.indexOf('    function renderProviderConfiguration', start);
assert.ok(start >= 0 && end > start, 'renderer section is available');
const renderers = fullSource.slice(start, end) + '\nreturn { renderAssetReport };';
const providerName = provider => String(provider || 'Provider');
const safeText = value => String(value || '');
const safeProviderText = safeText;
const renderAssetReport = new Function('document', 'providerName', 'safeText', 'safeProviderText', renderers)(document, providerName, safeText, safeProviderText).renderAssetReport;
const walk = node => [node, ...node.children.flatMap(walk)];
const get = (root, predicate) => walk(root).find(predicate);
const report = {
  asset: { symbol: 'TST', name: 'Test asset' },
  as_of: '2026-02-01T00:00:00Z',
  sections: [{ key: 'snapshot', metrics: [
    { key: 'last_price', value: 0 }, { key: 'previous_close', value: 8 },
    { key: 'year_high', value: 12 }, { key: 'year_low', value: 5 },
  ] }, { key: 'valuation', metrics: [
    { key: 'pe_ratio', value: 10 }, { key: 'free_cash_flow_yield', value: 5 },
  ] }],
  price_history_total: 3,
  price_history: [
    { timestamp: '2026-01-01T00:00:00Z', close: 10 },
    { timestamp: '2026-01-02T00:00:00Z', close: 0 },
    { timestamp: '2026-01-10T00:00:00Z', close: 10 },
  ],
  key_findings: [{ id: 'f1', theme: 'price_action', evidence: { metric: 'last_price', current_value: 0, previous_value: 0, comparison_period: '1m' } }],
  risks: [{ finding_id: 'f1' }],
  earnings: [
    { period_end: '2025-09-30', reported_eps: 0, estimated_eps: -0.25 },
    { earnings_date: '2026-03-01', reported_eps: 4, estimated_eps: 5, status: 'scheduled' },
    { period_end: '2025-12-31', reported_eps: null, estimated_eps: 8 },
    { period_end: '2025-12-31', reported_eps: -1, estimated_eps: 0.5 },
    { period_end: '2025-12-31', reported_eps: 20, estimated_eps: null },
    { earnings_date: '2025-11-15', reported_eps: 1, estimated_eps: 1.25 },
  ],
  filings: [], news: [], sources: [], data_coverage: [],
};
const rendered = renderAssetReport({ reports: [report] });
const output = rendered.textContent;
assert.match(output, /Observed price0 \(currency unknown\)/);
assert.match(output, /Observed: 0 \(currency unknown\) · Comparison: 0 \(currency unknown\)/);
assert.match(output, /Previous close/);
assert.match(output, /52-week high/);
assert.match(output, /52-week low/);
assert.match(output, /P\/E ratio10x/);
assert.match(output, /Free Cash Flow Yield5%/);
assert.doesNotMatch(output, /Observed price\$0\.00/);

const chart = get(rendered, node => node.className === 'price-history-svg');
assert.ok(chart, 'multi-point history renders a price chart');
const line = get(chart, node => node.tagName === 'polyline');
const coords = line.attributes.points.split(' ').map(point => point.split(',').map(Number));
assert.equal(coords.length, 3);
assert.ok(Math.abs(coords[1][0] - (coords[0][0] + coords[2][0]) / 2) > 100, 'date spacing follows timestamps, not point indexes');
assert.ok(coords.every(point => Number.isFinite(point[1])), 'zero closing price remains a finite plotted observation');
const selected = get(rendered, node => node.className === 'chart-selection');
let prevented = false;
chart.listeners.keydown({ key: 'ArrowLeft', preventDefault: () => { prevented = true; } });
assert.ok(prevented);
assert.match(selected.textContent, /Closing price 0 currency unknown/);
assert.match(output, /0 selected observations|3 selected points/);

const eps = get(rendered, node => node.tagName === 'section' && get(node, child => child.tagName === 'h2')?.textContent === 'EPS actual vs estimate');
assert.ok(eps, 'EPS comparison section is rendered');
const rows = get(eps, node => node.tagName === 'tbody').children;
assert.equal(rows.length, 3, 'only same-record historical actual/estimate pairs are included');
assert.equal(rows[0].children[1].textContent, '0');
assert.equal(rows[0].children[2].textContent, '-0.25');
assert.equal(rows[1].children[1].textContent, '-1');
assert.equal(rows[1].children[2].textContent, '0.5');
assert.equal(rows[2].children[1].textContent, '1');
assert.equal(rows[2].children[2].textContent, '1.25');
assert.doesNotMatch(get(eps, node => node.className === 'eps-comparison-svg').textContent, /2026/);

const nullReport = { ...report, sections: [{ key: 'snapshot', metrics: [{ key: 'last_price', value: null }] }], price_history: [], earnings: [] };
const nullRendered = renderAssetReport({ reports: [nullReport] });
assert.match(nullRendered.textContent, /Observed priceNot available/);
assert.doesNotMatch(nullRendered.textContent, /Observed price0/);

const flatReport = { ...report, price_history: [
  { timestamp: '2026-01-01T00:00:00Z', close: 5 },
  { timestamp: '2026-01-02T00:00:00Z', close: 5 },
] };
const flatRendered = renderAssetReport({ reports: [flatReport] });
const flatLine = get(flatRendered, node => node.tagName === 'polyline');
assert.ok(flatLine);
const flatCoords = flatLine.attributes.points.split(' ').map(point => point.split(',').map(Number));
assert.equal(flatCoords[0][1], flatCoords[1][1], 'flat price history stays on a finite centered line');

const onePointReport = { ...report, price_history: [{ timestamp: '2026-01-01T00:00:00Z', close: 0 }] };
const onePointRendered = renderAssetReport({ reports: [onePointReport] });
assert.match(onePointRendered.textContent, /Insufficient closing-price observations for a line chart \(1 valid dated close\)/);
assert.equal(get(onePointRendered, node => node.tagName === 'polyline'), undefined, 'one point is not presented as a line chart');
"""


def _run_renderer_check(source_text: str | None = None) -> None:
    env = os.environ.copy()
    result = subprocess.run(
        [NODE, "-e", RENDERER_CHECK],
        cwd=ROOT,
        env=env,
        input=APP_JS.read_text(encoding="utf-8") if source_text is None else source_text,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not Path(NODE).is_file(), reason="Node.js is needed for renderer behavior checks")
def test_stock_report_renderer_preserves_real_zero_null_and_pairing_behavior() -> None:
    _run_renderer_check()

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
  get childElementCount() { return this.children.length; }
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
  asset: { symbol: 'TST', name: 'Test asset', currency: 'EUR' },
  as_of: '2026-02-01T00:00:00Z',
  sections: [{ key: 'snapshot', metrics: [
    { key: 'last_price', value: 0 }, { key: 'previous_close', value: 8 },
    { key: 'year_high', value: 12 }, { key: 'year_low', value: 5 },
  ] }, { key: 'valuation', metrics: [
    { key: 'pe_ratio', value: 10 }, { key: 'free_cash_flow_yield', value: 5 },
    { key: 'gross_margin', value: 0.74674004 }, { key: 'revenue_growth', value: 1.059 },
    { key: 'return_on_equity', value: 0.4, unit: '%' },
  ] }],
  fund_composition: {
    holdings: [
      { symbol: 'NVDA', name: 'NVIDIA Corporation', weight: '0.0836' },
      { symbol: 'MSFT', name: '<img src=x>', weight: 0.071 },
    ],
    sectors: [['technology', 0.4045]],
    as_of: null,
    provenance: { provider: 'yfinance', source_category: 'fund_composition', retrieved_at: '2026-02-01T12:00:00Z' },
    freshness: 'fresh',
    quality: { status: 'partial', warnings: ['Only provider top holdings are shown; this is not the complete portfolio. The portfolio observation date is unknown.'] },
  },
  price_history_total: 3,
  price_history: [
    { timestamp: '2026-01-01T00:00:00Z', close: 10 },
    { timestamp: '2026-01-02T00:00:00Z', close: 0 },
    { timestamp: '2026-01-10T00:00:00Z', close: 10.123456789 },
  ],
  key_findings: [
    { id: 'f1', theme: 'price_action', evidence: { metric: 'last_price', current_value: 0, previous_value: 0, comparison_period: '1m' } },
    { id: 'f2', theme: 'data_quality', finding_type: 'data_gap', metric: 'news', evidence: { metric: 'news', current_value: null, comparison_period: 'upstream_failure' }, quality: { status: 'partial', warnings: ['No provider is configured for this research section.'] } },
  ],
  risks: [{ finding_id: 'f1' }, { finding_id: 'rf_missing_1', metric: 'news', category: 'data_quality', evidence: [['direction', 'unknown'], ['finding_type', 'data_gap']] }],
  earnings: [
    { period_end: '2025-09-30', reported_eps: 0, estimated_eps: -0.25, reported_revenue: 125000 },
    { earnings_date: '2026-03-01', reported_eps: 4, estimated_eps: 5, status: 'scheduled' },
    { period_end: '2025-12-31', reported_eps: null, estimated_eps: 8 },
    { period_end: '2025-12-31', reported_eps: -1, estimated_eps: 0.5 },
    { period_end: '2025-12-31', reported_eps: 20, estimated_eps: null },
    { earnings_date: '2025-11-15', reported_eps: 1, estimated_eps: 1.25 },
  ],
  financial_history: [
    { statement_type: 'income_statement', period_end: '2025-12-31T00:00:00Z', period: 'annual', currency: 'USD', values: [['revenue', '1250000']] },
    { statement_type: 'income_statement', period_end: '2024-12-31T00:00:00Z', period: 'annual', currency: 'USD', values: [['revenue', '1000000']] },
  ],
  filings: [], news: [], sources: [], data_coverage: [
    { section: 'Fund Issuer', availability: 'missing', freshness: 'fresh', missing_fields: ['Distribution Frequency', 'Objective', 'Replication Method'] },
    { section: 'Crypto Market', availability: 'not_requested', freshness: 'unknown' },
  ],
};
const rendered = renderAssetReport({ reports: [report] });
const output = rendered.textContent;
assert.match(output, /Beobachtet: EUR 0\.00 · Vergleich: EUR 0\.00/);
assert.doesNotMatch(output, /VerfüGbar/, 'German characters are not split during title casing');
assert.match(output, /Schlusskurs zuvor/);
assert.match(output, /52-Wochen-Hoch/);
assert.match(output, /52-Wochen-Tief/);
assert.match(output, /Kurs-Gewinn-Verhältnis10×/);
assert.match(output, /Free-Cashflow-Rendite5 %/);
assert.match(output, /Bruttomarge74[,.]674 %/);
assert.match(output, /Umsatzwachstum105[,.]9 %/);
assert.match(output, /Eigenkapitalrendite0[,.]4 %/);
assert.match(output, /Währung unbekannt je Aktie/);
assert.match(output, /Gemeldeter Umsatz125['’]000 \(Währung unbekannt\)/);
assert.match(output, /Unternehmensnachrichten: keine Daten/);
assert.match(output, /Für diesen Abschnitt liegt kein verknüpfter Einzelbefund vor\./);
assert.match(output, /Schlusskurs EUR 10\.12/);
assert.match(output, /10\.123456789/, 'the exact-price disclosure retains the provider value');
assert.doesNotMatch(output, /rf_missing_1|Finding Type|direction unknown|data_gap/);
assert.doesNotMatch(output, /Beobachteter Wert nicht verfügbar/, 'data gaps are named by research section');
assert.match(output, /Fondsherausgeber · fehlend · aktuell/);
assert.match(output, /Fehlendes Feld: Ausschüttungsrhythmus/);
assert.match(output, /Krypto-Marktdaten · nicht angefragt · unbekannt/);
assert.doesNotMatch(output, /Distribution Frequency/);
assert.doesNotMatch(output, /Beobachtet: 0\s*\$0\.00/);

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
assert.match(selected.textContent, /Schlusskurs EUR 0\.00/);
assert.match(output, /0 ausgewählte Punkte|3 ausgewählte Punkte/);

const eps = get(rendered, node => node.tagName === 'section' && get(node, child => child.tagName === 'h2')?.textContent === 'Gewinn je Aktie: Ist und Schätzung');
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
const historyTable = get(rendered, node => node.tagName === 'table' && get(node, child => child.tagName === 'caption')?.textContent === 'Erfolgsrechnung');
assert.ok(historyTable, 'multi-year statement history appears in the expandable report details');
assert.match(historyTable.textContent, /2025/);
assert.match(historyTable.textContent, /2024/);
assert.match(historyTable.textContent, /\$|USD/);
const composition = get(rendered, node => node.className === 'fund-composition-disclosure');
assert.ok(composition, 'ETF holdings and sectors are available behind a compact disclosure');
assert.match(composition.textContent, /Grösste Positionen und Branchen/);
assert.match(composition.textContent, /NVDA/);
assert.match(composition.textContent, /8[.,]36 %/);
assert.match(composition.textContent, /40[.,]45 %/);
assert.match(composition.textContent, /Beobachtungsdatum unbekannt/);
assert.match(composition.textContent, /kein vollständiges Fondsportfolio/i);
assert.match(composition.textContent, /Regionen und Länder werden nicht aus den Positionen abgeleitet/);
assert.equal(get(composition, node => node.tagName === 'img'), undefined, 'provider names remain inert text');

const nullReport = { ...report, sections: [{ key: 'snapshot', metrics: [{ key: 'last_price', value: null }] }], price_history: [], earnings: [] };
const nullRendered = renderAssetReport({ reports: [nullReport] });
assert.match(nullRendered.textContent, /Letzter KursNicht verfügbar/);
assert.doesNotMatch(nullRendered.textContent, /Letzter Kurs0/);

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
assert.match(onePointRendered.textContent, /Zu wenige datierte Schlusskurse für ein Liniendiagramm \(1\)/);
assert.equal(get(onePointRendered, node => node.tagName === 'polyline'), undefined, 'one point is not presented as a line chart');

const fundReport = {
  ...report,
  asset: { symbol: 'FND', name: 'Fund', asset_type: 'etf', currency: 'EUR' },
  sections: [{ key: 'fund_characteristics', title: 'Fondseigenschaften', metrics: [
    { key: 'assets_under_management', value: 1000, unit: null },
    { key: 'nav', value: 100, unit: null },
    { key: 'expense_ratio', value: 0.0945, unit: '%' },
    { key: 'dividend_yield', value: 0.02, unit: null },
    { key: 'dividend_rate_ttm', value: 1.25, unit: 'unknown' },
  ] }],
  price_history: [],
  financial_history: [],
  earnings: [],
};
const fundOutput = renderAssetReport({ reports: [fundReport] }).textContent;
assert.match(fundOutput, /Währung unbekannt/);
assert.doesNotMatch(fundOutput, /1’000[,.]00 EUR/);
assert.match(fundOutput, /0[,.]0945 %/);
assert.match(fundOutput, /Dividendenrendite2 %/);
assert.match(fundOutput, /Dividendenbetrag \(12 Monate\)1[,.]25 \(Währung unbekannt\)/);

const cryptoReport = { ...report, asset: { symbol: 'BTC', asset_type: 'crypto' }, sections: [{ key: 'market_structure', metrics: [{ key: 'crypto_circulating_supply', value: 19, unit: 'asset units' }] }], price_history: [], financial_history: [], earnings: [], fund_composition: null };
assert.match(renderAssetReport({ reports: [cryptoReport] }).textContent, /Umlaufmenge19 Einheiten/);
const penceReport = { ...report, asset: { symbol: 'VOD.L', currency: 'GBp' }, sections: [{key:'snapshot', metrics:[{key:'last_price', value:119.8, unit:'GBp'}]}], price_history: [], financial_history: [], earnings: [], fund_composition: null };
const penceOutput = renderAssetReport({reports:[penceReport]}).textContent;
assert.match(penceOutput, /119[,.]8 GBp \(Pence\)/);
assert.doesNotMatch(penceOutput, /GBP|£119/);

const providerWarnings = [
  'No credentials-free installed provider is wired for this breakdown.',
  'Only provider top holdings are shown; this is not the complete portfolio. The portfolio observation date is unknown.',
  'fund_info data is partial.',
  'quote data is empty.',
];
const partialFund = { ...fundReport, is_partial: true, missing_essentials: [],
  warnings: providerWarnings,
  data_quality: { status: 'partial', availability: 'available', warnings: ['fund_info data is partial.'] },
  data_coverage: [
    { section: 'fund_info', availability: 'available', warnings: ['fund_info data is partial.'], missing_fields: ['benchmark', 'objective'] },
    { section: 'fund_geography', availability: 'not_supported', warnings: [providerWarnings[0]] },
  ],
};
const partialRendered = renderAssetReport({ reports: [partialFund] });
const riskSection = root => get(root, node => node.tagName === 'section' && node.children.some(child => child.tagName === 'h2' && child.textContent === 'Risiken und Datenqualität'));
const notices = riskSection(partialRendered);
assert.doesNotMatch(partialRendered.textContent, /Die Datenquelle meldet eine Einschränkung/);
assert.match(notices.textContent, /Teilbericht: Einige Angaben sind unvollständig oder nicht verfügbar\./);
assert.doesNotMatch(notices.textContent, /Wichtige Daten fehlen/, 'nonessential limitations do not imply missing essentials');
assert.match(notices.textContent, /Länder und Regionen:.*kostenlosen Datenquellen.*Aufschlüsselung nicht/);
assert.match(notices.textContent, /Nur die grössten Positionen.*vollständige Fondsportfolio.*Beobachtungsdatum.*unbekannt/);
assert.match(notices.textContent, /Fondsinformationen: Einige Angaben fehlen \(Referenzindex, Anlageziel\)\./);
assert.match(notices.textContent, /Aktueller Kurs: Die Datenquelle hat keine Daten geliefert\./);
assert.equal(notices.children.filter(node => node.className === 'quality-warning' && node.textContent.startsWith('Fondsinformationen:')).length, 1);
const geographyNotice = get(partialRendered, node => node.className === 'section-notice' && node.textContent.startsWith('Länder und Regionen'));
assert.match(geographyNotice.textContent, /kostenlosen Datenquellen.*Aufschlüsselung nicht/, 'coverage uses the same concrete explanation');

const unknownRendered = renderAssetReport({ reports: [{ ...partialFund,
  warnings: [...providerWarnings, 'Unexpected upstream response A.', 'Unexpected upstream response B.'],
}] });
const unknownNotices = riskSection(unknownRendered);
const unknownDetails = unknownNotices.children.filter(node => node.tagName === 'details');
assert.equal(unknownDetails.length, 1, 'unmapped notices share one disclosure');
assert.match(unknownDetails[0].textContent, /Weitere Quellenhinweise \(2\)/);
assert.match(unknownDetails[0].textContent, /Unexpected upstream response A/);
assert.match(unknownDetails[0].textContent, /Unexpected upstream response B/);

const essentialRendered = renderAssetReport({ reports: [{ ...partialFund,
  missing_essentials: ['fund_fee'],
  warnings: ['Report is partial because essential data is unavailable: fund_fee.'],
  data_quality: {},
}] });
assert.match(riskSection(essentialRendered).textContent, /Teilbericht: Wichtige Daten fehlen \(Fondsgebühren\)\./);
assert.equal(riskSection(essentialRendered).children.filter(node => node.className === 'quality-warning').length, 1, 'the derived essential warning is not repeated');

const issuerReport = { ...fundReport, sections: [{ key: 'fund_characteristics', metrics: [{key:'distribution_yield',value:0.99,unit:'%'}], details: [
  ['sponsor', 'Observed sponsor'], ['trustee', 'Observed trustee'],
  ['investment_geography', 'United States'], ['distribution_frequency', 'Quarterly'],
  ['nav_as_of', '2026-10-22T00:00:00Z'],
]}], fund_composition: { ...report.fund_composition,
  is_complete: true, as_of: '2026-10-22T00:00:00Z', sectors_as_of: '2026-10-22T00:00:00Z',
  provenance: { provider:'ssga', retrieved_at:'2026-10-25T00:00:00Z' },
  reference_url: 'https://www.ssga.com/observed-holdings.xlsx',
  holdings: Array.from({length:12}, (_,i) => ({symbol:'FULL'+i,name:'Holding '+i,weight:0.01})),
  quality: { status:'complete', warnings:[] },
} };
const issuerRendered = renderAssetReport({ reports:[issuerReport] });
const fullComposition = get(issuerRendered, node => node.className === 'fund-composition-disclosure');
assert.match(fullComposition.textContent, /Vollständige Positionsliste.*12 Positionen/);
assert.match(fullComposition.textContent, /FULL11/, 'issuer holdings are not truncated to ten positions');
assert.match(fullComposition.textContent, /22\. Okt\. 2026/);
assert.doesNotMatch(fullComposition.textContent, /Beobachtungsdatum unbekannt|höchstens zehn|kein vollständiges Fondsportfolio/);
assert.ok(get(fullComposition, node => node.tagName === 'a' && node.href === 'https://www.ssga.com/observed-holdings.xlsx'));
assert.match(issuerRendered.textContent, /SponsorObserved sponsor/);
assert.match(issuerRendered.textContent, /TreuhänderObserved trustee/);
assert.match(issuerRendered.textContent, /Anlageregion laut HerausgeberUnited States/);
assert.match(issuerRendered.textContent, /Ausschüttungsrhythmusquartalsweise/);
assert.match(issuerRendered.textContent, /Ausschüttungsrendite \(12 Monate\)0\.99 %/);
assert.match(issuerRendered.textContent, /Stand des Nettoinventarwerts22\. Okt\. 2026/);
const datedHeader = get(renderAssetReport({ reports:[{ ...issuerReport, as_of:'2026-10-25T00:00:00Z', price_as_of:'2026-10-23T20:00:00Z' }] }), node => node.className === 'report-header');
assert.match(datedHeader.textContent, /Stand 23\. Okt\. 2026/);
assert.doesNotMatch(datedHeader.textContent, /Stand 25\. Okt\. 2026/, 'new issuer metadata does not redate the price observation');
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


def test_stock_report_renderer_preserves_real_zero_null_and_pairing_behavior() -> None:
    assert Path(NODE).is_file(), "Node.js is required for renderer behavior checks"
    _run_renderer_check()

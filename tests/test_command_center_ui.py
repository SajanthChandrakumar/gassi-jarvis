"""Static contract tests for the dependency-free Command Center PWA."""

from pathlib import Path


UI_PATH = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"
STATIC = UI_PATH.parent
CSS_PATH = STATIC / "styles.css"
JS_PATH = STATIC / "app.js"


def _ui() -> str:
    parts = [UI_PATH.read_text(encoding="utf-8")]
    for path in (CSS_PATH, JS_PATH):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


def test_command_center_loads_separate_native_assets() -> None:
    ui = _ui()

    assert '<link rel="stylesheet" href="/static/styles.css?v=12">' in ui
    assert '<script src="/static/app.js?v=12" defer></script>' in ui
    assert "<style>" not in ui
    assert "<script>" not in ui
    assert CSS_PATH.is_file()
    assert JS_PATH.is_file()


def test_editorial_shell_prioritizes_research_command_and_useful_empty_state() -> None:
    ui = _ui()

    assert '<html lang="de">' in ui and "Was möchtest du untersuchen?" in ui
    for identifier in ("researchForm", "researchInput", "searchResults", "workspace", "researchFeed"):
        assert f'id="{identifier}"' in ui
    assert ui.index('id="researchForm"') < ui.index('id="workspace"')


def test_static_external_links_require_safe_new_tab_attributes() -> None:
    html = UI_PATH.read_text(encoding="utf-8")

    import re

    for link in re.findall(r"<a\b[^>]*target=\"_blank\"[^>]*>", html):
        assert 'rel="noopener noreferrer"' in link


def test_editorial_shell_removes_hud_and_decorative_patterns() -> None:
    ui, css = _ui(), _css()

    for stale in ("orb-shell", "orb-ring", "orb-core", "Jarvis research session", "Phase 7 · read-only research", "quality & provenance in response", "no investment advice", "Working method", "Read a result"):
        assert stale not in ui
        assert stale not in css
    assert "text-transform: uppercase" not in css
    assert "radial-gradient" not in css


def test_service_worker_versions_every_command_center_asset() -> None:
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")
    for path in ("/", "/static/styles.css?v=12", "/static/app.js?v=12"):
        assert repr(path) in worker or f'"{path}"' in worker


def test_service_worker_leaves_api_and_runtime_config_on_the_network() -> None:
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")

    assert "req.method !== 'GET' || url.pathname.startsWith('/api/')" in worker
    assert "url.pathname.startsWith('/api/')" in worker
    assert "config.js" not in worker


def test_service_worker_refreshes_static_assets_before_cache_fallback() -> None:
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")

    assert "caches.match(req).then((hit) => hit || fetch(req))" not in worker
    assert "fetch(req)" in worker
    assert ".then((response) =>" in worker
    assert "cache.put(req, response.clone())" in worker
    assert ".catch(() => caches.match(req))" in worker


def test_frontend_loads_runtime_config_before_app_and_uses_one_api_url_helper() -> None:
    html, js = UI_PATH.read_text(encoding="utf-8"), _js()

    assert '<script src="/config.js" defer></script>' in html
    assert html.index('/config.js') < html.index('/static/app.js')
    assert "function normalizeApiBase" in js
    assert "raw.includes('?')" in js
    assert "raw.includes('#')" in js
    assert "function apiUrl" in js
    assert "new URL(endpoint, API_BASE_URL + '/')" in js
    assert "function apiFetch" in js
    assert "fetch('/api/" not in js
    for endpoint in ("/api/chat", "/api/research/run", "/api/research/providers", "/api/research/macro"):
        assert f"apiFetch('{endpoint}'" in js


def test_frontend_exposes_structured_device_status_approval_and_result_polling() -> None:
    ui = _ui()

    for identifier in ("deviceState", "deviceLabel"):
        assert f'id="{identifier}"' in ui
    for name in ("loadDeviceStatus", "renderDeviceAction", "submitDeviceDecision", "pollDeviceAction"):
        assert f"function {name}" in ui
    assert "device_action" in ui
    assert "apiFetch('/api/device/status'" in ui
    assert "apiFetch('/api/device/actions/'" in ui
    assert "apiFetch('/api/device/actions/' + encodeURIComponent(actionId) + '/decision'" in ui
    for name in ("cancelDevicePolling", "cancelAllDevicePolling", "startDevicePolling"):
        assert f"function {name}" in ui
    assert "devicePolls" in ui
    assert "generation" in ui
    assert "DEVICE_POLL_RETRY_LIMIT" in ui
    assert "DEVICE_POLL_MAX_DURATION_MS" in ui
    assert "timed_out" in ui
    assert "Authorization required" in ui
    assert "state.retries < DEVICE_POLL_RETRY_LIMIT" in ui
    assert "state.retries = 0" in ui
    assert "Device action status is unavailable after repeated attempts." in ui
    assert "Device action status polling timed out." in ui
    assert "setTimeout(() => pollDeviceAction" in ui
    assert "/api/device-agent/" not in ui
    assert "cancelAllDevicePolling()" in ui
    assert "sessionId = newSession()" in ui


def test_asset_renderer_has_document_sections_and_compact_formatters() -> None:
    js = _js()

    for name in ("renderAssetReport", "renderAssetHeader", "renderPriceHistory", "renderMetricSections", "renderComparisonReport", "renderHistoricalReport", "renderRelationshipReport", "formatMoney", "formatCompact", "formatRatio", "formatPercent"):
        assert f"function {name}" in js
    for heading in ("Marktüberblick", "Kursverlauf", "Fundamentaldaten", "Bewertung"):
        assert heading in js


def test_report_renderer_exposes_filings_news_and_section_context() -> None:
    js = _js()

    for name in ("renderEarnings", "renderFilings", "renderDirectNews", "renderMacroContext", "renderProviderConfiguration", "renderContextPanel", "renderSectionNotice"):
        assert f"function {name}" in js
    for heading in ("Unternehmensmeldungen", "Unternehmensnachrichten", "Quellen", "Datenabdeckung"):
        assert heading in js
    assert "report.earnings" in js
    assert "item.unit" in js


def test_stock_report_preserves_currency_null_and_safe_link_states() -> None:
    js = _js()

    assert "function safeHttpUrl" in js
    assert "Währung unbekannt" in js
    assert "function formatMoney(value, currency)" in js
    assert "value === null || value === undefined || value === ''" in js
    assert "['http:', 'https:'].includes(url.protocol)" in js


def test_stock_report_chart_has_date_axes_accessible_selection_and_exact_data() -> None:
    js = _js()

    assert "function renderPriceHistory" in js
    assert "price_history_total" in js
    assert "role: 'group'" in js
    assert "aria-live" in js
    assert "ArrowLeft" in js and "ArrowRight" in js
    assert "Exakte Schlusskurse" in js
    assert "Zu wenige datierte Schlusskurse" in js
    assert "Für die Anzeige reduziert" in js


def test_stock_report_renders_ordered_findings_risk_links_and_coverage() -> None:
    js = _js()

    assert "function renderKeyFindings" in js
    assert "function renderRiskCoverage" in js
    assert "report.key_findings" in js
    assert "report.risks" in js
    assert "finding_id" in js
    assert "comparison_period" in js
    assert "retrieved_at" in js
    assert "missing_fields" in js
    assert "appendOriginalSourceText(notice, failure.message)" in js


def test_stock_report_limits_sources_and_pairs_eps_from_one_historical_observation() -> None:
    js = _js()

    assert "function renderEpsComparison" in js
    assert "reported_eps" in js and "estimated_eps" in js
    assert "period_end" in js and "earnings_date" in js
    assert "Gemeldeter Istwert" in js and "Schätzung der Quelle" in js
    assert "Keine passenden historischen Ist- und Schätzwerte verfügbar." in js
    assert "slice(0, 3)" in js and "slice(0, 5)" in js
    assert "function safeHttpUrl" in js


def test_stock_report_uses_disclosures_and_responsive_chart_support_layout() -> None:
    js, css = _js(), _css()

    assert "function renderMetricSections" in js
    assert "element('details'" in js
    assert ".report-grid" in css
    assert ".report-support" in css
    assert "@media (max-width: 680px)" in css


def test_ui_never_renders_raw_provider_plan_errors() -> None:
    js = _js()

    for stale in ("Premium Query Parameter", "subscription page", "financialmodelingprep.com"):
        assert stale not in js
    assert "function safeProviderText" in js
    assert "textContent = safeProviderText(text)" in js
    assert "appendOriginalSourceText(notice, failure.message)" in js


def test_command_center_has_command_first_prompt_and_research_modes() -> None:
    ui = _ui()

    assert 'id="jarvisCore"' in ui
    assert 'id="researchForm"' in ui
    assert 'id="researchInput"' in ui
    for label in ("Was möchtest du untersuchen?", "Aktie", "ETF", "Krypto", "Bericht erstellen", "Systemstatus und Mac-Status"):
        assert label in ui


def test_command_center_preserves_hands_free_voice_loop() -> None:
    ui = _ui()

    assert 'id="handsFreeBtn"' in ui
    assert "jarvis_handsfree" in ui
    assert "function tryAutoListen" in ui
    assert "if (!handsFree || speaking) return" in ui
    assert "tryAutoListen();" in ui


def test_research_requests_preserve_existing_chat_flow() -> None:
    ui = _ui()

    assert "apiFetch('/api/chat'" in ui
    assert "session_id: sessionId" in ui
    assert "finance_research:" in ui
    assert "hitl_pending" in ui
    assert "apiFetch('/api/research/run'" in ui
    assert "quality-warning" in ui
    assert "loadingResearch" in ui
    assert "answer-query" in ui
    assert "research_payload" in ui
    assert "renderResearchPayload" in ui
    assert "Kernbefunde" in ui
    assert "findings-list" in ui
    assert "PRESENTATION_LABELS" in ui
    assert "readableTimestamp" in ui
    assert "updateResearchAlerts" in ui
    assert 'id="alertsState"' in ui
    assert "Quellen und Datenabdeckung" in ui
    assert "Zuletzt abgerufen" in ui


def test_accessibility_and_responsive_motion_contracts_are_present() -> None:
    ui = _ui()

    assert "aria-live=\"polite\"" in ui
    assert "@media (max-width: 680px)" in ui
    assert "prefers-reduced-motion: reduce" in ui
    assert "focus-visible" in ui


def test_command_center_uses_opaque_solid_surfaces_not_glass_panels() -> None:
    ui = _ui()

    assert "--surface: #101418" in ui
    assert "--surface-raised: #161b20" in ui
    assert "background: var(--surface);" in ui
    assert "backdrop-filter" not in ui
    assert "radial-gradient" not in ui


def test_provider_status_is_explicit_and_does_not_expose_credentials() -> None:
    ui = _ui()

    assert "Datenabdeckung" in ui
    assert "loadProviderStatus" in ui
    assert "apiFetch('/api/research/providers'" in ui
    assert "Zugangsdaten werden nie angezeigt." in ui
    assert "configuration_state" in ui
    assert "Der Quellenstatus ist verfügbar, wenn Jarvis lokal läuft." in ui


def test_structured_reports_render_provider_backed_company_news() -> None:
    ui = _ui()

    assert "report.news" in ui
    assert "Unternehmensnachrichten" in ui
    assert "news-list" in ui
    assert "article.url" in ui


def test_command_center_loads_canonical_macro_context() -> None:
    ui = _ui()

    assert 'id="macroState"' in ui
    assert "loadMacroContext" in ui
    assert "apiFetch('/api/research/macro'" in ui
    assert "macro-grid" in ui
    assert "data.countries" in ui
    assert "macro-countries" in ui
    assert "macro-country" in ui
    assert "country.label" in ui
    assert "Zehnjahresrendite" in ui
    assert "Reales BIP-Wachstum" in ui
    assert "Makrodaten" in ui


def test_structured_reports_render_observed_report_metrics() -> None:
    ui = _ui()

    assert "report.sections" in ui
    assert "appendReportMetrics" in ui
    assert "metric-grid" in ui
    assert "Analystenschätzungen" in ui


def test_navigation_opens_validated_research_workflows_and_charts() -> None:
    ui = _ui()

    assert 'id="workflowPanel"' in ui
    assert 'id="workflowForm"' in ui
    assert 'id="workflowAsset"' in ui
    assert 'id="workflowBenchmark"' in ui
    assert "openWorkflow" in ui
    assert "apiFetch('/api/research/run'" in ui
    assert "appendPriceChart" in ui
    assert ".workflow-panel[hidden], .workflow-panel [hidden] { display: none; }" in ui
    assert "price-chart" in ui
    assert "data-future" not in ui


def test_local_watchlist_saved_research_and_exports_are_available() -> None:
    ui = _ui()

    assert 'id="watchlistState"' in ui
    assert 'id="savedResearchState"' in ui
    assert "WATCHLIST_KEY" in ui
    assert "SAVED_RESEARCH_KEY" in ui
    assert "saveResearchResult" in ui
    assert "renderSavedResearch" in ui
    assert "exportResearch" in ui
    assert "JSON exportieren" in ui
    assert "CSV exportieren" in ui
    assert "setTimeout(() => URL.revokeObjectURL(url), 1000)" in ui
    assert "format.toUpperCase() + '-Export vorbereitet.'" in ui
    assert "'statistical_result'" in ui
    assert "'historical_result'" in ui
    assert "appendResultActions(article, researchPayload, reportSelection, requestPayload)" in ui
    assert "Daten aktualisieren" in ui
    assert "renderWatchlist(); renderSavedResearch();" in ui

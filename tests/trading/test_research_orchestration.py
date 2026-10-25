"""Phase-7 controlled orchestration tests; all data stays provider-free."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.trading.research.canonical import AssetIdentity, AssetResearchData, CanonicalAssetType, DataQuality, FreshnessStatus, PriceBar, PriceSeries, QualityStatus, ResearchProvenance
from app.trading.research.orchestration import AssetResolver, RequestStatus, ResearchAnalysisType, ResearchIntent, ResearchOrchestrator, ResearchPlanner, ResearchRequest, parse_research_question, resolve_timeframe
from app.trading.research.reports import ReportMetric, ReportSection
from app.trading.research.jarvis_tools import crypto_asset_from_research_question

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def _data(symbol: str) -> AssetResearchData:
    asset_type = CanonicalAssetType.CRYPTO if symbol in {"BTC", "ETH"} else CanonicalAssetType.EQUITY
    asset = AssetIdentity(symbol, asset_type, currency="USD")
    prices = [Decimal("100")]
    for index in range(1, 40):
        prices.append(prices[-1] * (Decimal("1.01") if index % 3 else Decimal("0.995")))
    bars = tuple(PriceBar(NOW - timedelta(days=40 - index), value, value, value, value, Decimal("100")) for index, value in enumerate(prices))
    series = PriceSeries(asset, bars, "1d", "USD", ResearchProvenance("fixture", "price_history", NOW), bars[-1].timestamp, FreshnessStatus.FRESH, DataQuality(QualityStatus.COMPLETE))
    return AssetResearchData(asset, prices=series, quality=DataQuality(QualityStatus.COMPLETE))


class FakeCanonicalService:
    def __init__(self):
        self.calls = []

    def get_asset_research_data(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return _data(symbol)


def test_resolver_centralizes_defaults_and_surfaces_nasdaq_assumption():
    resolver = AssetResolver()
    apple = resolver.resolve("Apple")
    nasdaq = resolver.resolve("Nasdaq")
    assert apple.asset.symbol == "AAPL"
    assert nasdaq.asset.symbol == "QQQ"
    assert nasdaq.assumed_default is True
    assert "documented" in nasdaq.message


def test_planner_limits_statistical_request_to_prices_and_normalizes_timeframe():
    request = ResearchRequest(ResearchIntent.STATISTICAL_RELATIONSHIP, ("BTC", "QQQ"), timeframe="2y", analyses=(ResearchAnalysisType.CORRELATION,))
    plan = ResearchPlanner().plan(request)
    start, end = resolve_timeframe("2y")
    assert plan.sections == ("prices",)
    assert plan.timeframe_start == start and plan.timeframe_end == end


def test_asset_report_plan_requests_company_news():
    plan = ResearchPlanner().plan(ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("NVDA",)))

    assert plan.sections == (
        "quote", "prices", "profile", "fundamentals", "valuation",
        "earnings", "estimates", "filings", "news",
    )


def test_statistical_relationship_uses_deterministic_price_only_service():
    provider = FakeCanonicalService()
    response = ResearchOrchestrator(provider).execute(ResearchRequest(ResearchIntent.STATISTICAL_RELATIONSHIP, ("BTC", "QQQ"), timeframe="2y", analyses=(ResearchAnalysisType.CORRELATION,)))
    assert response.status is RequestStatus.SUCCESS
    assert response.statistical_results[0].context.observations >= 20
    assert all(call[1]["sections"] == ("prices",) for call in provider.calls)
    assert all(source.source_category == "price_history" for source in response.sources)


def test_history_routes_to_event_study_and_preserves_insufficient_sample_warning():
    provider = FakeCanonicalService()
    response = ResearchOrchestrator(provider).execute(ResearchRequest(ResearchIntent.HISTORICAL_ANALYSIS, ("BTC",), analyses=(ResearchAnalysisType.EVENT_STUDY,), parameters=(("lookback", "10"), ("horizons", "1,5"))))
    assert response.historical_results
    assert provider.calls[0][1]["sections"] == ("prices",)
    assert response.trace[-1].step == "historical_research"


def test_crypto_asset_report_requests_only_crypto_supported_sections():
    provider = FakeCanonicalService()

    response = ResearchOrchestrator(provider).execute(
        ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("ETH",))
    )

    assert response.status is RequestStatus.PARTIAL
    assert response.reports[0].is_partial is True
    assert provider.calls[0][1]["asset_type"] == "crypto"
    assert provider.calls[0][1]["sections"] == ("crypto",)


def test_ambiguous_asset_does_not_fetch_provider_data():
    provider = FakeCanonicalService()
    response = ResearchOrchestrator(provider).execute(ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("some company perhaps",)))
    assert response.status is RequestStatus.AMBIGUOUS
    assert provider.calls == []


def test_explicit_primary_and_benchmark_identity_reaches_canonical_service():
    provider = FakeCanonicalService()
    request = ResearchRequest(
        ResearchIntent.ASSET_COMPARISON,
        ("VWRL", "BTC-USD"),
        asset_type=CanonicalAssetType.ETF,
        exchange="XLON",
        currency="GBP",
        benchmark_asset_type=CanonicalAssetType.CRYPTO,
        benchmark_exchange="CRYPTO",
        benchmark_currency="USD",
        refresh=True,
    )

    response = ResearchOrchestrator(provider).execute(request)

    assert response.assets[0].asset == AssetIdentity("VWRL", CanonicalAssetType.ETF, exchange="XLON", currency="GBP")
    assert response.assets[1].asset == AssetIdentity("BTC-USD", CanonicalAssetType.CRYPTO, exchange="CRYPTO", currency="USD")
    assert provider.calls[0][1]["asset_type"] == "etf"
    assert provider.calls[0][1]["exchange"] == "XLON"
    assert provider.calls[0][1]["currency"] == "GBP"
    assert provider.calls[1][1]["asset_type"] == "crypto"
    assert provider.calls[1][1]["exchange"] == "CRYPTO"
    assert provider.calls[1][1]["currency"] == "USD"
    assert provider.calls[0][1]["refresh"] is True
    assert provider.calls[1][1]["refresh"] is True


def test_comparison_marks_different_monetary_currencies_incompatible_but_keeps_ratios():
    left = SimpleNamespace(
        asset=AssetIdentity("AAPL", CanonicalAssetType.EQUITY, currency="USD"),
        sections=(ReportSection("valuation", "Valuation", metrics=(
            ReportMetric("market_cap", Decimal("1000")),
            ReportMetric("pe_ratio", Decimal("20")),
        )),),
    )
    right = SimpleNamespace(
        asset=AssetIdentity("BMW", CanonicalAssetType.EQUITY, currency="EUR"),
        sections=(ReportSection("valuation", "Valuation", metrics=(
            ReportMetric("market_cap", Decimal("900")),
            ReportMetric("pe_ratio", Decimal("9")),
        )),),
    )

    comparison = ResearchOrchestrator._comparison(left, right)

    valuation = next(item for item in comparison.dimensions if item.category == "valuation")
    assert valuation.compatible is False
    assert "currency" in valuation.warning.lower()

    ratios = ResearchOrchestrator._comparison(
        SimpleNamespace(asset=left.asset, sections=(ReportSection("valuation", "Valuation", metrics=(ReportMetric("pe_ratio", Decimal("20")),)),)),
        SimpleNamespace(asset=right.asset, sections=(ReportSection("valuation", "Valuation", metrics=(ReportMetric("pe_ratio", Decimal("9")),)),)),
    )
    assert next(item for item in ratios.dimensions if item.category == "valuation").compatible is True


def test_comparison_marks_different_metric_periods_incompatible():
    left = SimpleNamespace(
        asset=AssetIdentity("AAPL", CanonicalAssetType.EQUITY, currency="USD"),
        sections=(ReportSection("growth", "Growth", metrics=(ReportMetric("revenue", Decimal("100"), period="annual"),)),),
    )
    right = SimpleNamespace(
        asset=AssetIdentity("MSFT", CanonicalAssetType.EQUITY, currency="USD"),
        sections=(ReportSection("growth", "Growth", metrics=(ReportMetric("revenue", Decimal("30"), period="quarterly"),)),),
    )

    comparison = ResearchOrchestrator._comparison(left, right)

    growth = next(item for item in comparison.dimensions if item.category == "growth")
    assert growth.compatible is False
    assert "period" in growth.warning.lower()


def test_comparison_includes_fund_fees_and_requires_dated_financial_periods():
    def report(symbol, section, metric):
        return SimpleNamespace(asset=AssetIdentity(symbol, CanonicalAssetType.ETF, currency="USD"),
            sections=(ReportSection(section, section, metrics=(metric,)),))
    comparison = ResearchOrchestrator._comparison(
        report("SPY", "fund_characteristics", ReportMetric("expense_ratio", Decimal("0.000945"), unit="%")),
        report("IVV", "fund_characteristics", ReportMetric("expense_ratio", Decimal("0.0003"), unit="%")),
    )
    fund = next(item for item in comparison.dimensions if item.category == "fund_characteristics")
    assert fund.compatible
    assert fund.left[0].value == Decimal("0.000945")
    financial = ResearchOrchestrator._comparison(
        report("AAA", "fundamentals", ReportMetric("revenue", Decimal("100"), unit="USD")),
        report("BBB", "fundamentals", ReportMetric("revenue", Decimal("200"), unit="USD")),
    )
    assert not next(item for item in financial.dimensions if item.category == "fundamentals").compatible


def test_same_symbol_comparison_preserves_two_distinct_listing_identities():
    request = ResearchRequest(
        ResearchIntent.ASSET_COMPARISON, ("ABC", "ABC"),
        asset_type=CanonicalAssetType.EQUITY, exchange="NYSE", currency="USD",
        benchmark_asset_type=CanonicalAssetType.EQUITY, benchmark_exchange="SIX", benchmark_currency="CHF",
    )
    assets = ResearchOrchestrator(FakeCanonicalService())._resolve_assets(request)
    assert len(assets) == 2
    assert assets[0].asset.exchange == "NYSE"
    assert assets[1].asset.exchange == "SIX"


def test_crypto_comparison_includes_market_structure_and_currency_checks():
    left = SimpleNamespace(asset=AssetIdentity("BTC-USD", CanonicalAssetType.CRYPTO),
        sections=(ReportSection("market_structure", "Market structure", metrics=(ReportMetric("crypto_market_cap", Decimal("100"), unit="USD"),)),))
    right = SimpleNamespace(asset=AssetIdentity("ETH-USD", CanonicalAssetType.CRYPTO),
        sections=(ReportSection("market_structure", "Market structure", metrics=(ReportMetric("crypto_market_cap", Decimal("90"), unit="EUR"),)),))
    dimension = next(item for item in ResearchOrchestrator._comparison(left, right).dimensions if item.category == "market_structure")
    assert not dimension.compatible
    assert dimension.left and dimension.right


def test_comparison_requires_known_financial_currency_but_uses_price_quote_currency():
    usd = AssetIdentity("AAA", CanonicalAssetType.EQUITY, currency="USD")
    left = SimpleNamespace(
        asset=usd,
        sections=(ReportSection("valuation", "Valuation", metrics=(
            ReportMetric("market_cap", Decimal("100"), unit="unknown"),
        )),),
    )
    right = SimpleNamespace(
        asset=AssetIdentity("BBB", CanonicalAssetType.EQUITY, currency="USD"),
        sections=(ReportSection("valuation", "Valuation", metrics=(
            ReportMetric("market_cap", Decimal("90"), unit="unknown"),
        )),),
    )

    valuation = next(
        item for item in ResearchOrchestrator._comparison(left, right).dimensions
        if item.category == "valuation"
    )
    assert valuation.compatible is False
    assert "unknown currencies" in valuation.warning

    quotes = ResearchOrchestrator._comparison(
        SimpleNamespace(asset=usd, sections=(ReportSection("market_behavior", "Market", metrics=(ReportMetric("last_price", Decimal("10")),)),)),
        SimpleNamespace(asset=right.asset, sections=(ReportSection("market_behavior", "Market", metrics=(ReportMetric("last_price", Decimal("12")),)),)),
    )
    assert next(item for item in quotes.dimensions if item.category == "market_behavior").compatible is True


def test_deterministic_parser_produces_bounded_beta_request():
    request = parse_research_question("Wie hoch ist NVDAs Beta zum Nasdaq über die letzten 2 Jahre?")
    assert request.intent is ResearchIntent.STATISTICAL_RELATIONSHIP
    assert request.analyses == (ResearchAnalysisType.BETA,)
    assert request.timeframe == "2y"


def test_crypto_performance_router_is_narrow_and_deterministic():
    assert crypto_asset_from_research_question("how is ETH the coin performing") == "ETH"
    assert crypto_asset_from_research_question("Bitcoin price research") == "BTC"
    assert crypto_asset_from_research_question("Tell me a joke about ETH") is None


def test_comparison_keeps_pence_distinct_from_pounds():
    left = SimpleNamespace(asset=AssetIdentity("VOD.L", CanonicalAssetType.EQUITY, currency="GBp"), sections=(ReportSection("market_behavior", "Market", metrics=(ReportMetric("last_price", Decimal("119.8")),)),))
    right = SimpleNamespace(asset=AssetIdentity("OTHER", CanonicalAssetType.EQUITY, currency="GBP"), sections=(ReportSection("market_behavior", "Market", metrics=(ReportMetric("last_price", Decimal("1.198")),)),))
    dimension = next(item for item in ResearchOrchestrator._comparison(left, right).dimensions if item.category == "market_behavior")
    assert not dimension.compatible


def test_crypto_token_counts_do_not_imply_cross_asset_supply_compatibility():
    def coin(symbol):
        return SimpleNamespace(asset=AssetIdentity(symbol, CanonicalAssetType.CRYPTO), sections=(ReportSection("market_structure", "Structure", metrics=(ReportMetric("crypto_total_supply", Decimal("100"), unit="asset units"),)),))
    dimension = next(item for item in ResearchOrchestrator._comparison(coin("BTC-USD"), coin("ETH-USD")).dimensions if item.category == "market_structure")
    assert not dimension.compatible

"""Phase-7 controlled orchestration tests; all data stays provider-free."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.trading.research.canonical import AssetIdentity, AssetResearchData, CanonicalAssetType, DataQuality, FreshnessStatus, PriceBar, PriceSeries, QualityStatus, ResearchProvenance
from app.trading.research.orchestration import AssetResolver, RequestStatus, ResearchAnalysisType, ResearchIntent, ResearchOrchestrator, ResearchPlanner, ResearchRequest, parse_research_question, resolve_timeframe
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

    assert response.status is RequestStatus.SUCCESS
    assert provider.calls[0][1]["asset_type"] == "crypto"
    assert provider.calls[0][1]["sections"] == ("crypto",)


def test_ambiguous_asset_does_not_fetch_provider_data():
    provider = FakeCanonicalService()
    response = ResearchOrchestrator(provider).execute(ResearchRequest(ResearchIntent.ASSET_ANALYSIS, ("some company perhaps",)))
    assert response.status is RequestStatus.AMBIGUOUS
    assert provider.calls == []


def test_deterministic_parser_produces_bounded_beta_request():
    request = parse_research_question("Wie hoch ist NVDAs Beta zum Nasdaq über die letzten 2 Jahre?")
    assert request.intent is ResearchIntent.STATISTICAL_RELATIONSHIP
    assert request.analyses == (ResearchAnalysisType.BETA,)
    assert request.timeframe == "2y"


def test_crypto_performance_router_is_narrow_and_deterministic():
    assert crypto_asset_from_research_question("how is ETH the coin performing") == "ETH"
    assert crypto_asset_from_research_question("Bitcoin price research") == "BTC"
    assert crypto_asset_from_research_question("Tell me a joke about ETH") is None

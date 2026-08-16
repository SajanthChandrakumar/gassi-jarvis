"""Small canonical Phase-3 fixtures; no live-provider data is used in unit tests."""

from datetime import datetime, timezone
from decimal import Decimal

from app.trading.research.canonical import (
    AssetIdentity,
    AssetResearchData,
    CanonicalAssetType,
    CryptoMarketData,
    DataQuality,
    FinancialStatement,
    FreshnessStatus,
    FundamentalsData,
    PriceBar,
    PriceSeries,
    QualityStatus,
    ResearchProvenance,
    StatementPeriod,
)


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)


def _provenance(category: str) -> ResearchProvenance:
    return ResearchProvenance("fixture", category, NOW)


def _prices(asset: AssetIdentity, closes, volumes, *, quality=QualityStatus.COMPLETE, freshness=FreshnessStatus.FRESH) -> PriceSeries:
    bars = tuple(
        PriceBar(datetime(2026, 8, index + 1, tzinfo=timezone.utc), value, value, value, value, volumes[index])
        for index, value in enumerate(closes)
    )
    return PriceSeries(asset, bars, "1d", "USD", _provenance("price_history"), bars[-1].timestamp, freshness, DataQuality(quality))


def _fundamentals(asset: AssetIdentity, *, quality=QualityStatus.COMPLETE, freshness=FreshnessStatus.FRESH) -> FundamentalsData:
    statements = []
    # Revenue accelerates; free cash flow falls despite revenue growth.
    for index, (revenue, operating_income, cash_flow) in enumerate(((Decimal("100"), Decimal("20"), Decimal("20")), (Decimal("110"), Decimal("25"), Decimal("18")), (Decimal("135"), Decimal("38"), Decimal("12")))):
        at = datetime(2026, 2 + index * 2, 1, tzinfo=timezone.utc)
        statements.extend((
            FinancialStatement("income", at, StatementPeriod.QUARTERLY, (("revenue", revenue), ("operating_income", operating_income), ("net_income", operating_income - Decimal("5")))),
            FinancialStatement("cash_flow", at, StatementPeriod.QUARTERLY, (("free_cash_flow", cash_flow), ("operating_cash_flow", cash_flow + Decimal("4")))),
        ))
    return FundamentalsData(asset, tuple(statements), _provenance("fundamentals"), statements[-1].period_end, freshness, DataQuality(quality))


def equity_growth_case() -> AssetResearchData:
    asset = AssetIdentity("GROW", CanonicalAssetType.EQUITY, currency="USD")
    return AssetResearchData(asset, prices=_prices(asset, [Decimal(value) for value in (100, 102, 103, 105, 108, 120)], [Decimal(value) for value in (100, 100, 105, 102, 100, 60)]), fundamentals=_fundamentals(asset), quality=DataQuality(QualityStatus.COMPLETE))


def equity_valuation_extreme_case() -> AssetResearchData:
    # Phase 2 exposes only a valuation snapshot: intentionally no historical valuation finding is expected.
    return equity_growth_case()


def equity_conflicting_signals_case() -> AssetResearchData:
    return equity_growth_case()


def crypto_price_volume_case() -> AssetResearchData:
    asset = AssetIdentity("BTC", CanonicalAssetType.CRYPTO, currency="USD")
    prices = _prices(asset, [Decimal(value) for value in (60000, 60500, 60800, 61000, 61500, 67000)], [Decimal(value) for value in (100, 100, 100, 100, 100, 55)])
    crypto = CryptoMarketData(asset, prices, None, None, None, prices.provenance, prices.freshness, prices.quality)
    return AssetResearchData(asset, crypto=crypto, quality=DataQuality(QualityStatus.COMPLETE))


def partial_data_case() -> AssetResearchData:
    asset = AssetIdentity("PART", CanonicalAssetType.EQUITY, currency="USD")
    prices = _prices(asset, [Decimal(value) for value in (10, 10, 10, 10, 10, 12)], [Decimal("10")] * 6, quality=QualityStatus.PARTIAL)
    return AssetResearchData(asset, prices=prices, quality=DataQuality(QualityStatus.PARTIAL))

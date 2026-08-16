from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.trading.research.cache import InMemoryResearchCache, ResearchCacheKey
from app.trading.research.canonical import (
    AssetIdentity,
    CanonicalAssetType,
    FreshnessStatus,
    QualityStatus,
)
from app.trading.research.freshness import FreshnessPolicy
from app.trading.research.normalizers import (
    NormalizationError,
    identity_from_profile,
    normalize_fundamentals,
    normalize_macro,
    normalize_price_data,
)
from app.trading.research.openbb_client import ResearchData, ResearchProviderError
from app.trading.research.serialization import canonical_json
from app.trading.research.service import CanonicalResearchService


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
ASSET = AssetIdentity("NVDA", CanonicalAssetType.EQUITY, currency="USD")


def _raw(category, rows, *, retrieved_at=NOW, provider="fake", **kwargs):
    return ResearchData(
        symbol=kwargs.pop("symbol", "NVDA"),
        asset_type=kwargs.pop("asset_type", "equity"),
        category=category,
        provider=provider,
        retrieved_at=retrieved_at,
        data=tuple(rows),
        **kwargs,
    )


def test_price_normalization_sorts_bars_and_keeps_zero_distinct_from_missing():
    raw = _raw("price_history", [
        {"date": "2026-08-02", "open": 2, "high": 3, "low": 1, "close": 0, "volume": None},
        {"date": "2026-08-01", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 10},
    ])

    series = normalize_price_data(raw, ASSET, interval="1d", now=NOW)

    assert [bar.timestamp.date() for bar in series.bars] == [date(2026, 8, 1), date(2026, 8, 2)]
    assert series.bars[1].close == Decimal("0")
    assert series.bars[1].volume is None
    assert series.quality.status is QualityStatus.PARTIAL
    assert "volume" in series.quality.missing_fields


def test_price_normalization_rejects_ambiguous_timestamps_and_represents_empty_data():
    invalid = _raw("price_history", [{"date": "2026-08-01T09:30:00", "open": 1, "high": 1, "low": 1, "close": 1}])
    with pytest.raises(NormalizationError, match="timezone"):
        normalize_price_data(invalid, ASSET)

    empty = normalize_price_data(_raw("price_history", []), ASSET)
    assert empty.bars == ()
    assert empty.quality.status is QualityStatus.EMPTY


def test_identity_and_fundamentals_are_provider_agnostic_with_period_semantics():
    profile = _raw("company_profile", [{"symbol": "nvda", "name": "NVIDIA", "issue_type": "EQUITY", "stock_exchange": "NMS", "currency": "USD", "cik": "1045810"}])
    identity = identity_from_profile(profile)
    annual = _raw("income_statement", [{"period_ending": "2025-01-31", "fiscal_period": "FY", "fiscal_year": 2025, "total_revenue": 100, "operating_income": 25, "net_income": 20}])
    quarterly = _raw("income_statement", [{"period_ending": "2025-04-30", "fiscal_period": "Q1", "fiscal_year": 2026, "total_revenue": 30, "operating_income": None, "net_income": 5}])

    fundamentals = normalize_fundamentals((("income", annual), ("income", quarterly)), identity, now=NOW)

    assert identity.symbol == "NVDA"
    assert identity.provider_identifiers == (("cik", "1045810"),)
    assert [statement.period.value for statement in fundamentals.statements] == ["annual", "quarterly"]
    assert dict(fundamentals.statements[0].values)["revenue"] == Decimal("100")
    assert dict(fundamentals.statements[1].values)["operating_income"] is None
    assert fundamentals.quality.status is QualityStatus.PARTIAL


def test_macro_provenance_as_of_and_serialization_are_deterministic():
    raw = _raw("macro_series", [{"date": "2026-01-01", "symbol": "CPIUS", "symbol_root": "CPI", "country": "United States", "value": 0, "unit": "index", "frequency": "month"}])
    macro = normalize_macro(raw, now=NOW)

    assert macro.provenance.provider == "fake"
    assert macro.provenance.retrieved_at == NOW
    assert macro.as_of == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert macro.observations[0].value == Decimal("0")
    assert canonical_json(macro) == canonical_json(macro)


def test_freshness_policy_and_cache_keys_do_not_hide_stale_or_collide():
    policy = FreshnessPolicy(category_ttls={"price_history": timedelta(minutes=5)})
    cache = InMemoryResearchCache[str]()
    first = ResearchCacheKey("NVDA", "price_history", "yfinance", (("start_date", "2026-01-01"),))
    different_provider = ResearchCacheKey("NVDA", "price_history", "fmp", (("start_date", "2026-01-01"),))
    different_range = ResearchCacheKey("NVDA", "price_history", "yfinance", (("start_date", "2026-02-01"),))
    cache.set(first, "value", retrieved_at=NOW)

    assert cache.get(different_provider, policy=policy, now=NOW) is None
    assert cache.get(different_range, policy=policy, now=NOW) is None
    assert cache.get(first, policy=policy, now=NOW).freshness is FreshnessStatus.FRESH
    assert cache.get(first, policy=policy, now=NOW + timedelta(minutes=6)) is None
    assert cache.get(first, policy=policy, now=NOW + timedelta(minutes=6), allow_stale=True).freshness is FreshnessStatus.STALE


class FakeResearchClient:
    def get_company_profile(self, symbol, *, provider=None):
        return _raw("company_profile", [{"symbol": symbol, "name": "NVIDIA", "issue_type": "EQUITY", "currency": "USD"}], provider=provider or "fake")

    def get_price_history(self, symbol, **kwargs):
        return _raw("price_history", [{"date": "2026-08-01", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}], provider=kwargs.get("provider") or "fake", symbol=symbol)

    def get_financial_statements(self, symbol, *, statement, provider=None, **kwargs):
        if statement == "balance":
            raise ResearchProviderError("Balance provider unavailable", provider=provider)
        fields = {"period_ending": "2026-01-31", "fiscal_period": "FY", "total_revenue": 10, "operating_income": 2, "net_income": 1}
        return _raw(f"{statement}_statement", [fields], provider=provider or "fake", symbol=symbol)


def test_aggregate_keeps_successful_sections_when_one_optional_fetch_fails():
    service = CanonicalResearchService(FakeResearchClient())

    aggregate = service.get_asset_research_data("NVDA", sections=("prices", "fundamentals"), now=NOW)

    assert aggregate.prices is not None
    assert aggregate.fundamentals is not None
    assert aggregate.quality.status is QualityStatus.PARTIAL
    assert aggregate.failures[0].section == "fundamentals.balance"
    assert aggregate.failures[0].code == "provider_error"


def test_service_refreshes_stale_cache_unless_stale_is_explicitly_allowed():
    class CountingClient(FakeResearchClient):
        price_calls = 0

        def get_price_history(self, symbol, **kwargs):
            self.price_calls += 1
            return super().get_price_history(symbol, **kwargs)

    client = CountingClient()
    service = CanonicalResearchService(
        client,
        freshness_policy=FreshnessPolicy(category_ttls={"price_history": timedelta(seconds=-1)}),
    )

    service.get_asset_research_data("NVDA", sections=("prices",))
    service.get_asset_research_data("NVDA", sections=("prices",))
    service.get_asset_research_data("NVDA", sections=("prices",), allow_stale=True)
    service.get_asset_research_data("NVDA", sections=("prices",), refresh=True)

    assert client.price_calls == 3

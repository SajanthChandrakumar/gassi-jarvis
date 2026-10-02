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
from app.trading.research import normalizers
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


def test_fundamentals_drop_empty_rows_and_measure_latest_valid_period():
    income = _raw("income_statement", [
        {
            "period_ending": "2026-01-31", "fiscal_period": "FY",
            "total_revenue": 100, "operating_income": 30, "net_income": 22,
        },
        {
            "period_ending": "2022-01-31", "fiscal_period": "FY",
            "total_revenue": None, "operating_income": None, "net_income": None,
        },
    ])

    result = normalize_fundamentals((("income", income),), ASSET, now=NOW)

    assert len(result.statements) == 1
    assert result.quality.status is QualityStatus.COMPLETE
    assert result.quality.missing_fields == ()


def test_sec_and_yahoo_balance_aliases_map_to_canonical_fields():
    raw = _raw("balance_statement", [{
        "period_ending": "2026-01-31", "fiscal_period": "FY",
        "total_assets": 120, "long_term_debt": 18,
        "cash_and_equivalents": 20, "common_stock_equity": 70,
    }], provider="sec")

    result = normalize_fundamentals((("balance", raw),), ASSET, now=NOW)

    assert dict(result.statements[0].values) == {
        "cash": Decimal("20"),
        "equity": Decimal("70"),
        "total_assets": Decimal("120"),
        "total_debt": Decimal("18"),
    }


def test_macro_provenance_as_of_and_serialization_are_deterministic():
    raw = _raw("macro_series", [{"date": "2026-01-01", "symbol": "CPIUS", "symbol_root": "CPI", "country": "United States", "value": 0, "unit": "index", "frequency": "month"}])
    macro = normalize_macro(raw, now=NOW)

    assert macro.provenance.provider == "fake"
    assert macro.provenance.retrieved_at == NOW
    assert macro.as_of == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert macro.observations[0].value == Decimal("0")
    assert canonical_json(macro) == canonical_json(macro)


def test_company_news_normalization_orders_articles_and_preserves_provenance():
    raw = _raw("company_news", [
        {"date": "2026-08-18T09:00:00+00:00", "title": "Older item", "excerpt": None, "url": "https://example.com/older"},
        {"date": "2026-08-19T14:30:00+00:00", "title": "Newer item", "excerpt": "Evidence only", "url": "https://example.com/newer"},
    ], provider="yfinance")

    news = normalizers.normalize_company_news(raw, ASSET, now=NOW)

    assert [article.title for article in news.articles] == ["Newer item", "Older item"]
    assert news.articles[0].published_at == datetime(2026, 8, 19, 14, 30, tzinfo=timezone.utc)
    assert news.provenance.provider == "yfinance"
    assert news.as_of == news.articles[0].published_at
    assert news.quality.status is QualityStatus.COMPLETE


def test_estimates_consensus_normalization_preserves_numeric_observations_only():
    raw = _raw("estimates_consensus", [{
        "symbol": "NVDA", "target_high": 250, "target_low": 140,
        "target_consensus": 210, "target_median": 215,
        "number_of_analysts": 42, "recommendation": "buy",
    }], provider="yfinance")

    estimates = normalizers.normalize_estimates(raw, ASSET, now=NOW)

    assert dict(estimates.metrics) == {
        "number_of_analysts": Decimal("42"), "target_consensus": Decimal("210"),
        "target_high": Decimal("250"), "target_low": Decimal("140"), "target_median": Decimal("215"),
    }
    assert estimates.provenance.provider == "yfinance"
    assert "recommendation" not in dict(estimates.metrics)


def test_quote_and_metrics_normalize_only_observed_values():
    quote = normalizers.normalize_equity_quote(_raw("equity_quote", [{
        "last_price": 216.61,
        "prev_close": 214.40,
        "year_high": 225,
        "year_low": 86,
        "volume": 12_000,
        "currency": "USD",
        "last_timestamp": "2026-08-20T15:59:00+00:00",
    }]), ASSET, now=NOW)
    valuation = normalizers.normalize_valuation_metrics(_raw("fundamental_metrics", [{
        "market_cap": 5_250_000_000_000,
        "pe_ratio": 31.8,
        "forward_pe": None,
        "ev_to_ebitda": 25.2,
    }]), ASSET, now=NOW)

    assert quote.last_price == Decimal("216.61")
    assert quote.previous_close == Decimal("214.40")
    assert quote.as_of == datetime(2026, 8, 20, 15, 59, tzinfo=timezone.utc)
    assert dict(valuation.metrics) == {
        "ev_to_ebitda": Decimal("25.2"),
        "market_cap": Decimal("5250000000000"),
        "pe_ratio": Decimal("31.8"),
    }
    assert valuation.quality.status is QualityStatus.COMPLETE


def test_actual_fmp_earnings_fields_normalize_without_inventing_actuals():
    result = normalizers.normalize_earnings(_raw("earnings_calendar", [{
        "symbol": "NVDA",
        "report_date": "2026-08-27",
        "eps_actual": None,
        "eps_consensus": 1.5,
        "revenue_actual": None,
        "revenue_consensus": 46_000_000_000,
        "last_updated": "2026-08-20",
    }], provider="fmp"), ASSET, now=NOW)

    observation = result.observations[0]
    assert observation.earnings_date.date() == date(2026, 8, 27)
    assert observation.estimated_eps == Decimal("1.5")
    assert observation.estimated_revenue == Decimal("46000000000")
    assert observation.reported_eps is None
    assert observation.reported_revenue is None


def test_sec_filings_keep_bounded_official_metadata():
    raw = _raw("company_filings", [
        {
            "report_type": "10-Q", "filing_date": "2026-05-21",
            "report_date": "2026-04-30", "primary_doc_description": "Quarterly report",
            "accession_number": "0001045810-26-000123",
            "report_url": "https://www.sec.gov/Archives/example.htm",
        },
        {
            "report_type": "S-8", "filing_date": "2026-05-20",
            "report_url": "https://www.sec.gov/Archives/ignored.htm",
        },
        {
            "report_type": "8-K", "filing_date": "2026-05-19",
            "report_url": "javascript:alert(1)",
        },
    ], provider="sec")

    filings = normalizers.normalize_filings(raw, ASSET, now=NOW)

    assert len(filings.items) == 1
    assert filings.items[0].form_type == "10-Q"
    assert filings.items[0].url == "https://www.sec.gov/Archives/example.htm"


def test_company_news_keeps_only_direct_company_mentions():
    raw = _raw("company_news", [
        {
            "date": "2026-08-20T12:00:00+00:00",
            "title": "Nvidia earnings approach", "summary": "NVDA demand remains in focus",
        },
        {
            "date": "2026-08-20T11:00:00+00:00",
            "title": "Why Lockheed Martin fell", "summary": "A defense-sector update",
        },
    ], provider="yfinance")

    filtered = normalizers.filter_company_news(
        raw,
        AssetIdentity("NVDA", CanonicalAssetType.EQUITY, name="NVIDIA Corporation"),
    )

    assert [row["title"] for row in filtered.data] == ["Nvidia earnings approach"]


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

    def get_equity_quote(self, symbol, **kwargs):
        return _raw("equity_quote", [{
            "last_price": 216.61, "prev_close": 214.40,
            "currency": "USD", "last_timestamp": "2026-08-20T15:59:00+00:00",
        }], provider=kwargs.get("provider") or "fake", symbol=symbol)

    def get_fundamental_metrics(self, symbol, **kwargs):
        return _raw("fundamental_metrics", [{
            "market_cap": 5_250_000_000_000, "pe_ratio": 31.8,
        }], provider=kwargs.get("provider") or "fake", symbol=symbol)

    def get_financial_statements(self, symbol, *, statement, provider=None, **kwargs):
        if statement == "balance":
            raise ResearchProviderError("Balance provider unavailable", provider=provider)
        fields = {"period_ending": "2026-01-31", "fiscal_period": "FY", "total_revenue": 10, "operating_income": 2, "net_income": 1}
        return _raw(f"{statement}_statement", [fields], provider=provider or "fake", symbol=symbol)

    def get_company_news(self, symbol, **kwargs):
        return _raw("company_news", [
            {
                "date": "2026-08-19T14:30:00+00:00",
                "title": "NVIDIA publishes quarterly results",
                "excerpt": "Evidence only",
                "url": "https://example.com/nvda-results",
            },
            {
                "date": "2026-08-18T14:30:00+00:00",
                "title": "Lockheed Martin updates guidance",
                "excerpt": "Defense-sector evidence",
                "url": "https://example.com/unrelated",
            },
        ], provider=kwargs.get("provider") or "yfinance", symbol=symbol)

    def get_company_filings(self, symbol, **kwargs):
        return _raw("company_filings", [{
            "report_type": "10-Q", "filing_date": "2026-05-21",
            "report_url": "https://www.sec.gov/Archives/example.htm",
        }], provider=kwargs.get("provider") or "sec", symbol=symbol)

    def get_estimates_consensus(self, symbol, **kwargs):
        return _raw("estimates_consensus", [{
            "symbol": symbol, "target_high": 250, "target_low": 140,
            "target_consensus": 210, "target_median": 215, "number_of_analysts": 42,
        }], provider=kwargs.get("provider") or "yfinance", symbol=symbol)

    def get_earnings_calendar(self, symbol, *, start_date=None, end_date=None, provider=None):
        return _raw("earnings_calendar", [{
            "symbol": symbol, "report_date": "2026-08-27", "eps_consensus": 1.5,
        }], provider=provider or "fmp", symbol=symbol, start_date=str(start_date), end_date=str(end_date))


def test_aggregate_keeps_successful_sections_when_one_optional_fetch_fails():
    service = CanonicalResearchService(FakeResearchClient())

    aggregate = service.get_asset_research_data("NVDA", sections=("prices", "fundamentals"), now=NOW)

    assert aggregate.prices is not None
    assert aggregate.fundamentals is not None
    assert aggregate.quality.status is QualityStatus.PARTIAL
    assert aggregate.failures[0].section == "fundamentals.balance"
    assert aggregate.failures[0].code == "provider_error"


def test_asset_aggregate_includes_requested_company_news():
    aggregate = CanonicalResearchService(FakeResearchClient()).get_asset_research_data(
        "NVDA", sections=("news",), now=NOW,
    )

    assert aggregate.news is not None
    assert aggregate.news.articles[0].title == "NVIDIA publishes quarterly results"
    assert aggregate.news.provenance.provider == "yfinance"
    assert len(aggregate.news.articles) == 1


def test_asset_aggregate_includes_recent_filings():
    aggregate = CanonicalResearchService(FakeResearchClient()).get_asset_research_data(
        "NVDA", sections=("filings",), now=NOW,
    )

    assert aggregate.filings.items[0].form_type == "10-Q"


def test_asset_aggregate_includes_supported_estimates_consensus():
    aggregate = CanonicalResearchService(FakeResearchClient()).get_asset_research_data(
        "NVDA", sections=("estimates",), now=NOW,
    )

    assert aggregate.estimates is not None
    assert aggregate.estimates.availability.value == "available"
    assert dict(aggregate.estimates.metrics)["target_consensus"] == Decimal("210")


def test_asset_aggregate_fetches_quote_and_valuation_independently_from_profile():
    aggregate = CanonicalResearchService(FakeResearchClient()).get_asset_research_data(
        "NVDA", sections=("quote", "valuation"), now=NOW,
    )

    assert aggregate.quote.last_price == Decimal("216.61")
    assert dict(aggregate.valuation.metrics)["market_cap"] == Decimal("5250000000000")


def test_asset_price_timeframe_is_not_forwarded_to_earnings_calendar():
    class RecordingClient(FakeResearchClient):
        def __init__(self):
            self.earnings_calls = []

        def get_earnings_calendar(self, symbol, *, start_date=None, end_date=None, provider=None):
            self.earnings_calls.append((symbol, start_date, end_date))
            return super().get_earnings_calendar(
                symbol, start_date=start_date, end_date=end_date, provider=provider,
            )

    client = RecordingClient()
    service = CanonicalResearchService(client)

    service.get_asset_research_data(
        "NVDA", sections=("earnings",), start_date="2025-08-20",
        end_date="2026-08-20", now=NOW,
    )

    assert client.earnings_calls == [("NVDA", date(2026, 8, 2), date(2026, 9, 15))]


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

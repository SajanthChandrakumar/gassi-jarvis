from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from app.trading.research.canonical import AssetIdentity, CanonicalAssetType
from app.trading.research.fund_composition import fetch_fund_composition, normalize_fund_composition


def test_free_fund_composition_preserves_observed_subset_and_weights(monkeypatch):
    calls = []
    def ticker(symbol, **kwargs):
        calls.append(symbol)
        assert kwargs["session"] is not None
        return SimpleNamespace(funds_data=SimpleNamespace(
            top_holdings=pd.DataFrame({"Name": ["NVIDIA", "Cash-like holding"], "Holding Percent": [0.0836, 0.0]}, index=["NVDA", "ZERO"]),
            sector_weightings={"technology": 0.4045},
        ))
    monkeypatch.setattr("yfinance.Ticker", ticker)
    raw = fetch_fund_composition("SPY")
    result = normalize_fund_composition(raw, AssetIdentity("SPY", CanonicalAssetType.ETF), now=raw.retrieved_at)

    assert calls == ["SPY"]
    assert result.holdings[0].weight == Decimal("0.0836")
    assert result.holdings[1].weight == Decimal("0.0")
    assert result.sectors == (("technology", Decimal("0.4045")),)
    assert result.as_of is None  # Fetch time is not a portfolio observation date.
    assert result.provenance.provider == "yfinance"
    assert result.quality.warnings  # This is a top-holdings subset, never a full portfolio.


def test_composition_rejects_invalid_weights_and_keeps_missing_sections(monkeypatch):
    monkeypatch.setattr("yfinance.Ticker", lambda _, **kwargs: SimpleNamespace(funds_data=SimpleNamespace(
        top_holdings=pd.DataFrame({"Name": ["Bad", "Missing"], "Holding Percent": [2.5, None]}, index=["BAD", "NONE"]),
        sector_weightings={},
    )))
    raw = fetch_fund_composition("SPY")
    result = normalize_fund_composition(raw, AssetIdentity("SPY", CanonicalAssetType.ETF))
    assert result.holdings == ()
    assert result.sectors == ()
    assert result.quality.status.value == "empty"


def test_provider_exception_is_a_safe_research_error(monkeypatch):
    def unavailable(_, **kwargs):
        raise RuntimeError("private upstream context")
    monkeypatch.setattr("yfinance.Ticker", unavailable)
    from app.trading.research.openbb_client import ResearchProviderError
    with pytest.raises(ResearchProviderError) as error:
        fetch_fund_composition("SPY")
    assert "private" not in error.value.public_message


def test_report_exposes_observed_holdings_without_claiming_full_portfolio(monkeypatch):
    from app.trading.research.canonical import AssetResearchData
    from app.trading.research.report_service import AssetResearchReportService
    from app.trading.research.relevance import ResearchRelevanceEngine
    monkeypatch.setattr("yfinance.Ticker", lambda _, **kwargs: SimpleNamespace(funds_data=SimpleNamespace(
        top_holdings=pd.DataFrame({"Name": ["NVIDIA"], "Holding Percent": [0.08]}, index=["NVDA"]),
        sector_weightings={"technology": 0.4},
    )))
    asset = AssetIdentity("SPY", CanonicalAssetType.ETF)
    composition = normalize_fund_composition(fetch_fund_composition("SPY"), asset)
    data = AssetResearchData(asset, fund_composition=composition)
    report = AssetResearchReportService().build_asset_report(research_data=data, analysis=ResearchRelevanceEngine().analyze(data))
    assert report.fund_composition == composition
    coverage = {item.section: item.availability.value for item in report.data_coverage}
    assert coverage["fund_holdings"] == coverage["fund_sectors"] == "available"
    assert coverage["fund_geography"] == "not_supported"
    assert any(source.source_category == "fund_composition" for source in report.sources)


def test_etf_profile_request_fetches_and_caches_composition(monkeypatch):
    from datetime import datetime, timezone
    from app.trading.research.openbb_client import ResearchData
    from app.trading.research.service import CanonicalResearchService
    calls = []
    class Client:
        def get_fund_info(self, symbol, **kwargs):
            return ResearchData(symbol, "etf", "etf_info", "yfinance", datetime.now(timezone.utc), ({"symbol": symbol, "name": "ETF"},))
        def get_fund_composition(self, symbol):
            calls.append(symbol)
            return ResearchData(symbol, "etf", "fund_composition", "yfinance", datetime.now(timezone.utc), ({"holdings": [{"symbol": "AAPL", "name": "Apple", "weight": 0.1}], "sectors": {}},))
    service = CanonicalResearchService(Client())
    first = service.get_asset_research_data("SPY", asset_type="etf", sections=("profile",))
    second = service.get_asset_research_data("SPY", asset_type="etf", sections=("profile",))
    assert first.fund_composition.holdings == second.fund_composition.holdings
    assert calls == ["SPY"]


def test_observed_quote_currency_enriches_identity_without_guessing_fund_asset_currency():
    from datetime import datetime, timezone
    from app.trading.research.openbb_client import ResearchData
    from app.trading.research.service import CanonicalResearchService
    class Client:
        def get_fund_info(self, symbol, **kwargs):
            return ResearchData(symbol, "etf", "etf_info", "yfinance", datetime.now(timezone.utc), ({"symbol": symbol, "name": "ETF", "total_assets": 1000},))
        def get_equity_quote(self, symbol, **kwargs):
            return ResearchData(symbol, "equity", "equity_quote", "yfinance", datetime.now(timezone.utc), ({"symbol": symbol, "currency": "USD", "previous_close": 10},))
    data = CanonicalResearchService(Client()).get_asset_research_data("SPY", asset_type="etf", sections=("profile", "quote"))
    assert data.asset.currency == "USD"
    assert data.quote.asset == data.asset == data.fund_profile.asset
    assert data.fund_profile.assets_under_management_currency is None


def test_issuer_profile_and_full_holdings_replace_incomplete_yahoo_sections_and_cache():
    from datetime import datetime, timezone
    from app.trading.research.openbb_client import ResearchData
    from app.trading.research.service import CanonicalResearchService
    from app.trading.research.report_service import AssetResearchReportService
    from app.trading.research.relevance import ResearchRelevanceEngine
    from app.trading.research.canonical import ProviderAttempt
    calls = []
    stamp = datetime.now(timezone.utc)
    class Client:
        def get_fund_info(self, symbol, **kwargs):
            return ResearchData(symbol, "etf", "etf_info", "yfinance", stamp, ({"symbol": symbol, "name": "ETF", "dividend_yield_ttm": "0.02", "dividend_rate_ttm": "4.5"},), attempts=(ProviderAttempt("yfinance", "success"),))
        def get_issuer_fund_data(self, symbol):
            calls.append(symbol)
            return ResearchData(symbol, "etf", "issuer_fund_data", "ssga", stamp, ({
                "symbol": symbol, "name": "Issuer fund", "currency": "USD",
                "benchmark": "Observed index", "objective": "Observed investment objective",
                "distribution_frequency": "Quarterly", "sponsor": "Observed sponsor",
                "trustee": "Observed trustee", "investment_geography": "United States",
                "assets_under_management": 1000, "assets_under_management_currency": "USD",
                "assets_under_management_as_of": "2026-10-22", "nav": 100, "nav_currency": "USD",
                "nav_as_of": "2026-10-22", "as_of": "2026-10-25",
                "distribution_yield": "0.0099", "distribution_yield_as_of": "2026-10-22",
                "expense_ratio": "0.000945", "website": "https://www.ssga.com/observed-fund",
                "holdings": [{"symbol": "AAPL", "name": "Apple", "weight": "0.1"}],
                "holdings_as_of": "2026-10-22", "holdings_complete": True,
                "sectors": {"Technology": "0.1"}, "sectors_as_of": "2026-10-22",
                "holdings_url": "https://www.ssga.com/observed-holdings.xlsx",
            },))
        def get_fund_composition(self, symbol):
            raise AssertionError("Do not refetch Yahoo's subset when full issuer holdings arrived")
    service = CanonicalResearchService(Client())
    data = service.get_asset_research_data("SPY", asset_type="etf", sections=("profile",))
    second = service.get_asset_research_data("SPY", asset_type="etf", sections=("profile",))
    assert calls == ["SPY"]
    fund = data.fund_profile
    assert fund.provenance.provider == "ssga"
    assert any(attempt.provider == "yfinance" for attempt in fund.provenance.attempts)
    assert fund.benchmark == "Observed index"
    assert fund.sponsor == "Observed sponsor" and fund.issuer is None
    assert fund.trustee == "Observed trustee"
    assert fund.investment_geography == "United States"
    assert fund.assets_under_management_currency == fund.nav_currency == "USD"
    assert fund.nav_as_of == datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert fund.distribution_yield == Decimal("0.0099")
    assert fund.distribution_yield_as_of == datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert fund.replication_method is None
    assert data.fund_composition.is_complete
    assert second.fund_composition == data.fund_composition
    assert data.fund_composition.as_of == datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert data.fund_composition.provenance.provider == "ssga"
    assert not any("top holdings" in warning for warning in data.fund_composition.quality.warnings)
    report = AssetResearchReportService().build_asset_report(research_data=data, analysis=ResearchRelevanceEngine().analyze(data))
    section = next(item for item in report.sections if item.key == "fund_characteristics")
    assert dict(section.details)["sponsor"] == "Observed sponsor"
    coverage = {item.section: item.availability.value for item in report.data_coverage}
    assert coverage["fund_benchmark"] == coverage["fund_distribution"] == "available"
    assert coverage["fund_investment_geography"] == "available"
    assert coverage["fund_geography"] == "not_supported"  # Classification is not a country-weight table.
    assert data.fund_profile_secondary.provenance.provider == "yfinance"
    assert report.fund_profile_secondary.dividend_yield_ttm == Decimal("0.02")
    extra = next(item for item in report.sections if item.key == "fund_provider_observations")
    assert extra.provenance[0].provider == "yfinance"
    assert any(item.key == "dividend_rate_ttm" and item.value == Decimal("4.5") for item in extra.metrics)


def test_issuer_failure_preserves_yahoo_data_and_reports_failure():
    from datetime import datetime, timezone
    from app.trading.research.openbb_client import ResearchData, ResearchProviderError
    from app.trading.research.service import CanonicalResearchService
    class Client:
        def get_fund_info(self, symbol, **kwargs):
            return ResearchData(symbol, "etf", "etf_info", "yfinance", datetime.now(timezone.utc), ({"symbol": symbol, "name": "ETF"},))
        def get_issuer_fund_data(self, symbol):
            raise ResearchProviderError("Unavailable", provider="ssga")
    data = CanonicalResearchService(Client()).get_asset_research_data("SPY", asset_type="etf", sections=("profile",))
    assert data.fund_profile.provenance.provider == "yfinance"
    assert any(item.section == "issuer_fund_data" and item.provider == "ssga" for item in data.failures)


def test_dropped_invalid_issuer_positions_cannot_be_marked_complete():
    from datetime import datetime, timezone
    from app.trading.research.openbb_client import ResearchData
    raw = ResearchData("SPY", "etf", "issuer_fund_data", "ssga", datetime.now(timezone.utc), ({
        "holdings": [{"symbol": "VALID", "weight": "0.1"}, {"symbol": "BAD", "weight": "1.5"}],
        "holdings_as_of": "2026-10-22", "holdings_complete": True,
        "sectors": {},
    },))
    composition = normalize_fund_composition(raw, AssetIdentity("SPY", CanonicalAssetType.ETF))
    assert not composition.is_complete
    assert composition.as_of is not None
    assert not any("date is unknown" in warning for warning in composition.quality.warnings)

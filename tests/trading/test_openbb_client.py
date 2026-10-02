from datetime import date, datetime, timezone
import os
from types import SimpleNamespace

import pytest

from app.trading.research import (
    AssetIdentity,
    CanonicalAssetType,
    OpenBBResearchClient,
    ResearchInvalidSymbolError,
    ResearchMissingCredentialError,
    ResearchNoDataError,
    ResearchProviderSettings,
    ResearchRateLimitError,
)
from app.trading.research.normalizers import normalize_price_data
from app.trading.research.openbb_client import _configure_tls_ca_bundle


class FakeRow:
    def __init__(self, **values):
        self.values = values

    def model_dump(self, mode: str):
        assert mode == "json"
        return self.values


class FakeResult:
    def __init__(self, rows, provider="fake", warnings=None):
        self.results = rows
        self.provider = provider
        self.warnings = warnings


def _fake_openbb(**endpoints):
    return SimpleNamespace(
        equity=SimpleNamespace(
            price=SimpleNamespace(
                historical=endpoints.get("equity_price"),
                quote=endpoints.get("quote"),
            ),
            profile=endpoints.get("profile"),
            fundamental=SimpleNamespace(
                income=endpoints.get("income"),
                balance=endpoints.get("balance"),
                cash=endpoints.get("cash"),
                metrics=endpoints.get("metrics"),
                filings=endpoints.get("filings"),
            ),
            calendar=SimpleNamespace(earnings=endpoints.get("earnings")),
            estimates=SimpleNamespace(consensus=endpoints.get("estimates_consensus")),
        ),
        crypto=SimpleNamespace(price=SimpleNamespace(historical=endpoints.get("crypto_price"))),
        news=SimpleNamespace(company=endpoints.get("company_news")),
        economy=SimpleNamespace(indicators=endpoints.get("macro"), fred_series=endpoints.get("fred_series")),
    )


def _client(**endpoints):
    return OpenBBResearchClient(
        _fake_openbb(**endpoints),
        ResearchProviderSettings(
            price=("equity-default",), quote=("equity-default",),
            profile=("equity-default",), statements=("equity-default",),
            metrics=("equity-default",), news=("news-default",),
            estimates=("estimates-default",), earnings=("fmp",), filings=("sec",),
            crypto=("crypto-default",), macro=("macro-default",),
        ),
    )


def test_equity_price_history_preserves_provider_data_and_forwards_parameters():
    captured = {}

    def historical(**kwargs):
        captured.update(kwargs)
        return FakeResult([FakeRow(date=date(2026, 8, 1), open=10, high=12, low=9, close=11, volume=42)])

    result = _client(equity_price=historical).get_price_history(
        "NVDA", start_date=date(2026, 8, 1), end_date="2026-08-08", interval="1d", provider="yfinance"
    )

    assert captured == {
        "symbol": "NVDA", "start_date": "2026-08-01", "end_date": "2026-08-08", "interval": "1d", "provider": "yfinance"
    }
    assert result.provider == "fake"
    assert result.category == "price_history"
    assert result.data[0]["date"] == "2026-08-01"
    assert result.data[0]["volume"] == 42


def test_equity_price_history_ignores_removed_credentials_and_uses_fmp_fallback(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "configured")
    monkeypatch.setenv("TIINGO_TOKEN", "obsolete")
    monkeypatch.setenv("BENZINGA_API_KEY", "obsolete")
    providers = []

    def historical(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "yfinance":
            return FakeResult([], provider="yfinance")
        assert kwargs["provider"] == "fmp"
        return FakeResult([FakeRow(date=date(2026, 8, 1), close=11)], provider="fmp")

    client = OpenBBResearchClient(
        _fake_openbb(equity_price=historical),
        ResearchProviderSettings.from_environment(),
    )
    result = client.get_price_history("NVDA")

    assert providers == ["yfinance", "fmp"]
    assert result.provider == "fmp"
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("yfinance", "failure", "no_data"),
        ("fmp", "success", None),
    ]


def test_default_provider_chain_records_attempts_and_preserves_them_in_provenance():
    providers = []

    def historical(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "yfinance":
            return FakeResult([], provider="yfinance")
        return FakeResult([FakeRow(date="2026-08-20", close=10)], provider="fmp")

    client = OpenBBResearchClient(
        _fake_openbb(equity_price=historical),
        ResearchProviderSettings(price=("yfinance", "fmp")),
    )

    result = client.get_price_history("NVDA")
    normalized = normalize_price_data(
        result,
        AssetIdentity("NVDA", CanonicalAssetType.EQUITY, currency="USD"),
        now=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert providers == ["yfinance", "fmp"]
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("yfinance", "failure", "no_data"),
        ("fmp", "success", None),
    ]
    assert normalized.provenance.attempts == result.attempts


def test_explicit_provider_does_not_fall_through_the_default_chain():
    providers = []

    def historical(**kwargs):
        providers.append(kwargs["provider"])
        return FakeResult([], provider=kwargs["provider"])

    client = OpenBBResearchClient(
        _fake_openbb(equity_price=historical),
        ResearchProviderSettings(price=("yfinance", "fmp")),
    )

    with pytest.raises(ResearchNoDataError):
        client.get_price_history("NVDA", provider="yfinance")

    assert providers == ["yfinance"]


def test_provider_plan_errors_map_to_a_stable_public_message():
    error = OpenBBResearchClient._map_openbb_error(
        RuntimeError("402 Premium Query Parameter: upgrade at https://provider.invalid/plan"),
        "fmp",
    )

    assert error.code == "entitlement_required"
    assert error.public_message == "This data is not included in the configured FMP tier."
    assert "http" not in error.public_message


def test_provider_result_warnings_do_not_expose_subscription_details():
    client = OpenBBResearchClient(_fake_openbb(
        equity_price=lambda **_: FakeResult(
            [FakeRow(date="2026-08-20", close=10)],
            warnings=["402 Premium endpoint: https://provider.invalid/upgrade"],
        )
    ))

    result = client.get_price_history("NVDA")

    assert result.warnings == ("Provider returned a restricted-data warning.",)


def test_openbb_uses_the_virtual_environment_ca_bundle_when_unset(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    _configure_tls_ca_bundle()

    assert os.environ["SSL_CERT_FILE"].endswith("certifi/cacert.pem")


def test_company_news_preserves_articles_and_forwards_bounded_request():
    captured = {}

    def company_news(**kwargs):
        captured.update(kwargs)
        return FakeResult([
            FakeRow(
                date="2026-08-19T14:30:00+00:00",
                title="NVIDIA publishes quarterly results",
                excerpt="Revenue increased during the quarter.",
                url="https://example.com/nvda-results",
            )
        ], provider="yfinance")

    result = _client(company_news=company_news).get_company_news(
        "NVDA", start_date="2026-08-01", end_date="2026-08-20", limit=8,
        provider="yfinance",
    )

    assert captured == {
        "symbol": "NVDA", "start_date": "2026-08-01", "end_date": "2026-08-20",
        "limit": 8, "provider": "yfinance",
    }
    assert result.category == "company_news"
    assert result.provider == "yfinance"
    assert result.data[0]["title"] == "NVIDIA publishes quarterly results"


def test_quote_and_metrics_use_dedicated_routes():
    quote_args = {}
    metric_args = {}

    def quote(**kwargs):
        quote_args.update(kwargs)
        return FakeResult([FakeRow(
            symbol="NVDA", last_price=216.61, prev_close=214.40,
            year_high=225, year_low=86, currency="USD",
        )], provider="yfinance")

    def metrics(**kwargs):
        metric_args.update(kwargs)
        return FakeResult([FakeRow(
            symbol="NVDA", market_cap=5_250_000_000_000,
            pe_ratio=31.8, forward_pe=28.1,
        )], provider="fmp")

    client = _client(quote=quote, metrics=metrics)

    assert client.get_equity_quote("NVDA", provider="yfinance").category == "equity_quote"
    assert client.get_fundamental_metrics("NVDA", provider="fmp").category == "fundamental_metrics"
    assert quote_args == {"symbol": "NVDA", "provider": "yfinance"}
    assert metric_args == {"symbol": "NVDA", "provider": "fmp"}


def test_company_news_falls_back_to_yfinance_when_configured_default_is_empty():
    providers = []

    def company_news(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "empty-news-provider":
            return FakeResult([], provider="empty-news-provider")
        return FakeResult([FakeRow(date="2026-08-19T14:30:00+00:00", title="Fallback item")], provider="yfinance")

    client = OpenBBResearchClient(
        _fake_openbb(company_news=company_news),
        ResearchProviderSettings(news=("empty-news-provider", "yfinance")),
    )
    result = client.get_company_news("NVDA", limit=3)

    assert providers == ["empty-news-provider", "yfinance"]
    assert result.provider == "yfinance"
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("empty-news-provider", "failure", "no_data"),
        ("yfinance", "success", None),
    ]


def test_estimates_consensus_falls_back_and_preserves_observed_fields():
    providers = []

    def consensus(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "fmp":
            raise RuntimeError("402 restricted endpoint")
        return FakeResult([FakeRow(
            symbol="NVDA", target_high=250, target_low=140,
            target_consensus=210, target_median=215, number_of_analysts=42,
            recommendation="buy",
        )], provider="yfinance")

    client = OpenBBResearchClient(
        _fake_openbb(estimates_consensus=consensus),
        ResearchProviderSettings(estimates=("fmp", "yfinance")),
    )
    result = client.get_estimates_consensus("NVDA")

    assert providers == ["fmp", "yfinance"]
    assert result.category == "estimates_consensus"
    assert result.provider == "yfinance"
    assert result.data[0]["target_consensus"] == 210
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("fmp", "failure", "entitlement_required"),
        ("yfinance", "success", None),
    ]


def test_crypto_and_macro_use_their_own_openbb_routes_and_default_providers():
    crypto_args = {}
    macro_args = {}

    def crypto(**kwargs):
        crypto_args.update(kwargs)
        return FakeResult([FakeRow(symbol="BTC-USD", close=100_000, volume=10)])

    def macro(**kwargs):
        macro_args.update(kwargs)
        return FakeResult([FakeRow(symbol="CPI", value=3.1)])

    client = _client(crypto_price=crypto, macro=macro)
    crypto_result = client.get_price_history("BTC-USD", asset_type="crypto")
    macro_result = client.get_macro_series("CPI", country="switzerland", frequency="month")

    assert crypto_args["provider"] == "crypto-default"
    assert macro_args["provider"] == "macro-default"
    assert macro_args["country"] == "switzerland"
    assert crypto_result.asset_type == "crypto"
    assert macro_result.asset_type == "macro"


def test_fred_macro_uses_series_route_and_preserves_canonical_indicator():
    captured = {}

    def fred_series(**kwargs):
        captured.update(kwargs)
        return FakeResult([FakeRow(date="2026-07-01", CPIAUCSL=2.7)], provider="fred")

    result = _client(fred_series=fred_series).get_macro_series(
        "CPI", start_date="2025-01-01", end_date="2026-08-20", provider="fred",
    )

    assert captured == {
        "symbol": "CPIAUCSL", "start_date": "2025-01-01", "end_date": "2026-08-20", "provider": "fred",
    }
    assert result.symbol == "CPI"
    assert result.provider == "fred"
    assert result.category == "macro_series"
    assert result.data[0]["value"] == 2.7


def test_fred_macro_preserves_transform_unit_and_request_provenance():
    captured = {}

    def fred_series(**kwargs):
        captured.update(kwargs)
        return FakeResult([FakeRow(date="2026-07-01", CPIAUCSL=2.7)], provider="fred")

    result = _client(fred_series=fred_series).get_macro_series(
        "inflation",
        series_id="CPIAUCSL",
        transform="pc1",
        unit="% YoY",
        provider="fred",
    )

    assert captured == {"symbol": "CPIAUCSL", "transform": "pc1", "provider": "fred"}
    assert result.data[0]["value"] == 2.7
    assert result.data[0]["unit"] == "% YoY"
    assert dict(result.request_parameters) == {
        "series_id": "CPIAUCSL", "transform": "pc1", "unit": "% YoY",
    }


def test_canonical_crypto_symbols_use_yfinance_usd_pairs_without_changing_identity():
    crypto_args = {}

    def crypto(**kwargs):
        crypto_args.update(kwargs)
        return FakeResult([FakeRow(symbol="BTC-USD", close=100_000, volume=10)])

    client = _client(crypto_price=crypto)
    result = client.get_price_history("BTC", asset_type="crypto", provider="yfinance")

    assert crypto_args["symbol"] == "BTC-USD"
    assert result.symbol == "BTC"


def test_empty_upstream_result_is_not_silently_converted_to_an_empty_list():
    with pytest.raises(ResearchNoDataError) as error:
        _client(profile=lambda **_: FakeResult([])).get_company_profile("MISSING")

    assert error.value.provider == "fake"


def test_provider_errors_map_to_clear_domain_errors():
    def missing_key(**_):
        raise RuntimeError("Provider requires an API key credential")

    def rate_limited(**_):
        raise RuntimeError("429 rate limit exceeded")

    def invalid_symbol(**_):
        raise RuntimeError("Invalid symbol: NO_SUCH_TICKER")

    with pytest.raises(ResearchMissingCredentialError):
        _client(profile=missing_key).get_company_profile("NVDA", provider="fmp")
    with pytest.raises(ResearchRateLimitError):
        _client(profile=rate_limited).get_company_profile("NVDA", provider="fmp")
    with pytest.raises(ResearchInvalidSymbolError):
        _client(profile=invalid_symbol).get_company_profile("NO_SUCH_TICKER")


def test_statement_selection_calls_the_requested_openbb_endpoint():
    called = []

    def balance(**kwargs):
        called.append(kwargs)
        return FakeResult([FakeRow(total_assets=100)])

    result = _client(balance=balance).get_financial_statements("NVDA", statement="balance", limit=2)

    assert called == [{"symbol": "NVDA", "limit": 2, "provider": "equity-default"}]
    assert result.category == "balance_statement"


def test_statement_provider_chain_falls_through_empty_sec_result():
    providers = []

    def income(**kwargs):
        providers.append(kwargs["provider"])
        if kwargs["provider"] == "sec":
            return FakeResult([], provider="sec")
        return FakeResult([FakeRow(period_ending="2026-01-31", total_revenue=100)], provider="fmp")

    client = OpenBBResearchClient(
        _fake_openbb(income=income),
        ResearchProviderSettings(statements=("sec", "fmp", "yfinance")),
    )

    result = client.get_financial_statements("NVDA", statement="income")

    assert providers == ["sec", "fmp"]
    assert result.provider == "fmp"
    assert [(item.provider, item.outcome, item.code) for item in result.attempts] == [
        ("sec", "failure", "no_data"),
        ("fmp", "success", None),
    ]


def test_earnings_calendar_returns_only_the_requested_symbol():
    captured = {}

    def earnings(**kwargs):
        captured.update(kwargs)
        return FakeResult([
            FakeRow(symbol="AMD", report_date="2026-08-25", eps_consensus=1.2),
            FakeRow(symbol="NVDA", report_date="2026-08-27", eps_consensus=1.5),
        ], provider="fmp")

    result = _client(earnings=earnings).get_earnings_calendar(
        "NVDA", start_date="2026-08-06", end_date="2026-09-19", provider="fmp",
    )

    assert captured == {
        "start_date": "2026-08-06", "end_date": "2026-09-19", "provider": "fmp",
    }
    assert [row["symbol"] for row in result.data] == ["NVDA"]
    assert result.symbol == "NVDA"


def test_company_filings_use_the_sec_route_with_a_bounded_limit():
    captured = {}

    def filings(**kwargs):
        captured.update(kwargs)
        return FakeResult([FakeRow(
            report_type="10-Q", filing_date="2026-05-21",
            report_url="https://www.sec.gov/Archives/example.htm",
        )], provider="sec")

    result = _client(filings=filings).get_company_filings("NVDA", limit=12)

    assert captured == {"symbol": "NVDA", "limit": 12, "provider": "sec"}
    assert result.category == "company_filings"
    assert result.provider == "sec"

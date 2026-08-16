from datetime import date
from types import SimpleNamespace

import pytest

from app.trading.research import (
    OpenBBResearchClient,
    ResearchInvalidSymbolError,
    ResearchMissingCredentialError,
    ResearchNoDataError,
    ResearchProviderSettings,
    ResearchRateLimitError,
)


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
            price=SimpleNamespace(historical=endpoints.get("equity_price")),
            profile=endpoints.get("profile"),
            fundamental=SimpleNamespace(
                income=endpoints.get("income"),
                balance=endpoints.get("balance"),
                cash=endpoints.get("cash"),
            ),
            calendar=SimpleNamespace(earnings=endpoints.get("earnings")),
        ),
        crypto=SimpleNamespace(price=SimpleNamespace(historical=endpoints.get("crypto_price"))),
        economy=SimpleNamespace(indicators=endpoints.get("macro")),
    )


def _client(**endpoints):
    return OpenBBResearchClient(
        _fake_openbb(**endpoints),
        ResearchProviderSettings(equity="equity-default", crypto="crypto-default", macro="macro-default"),
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

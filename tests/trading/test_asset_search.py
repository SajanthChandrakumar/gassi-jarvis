from types import SimpleNamespace

import pytest
import yfinance

from openbb_core.provider.abstract.fetcher import run_async

from app.trading.research.search import AssetSearchError, OpenBBAssetSearchClient, YahooAssetSearchFetcher


def _fetch(query, asset_type):
    return run_async(
        YahooAssetSearchFetcher.fetch_data,
        {"query": query, "asset_type": asset_type},
        credentials=None,
    )


def test_yahoo_fetcher_filters_quote_types_and_preserves_only_observed_identity(monkeypatch):
    calls = []

    class FakeSearch:
        def __init__(self, query, **kwargs):
            calls.append((query, kwargs))
            self.quotes = [
                {
                    "symbol": "NVDA",
                    "quoteType": "EQUITY",
                    "shortname": "NVIDIA Corporation",
                    "exchange": "NMS",
                    "currency": "USD",
                },
                {
                    "symbol": "VWRL.L",
                    "quoteType": "ETF",
                    "longname": "Vanguard FTSE All-World",
                    "exchange": "LSE",
                    "currency": "GBP",
                    "isin": "IE00B3RBWM25",
                },
                {"symbol": "BTC-USD", "quoteType": "CRYPTOCURRENCY", "shortname": "Bitcoin USD"},
                {"symbol": "NVDA.L", "quoteType": "MUTUALFUND", "shortname": "Not an equity"},
            ]
            self.response = {}

    monkeypatch.setattr(yfinance, "Search", FakeSearch)

    choices = _fetch("NVDA", "equity")

    assert calls == [("NVDA", {
        "max_results": 20,
        "news_count": 0,
        "lists_count": 0,
        "include_cb": False,
        "timeout": 10,
        "raise_errors": True,
    })]
    assert [item.symbol for item in choices] == ["NVDA"]
    assert choices[0].asset_type == "equity"
    assert choices[0].exchange == "NMS"
    assert choices[0].currency == "USD"
    assert choices[0].isin is None


@pytest.mark.parametrize(
    ("asset_type", "quote_type", "symbol"),
    [
        ("etf", "ETF", "VWRL.L"),
        ("crypto", "CRYPTOCURRENCY", "BTC-USD"),
    ],
)
def test_yahoo_fetcher_uses_explicit_category_and_keeps_real_isin_only(
    monkeypatch, asset_type, quote_type, symbol
):
    class FakeSearch:
        def __init__(self, *_args, **_kwargs):
            self.quotes = [{
                "symbol": symbol,
                "quoteType": quote_type,
                "shortname": "Observed name",
                "exchange": "OBS",
            }]
            self.response = {}

    monkeypatch.setattr(yfinance, "Search", FakeSearch)

    choices = _fetch("lookup", asset_type)

    assert len(choices) == 1
    assert choices[0].symbol == symbol
    assert choices[0].asset_type == asset_type
    assert choices[0].name == "Observed name"
    assert choices[0].currency is None
    assert choices[0].isin is None


def test_asset_search_falls_back_to_sec_only_for_equities_after_yahoo_failure(monkeypatch):
    class FailedYahooSearch:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("private Yahoo response detail")

    monkeypatch.setattr(yfinance, "Search", FailedYahooSearch)
    captured = {}

    def sec_search(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            provider="sec",
            warnings=None,
            results=[SimpleNamespace(model_dump=lambda mode="json": {"symbol": "NVDA", "name": "NVIDIA Corporation"})],
        )

    client = OpenBBAssetSearchClient(SimpleNamespace(equity=SimpleNamespace(search=sec_search)))

    response = client.search("NVIDIA", asset_type="equity")

    assert captured == {"query": "NVIDIA", "provider": "sec"}
    assert response["provider"] == "sec"
    assert response["results"][0]["symbol"] == "NVDA"
    assert response["results"][0]["isin"] is None


def test_asset_search_does_not_use_paid_default_for_crypto_when_yahoo_fails(monkeypatch):
    class FailedYahooSearch:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("private provider detail")

    monkeypatch.setattr(yfinance, "Search", FailedYahooSearch)
    client = OpenBBAssetSearchClient(SimpleNamespace())

    with pytest.raises(AssetSearchError) as error:
        client.search("Bitcoin", asset_type="crypto")

    assert error.value.public_message == "Asset search is currently unavailable for the selected category."
    assert "private provider detail" not in str(error.value)


def test_asset_search_empty_result_is_not_treated_as_provider_failure(monkeypatch):
    class EmptyYahooSearch:
        def __init__(self, *_args, **_kwargs):
            self.quotes = []
            self.response = {}

    monkeypatch.setattr(yfinance, "Search", EmptyYahooSearch)
    client = OpenBBAssetSearchClient(SimpleNamespace())

    response = client.search("unknown-name", asset_type="crypto")

    assert response["provider"] == "yfinance"
    assert response["results"] == []


def test_yahoo_fetcher_caps_results_at_twenty(monkeypatch):
    class ManyResults:
        def __init__(self, *_args, **_kwargs):
            self.quotes = [
                {"symbol": f"SYM{index}", "quoteType": "ETF"}
                for index in range(25)
            ]
            self.response = {}

    monkeypatch.setattr(yfinance, "Search", ManyResults)

    choices = _fetch("fund", "etf")

    assert len(choices) == 20
    assert choices[-1].symbol == "SYM19"

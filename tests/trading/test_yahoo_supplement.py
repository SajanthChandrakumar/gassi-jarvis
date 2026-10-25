from decimal import Decimal
from datetime import datetime, timezone

import yfinance

from app.trading.research.openbb_client import OpenBBResearchClient
from app.trading.research.yahoo_supplement import YahooSupplementFetcher
from openbb_core.provider.abstract.fetcher import run_async


def test_typed_yahoo_supplement_reads_only_requested_etf_or_crypto_fields(monkeypatch):
    calls = []

    class FakeTicker:
        def __init__(self, symbol, *, session):
            calls.append((symbol, session))

        def get_info(self):
            if calls[-1][0] == "SPY":
                return {"netExpenseRatio": 0.0945, "currency": "USD", "marketCap": 999}
            return {
                "currency": "USD", "marketCap": 1000, "circulatingSupply": 20,
                "totalSupply": 21, "maxSupply": 21,
            }

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    fund_rows = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "etf"},
        credentials=None,
    )
    crypto_rows = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "BTC-USD", "asset_type": "crypto"},
        credentials=None,
    )

    assert fund_rows[0].net_expense_ratio_percent == Decimal("0.0945")
    assert fund_rows[0].market_cap is None
    assert crypto_rows[0].market_cap == Decimal("1000")
    assert crypto_rows[0].circulating_supply == Decimal("20")
    assert crypto_rows[0].total_supply == Decimal("21")
    assert crypto_rows[0].max_supply == Decimal("21")
    assert crypto_rows[0].currency == "USD"
    assert [symbol for symbol, _ in calls] == ["SPY", "BTC-USD"]


def test_typed_yahoo_supplement_extracts_equity_quote_and_preserves_market_time(monkeypatch):
    market_time = 1_792_852_800

    class FakeTicker:
        def __init__(self, symbol, *, session):
            assert symbol == "SPY"

        def get_info(self):
            return {
                "currentPrice": 602.5,
                "regularMarketPrice": 601.75,
                "regularMarketTime": market_time,
                "regularMarketPreviousClose": 600.25,
                "regularMarketOpen": 601,
                "regularMarketDayHigh": 603,
                "regularMarketDayLow": 599,
                "regularMarketVolume": 12345,
                "fiftyTwoWeekHigh": 610,
                "fiftyTwoWeekLow": 450,
                "fiftyDayAverage": 590,
                "twoHundredDayAverage": 550,
                "currency": "USD",
            }

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    rows = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "equity"},
        credentials=None,
    )

    quote = rows[0]
    assert quote.last_price == Decimal("602.5")
    assert quote.last_timestamp == datetime.fromtimestamp(market_time, timezone.utc)
    assert quote.prev_close == Decimal("600.25")
    assert quote.open == Decimal("601")
    assert quote.high == Decimal("603")
    assert quote.low == Decimal("599")
    assert quote.volume == Decimal("12345")
    assert quote.year_high == Decimal("610")
    assert quote.year_low == Decimal("450")
    assert quote.ma_50d == Decimal("590")
    assert quote.ma_200d == Decimal("550")
    assert quote.currency == "USD"


def test_equity_quote_uses_regular_market_price_only_when_current_price_is_absent(monkeypatch):
    current_price_values = [None, 603.5]

    class FakeTicker:
        def __init__(self, symbol, *, session):
            pass

        def get_info(self):
            current_price = current_price_values.pop(0)
            row = {"regularMarketPrice": 601.75, "previousClose": 599.5}
            if current_price is not None:
                row["currentPrice"] = current_price
            return row

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    fallback = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "equity"},
        credentials=None,
    )[0]
    preferred = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "equity"},
        credentials=None,
    )[0]

    assert fallback.last_price == Decimal("601.75")
    assert preferred.last_price == Decimal("603.5")


def test_equity_quote_falls_back_when_current_price_is_null_and_preserves_market_time(monkeypatch):
    market_time = 1_792_852_800

    class FakeTicker:
        def __init__(self, symbol, *, session):
            pass

        def get_info(self):
            return {
                "currentPrice": None,
                "regularMarketPrice": 601.75,
                "regularMarketTime": market_time,
                "previousClose": 599.5,
            }

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    quote = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "equity"},
        credentials=None,
    )[0]

    assert quote.last_price == Decimal("601.75")
    assert quote.last_timestamp == datetime.fromtimestamp(market_time, timezone.utc)
    assert quote.prev_close == Decimal("599.5")


def test_equity_quote_preserves_zero_current_price_instead_of_using_regular_market_price(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol, *, session):
            pass

        def get_info(self):
            return {"currentPrice": 0, "regularMarketPrice": 601.75}

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    quote = run_async(
        YahooSupplementFetcher.fetch_data,
        params={"symbol": "SPY", "asset_type": "equity"},
        credentials=None,
    )[0]

    assert quote.last_price == Decimal("0")


def test_crypto_info_supplement_normalizes_compact_yahoo_pair_but_keeps_search_identity(monkeypatch):
    requested = []

    class FakeTicker:
        def __init__(self, symbol, *, session):
            requested.append(symbol)

        def get_info(self):
            return {"currency": "USD", "marketCap": 1000, "circulatingSupply": 20, "totalSupply": 21}

    monkeypatch.setattr(yfinance, "Ticker", FakeTicker)

    result = OpenBBResearchClient().get_crypto_info("BTCUSD")

    assert requested == ["BTC-USD"]
    assert result.symbol == "BTCUSD"
    assert result.data[0]["symbol"] == "BTCUSD"
    assert result.data[0]["currency"] == "USD"

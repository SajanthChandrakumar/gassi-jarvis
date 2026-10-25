"""Typed OpenBB Fetcher for Yahoo fields omitted by the installed routers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from collections.abc import Mapping
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


YahooSupplementAssetType = Literal["equity", "etf", "crypto"]
_FETCH_TIMEOUT_SECONDS = 10


class YahooSupplementQuery(QueryParams):
    """A bounded single-symbol request against the installed Yahoo client."""

    symbol: str = Field(min_length=1, max_length=40)
    asset_type: YahooSupplementAssetType


class YahooSupplementData(Data):
    """Fields actually returned by ``yfinance.Ticker.get_info``."""

    symbol: str
    asset_type: YahooSupplementAssetType
    last_price: Decimal | None = None
    last_timestamp: datetime | None = None
    prev_close: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None
    year_high: Decimal | None = None
    year_low: Decimal | None = None
    ma_50d: Decimal | None = None
    ma_200d: Decimal | None = None
    currency: str | None = None
    net_expense_ratio_percent: Decimal | None = None
    market_cap: Decimal | None = None
    circulating_supply: Decimal | None = None
    total_supply: Decimal | None = None
    max_supply: Decimal | None = None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def _bounded_yahoo_session():
    """Share yfinance's session while capping each network request at 10s."""
    from yfinance._http import HAS_CURL_CFFI, requests

    class BoundedSession(requests.Session):
        def __init__(self):
            if HAS_CURL_CFFI:
                super().__init__(impersonate="chrome")
            else:
                super().__init__()

        def request(self, method, url, **kwargs):
            timeout = kwargs.get("timeout")
            if isinstance(timeout, tuple):
                kwargs["timeout"] = tuple(min(float(value), _FETCH_TIMEOUT_SECONDS) for value in timeout)
            elif isinstance(timeout, (int, float)):
                kwargs["timeout"] = min(float(timeout), _FETCH_TIMEOUT_SECONDS)
            else:
                kwargs["timeout"] = _FETCH_TIMEOUT_SECONDS
            return super().request(method, url, **kwargs)

    return BoundedSession()


def _fetch_info(query: YahooSupplementQuery) -> list[dict[str, Any]]:
    try:
        from yfinance import Ticker
    except ImportError as exc:
        raise RuntimeError("The installed Yahoo Finance client is unavailable.") from exc

    ticker = Ticker(query.symbol, session=_bounded_yahoo_session())
    info = ticker.get_info()
    if not isinstance(info, Mapping):
        raise RuntimeError("Yahoo returned an invalid instrument information response.")

    row: dict[str, Any] = {"symbol": query.symbol, "asset_type": query.asset_type}
    if query.asset_type == "equity":
        # An explicit currentPrice is preferred; Yahoo uses null for an
        # unavailable value, so use the observed regular-market quote then.
        # Keep zero intact because it is a valid observed numeric value.
        price = info.get("currentPrice")
        if price is None:
            price = info.get("regularMarketPrice")
        row.update({
            "last_price": _decimal(price),
            "last_timestamp": _timestamp(info.get("regularMarketTime")),
            "prev_close": _decimal(
                info.get("regularMarketPreviousClose")
                if "regularMarketPreviousClose" in info else info.get("previousClose")
            ),
            "open": _decimal(info.get("regularMarketOpen")),
            "high": _decimal(info.get("regularMarketDayHigh")),
            "low": _decimal(info.get("regularMarketDayLow")),
            "volume": _decimal(info.get("regularMarketVolume")),
            "year_high": _decimal(info.get("fiftyTwoWeekHigh")),
            "year_low": _decimal(info.get("fiftyTwoWeekLow")),
            "ma_50d": _decimal(info.get("fiftyDayAverage")),
            "ma_200d": _decimal(info.get("twoHundredDayAverage")),
        })
        currency = info.get("currency")
        row["currency"] = currency.strip() if isinstance(currency, str) and currency.strip() else None
    elif query.asset_type == "etf":
        # Yahoo returns netExpenseRatio as percentage points (e.g. 0.0945 is
        # 0.0945%). Canonical normalization converts this field to a fraction.
        row["net_expense_ratio_percent"] = _decimal(info.get("netExpenseRatio"))
    else:
        currency = info.get("currency")
        row["currency"] = currency.strip() if isinstance(currency, str) and currency.strip() else None
        for output, source in (
            ("market_cap", "marketCap"),
            ("circulating_supply", "circulatingSupply"),
            ("total_supply", "totalSupply"),
            ("max_supply", "maxSupply"),
        ):
            row[output] = _decimal(info.get(source))
    return [row]


class YahooSupplementFetcher(Fetcher[YahooSupplementQuery, list[YahooSupplementData]]):
    """A small local OpenBB Fetcher, without provider-registry mutation."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> YahooSupplementQuery:
        return YahooSupplementQuery(**params)

    @staticmethod
    async def aextract_data(
        query: YahooSupplementQuery,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_info, query),
            timeout=_FETCH_TIMEOUT_SECONDS,
        )

    @staticmethod
    def transform_data(
        query: YahooSupplementQuery,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[YahooSupplementData]:
        del query, kwargs
        return [YahooSupplementData.model_validate(row) for row in data]

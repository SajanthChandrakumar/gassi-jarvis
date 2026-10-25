"""Typed asset discovery through an OpenBB Fetcher backed by Yahoo Search."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher, run_async
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field


SearchAssetType = Literal["equity", "etf", "crypto"]
_MAX_RESULTS = 20
_YAHOO_QUOTE_TYPES = {
    "equity": "EQUITY",
    "etf": "ETF",
    "crypto": "CRYPTOCURRENCY",
}


class AssetSearchError(RuntimeError):
    """Provider-safe public error for asset lookup failures."""

    def __init__(self, public_message: str = "Asset search is currently unavailable for the selected category."):
        super().__init__(public_message)
        self.public_message = public_message


class YahooAssetSearchQuery(QueryParams):
    """Bounded Yahoo instrument lookup request."""

    query: str = Field(min_length=1, max_length=100)
    asset_type: SearchAssetType


class YahooAssetSearchData(Data):
    """Search fields observed directly in Yahoo's quote response."""

    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    asset_type: SearchAssetType
    isin: str | None = None


class YahooAssetSearchFetcher(Fetcher[YahooAssetSearchQuery, list[YahooAssetSearchData]]):
    """OpenBB Fetcher extension for the installed Yahoo instrument search."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> YahooAssetSearchQuery:
        return YahooAssetSearchQuery(**params)

    @staticmethod
    async def aextract_data(
        query: YahooAssetSearchQuery,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        del credentials, kwargs
        try:
            from yfinance import Search
        except ImportError as exc:
            raise RuntimeError("Yahoo instrument search is not installed.") from exc

        search = await asyncio.to_thread(
            Search,
            query.query,
            max_results=_MAX_RESULTS,
            news_count=0,
            lists_count=0,
            include_cb=False,
            timeout=10,
            raise_errors=True,
        )
        response = getattr(search, "response", None)
        if isinstance(response, Mapping):
            error = (response.get("finance") or {}).get("error") if isinstance(response.get("finance"), Mapping) else None
            if error:
                raise RuntimeError("Yahoo returned an instrument search error.")
        quotes = getattr(search, "quotes", None)
        if not isinstance(quotes, (list, tuple)):
            raise RuntimeError("Yahoo returned an invalid instrument search response.")

        expected_quote_type = _YAHOO_QUOTE_TYPES[query.asset_type]
        results = []
        for quote in quotes:
            if not isinstance(quote, Mapping) or quote.get("quoteType") != expected_quote_type:
                continue
            symbol = _observed(quote.get("symbol"))
            if not symbol:
                continue
            results.append({
                "symbol": symbol,
                "name": _observed(quote.get("shortname")) or _observed(quote.get("longname")),
                "exchange": _observed(quote.get("exchange")) or _observed(quote.get("exchDisp")),
                "currency": _observed(quote.get("currency")),
                "asset_type": query.asset_type,
                "isin": _observed(quote.get("isin")),
            })
            if len(results) == _MAX_RESULTS:
                break
        return results

    @staticmethod
    def transform_data(
        query: YahooAssetSearchQuery,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[YahooAssetSearchData]:
        del query, kwargs
        return [YahooAssetSearchData.model_validate(item) for item in data]


class OpenBBAssetSearchClient:
    """Expose typed Yahoo search with an explicit free SEC equity fallback."""

    def __init__(self, openbb_client: Any | None = None) -> None:
        self._openbb_client = openbb_client

    @property
    def _obb(self) -> Any:
        if self._openbb_client is None:
            try:
                from openbb import obb
            except ImportError as exc:
                raise AssetSearchError() from exc
            self._openbb_client = obb
        return self._openbb_client

    def search(self, query: str, *, asset_type: SearchAssetType) -> dict[str, Any]:
        normalized_query = query.strip() if isinstance(query, str) else ""
        if not normalized_query:
            raise ValueError("query must contain at least one non-whitespace character")
        if len(normalized_query) > 100:
            raise ValueError("query must be 100 characters or fewer")
        if asset_type not in _YAHOO_QUOTE_TYPES:
            raise ValueError("asset_type must be equity, etf, or crypto")

        try:
            rows = run_async(
                YahooAssetSearchFetcher.fetch_data,
                {"query": normalized_query, "asset_type": asset_type},
                credentials=None,
            )
        except Exception as exc:
            if asset_type != "equity":
                raise AssetSearchError() from exc
            return self._search_sec(normalized_query)

        return _response(normalized_query, rows, "yfinance", asset_type)

    def _search_sec(self, query: str) -> dict[str, Any]:
        try:
            result = self._obb.equity.search(query=query, provider="sec")
            rows = getattr(result, "results", None)
            if rows is None and getattr(result, "warnings", None):
                raise RuntimeError("SEC search did not return results.")
            return _response(query, rows or (), _observed(getattr(result, "provider", None)) or "sec", "equity")
        except Exception as exc:
            raise AssetSearchError() from exc


def _response(query: str, rows: Any, provider: str, asset_type: SearchAssetType) -> dict[str, Any]:
    choices = []
    for row in rows:
        values = _row_values(row)
        symbol = _observed(values.get("symbol"))
        if not symbol:
            continue
        choices.append({
            "symbol": symbol,
            "name": _observed(values.get("name")),
            "exchange": _observed(values.get("exchange")) or _observed(values.get("exchange_name")),
            "currency": _observed(values.get("currency")),
            "asset_type": asset_type,
            "isin": _observed(values.get("isin")),
        })
        if len(choices) == _MAX_RESULTS:
            break
    return {"query": query, "results": choices, "provider": provider}


def _row_values(row: Any) -> Mapping[str, Any]:
    if hasattr(row, "model_dump"):
        values = row.model_dump(mode="json")
    elif isinstance(row, Mapping):
        values = row
    else:
        raise TypeError("OpenBB returned an unsupported search row")
    if not isinstance(values, Mapping):
        raise TypeError("OpenBB returned an unsupported search row")
    return values


def _observed(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None

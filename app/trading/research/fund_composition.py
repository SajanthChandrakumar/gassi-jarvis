"""Free Yahoo top holdings through a local OpenBB provider extension.

The installed OpenBB Yahoo provider does not expose this existing library
capability. This adapter preserves the subset and the unknown portfolio date.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher, run_async
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field

from .canonical import AssetIdentity, DataQuality, FreshnessStatus, ProviderAttempt, QualityStatus, ResearchProvenance
from .freshness import FreshnessPolicy
from .openbb_client import ResearchData, ResearchProviderError
from .yahoo_supplement import _bounded_yahoo_session


@dataclass(frozen=True, slots=True)
class FundHolding:
    symbol: str | None
    name: str | None
    weight: Decimal


@dataclass(frozen=True, slots=True)
class FundComposition:
    asset: AssetIdentity
    holdings: tuple[FundHolding, ...]
    sectors: tuple[tuple[str, Decimal], ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality
    is_complete: bool = False
    reference_url: str | None = None
    sectors_as_of: datetime | None = None


class FundCompositionQuery(QueryParams):
    symbol: str = Field(min_length=1, max_length=16)


class FundCompositionData(Data):
    holdings: list[dict[str, Any]]
    sectors: dict[str, Any]


class YahooFundCompositionFetcher(Fetcher[FundCompositionQuery, FundCompositionData]):
    require_credentials = False

    @staticmethod
    def transform_query(params):
        return FundCompositionQuery(**params)

    @staticmethod
    async def aextract_data(query, credentials, **kwargs):
        def read():
            from yfinance import Ticker
            fund = Ticker(query.symbol, session=_bounded_yahoo_session()).funds_data
            table = fund.top_holdings
            holdings = [
                {"symbol": str(symbol), "name": row.get("Name"), "weight": row.get("Holding Percent")}
                for symbol, row in table.head(10).iterrows()
            ]
            return {"holdings": holdings, "sectors": fund.sector_weightings or {}}
        return await asyncio.wait_for(asyncio.to_thread(read), timeout=15)

    @staticmethod
    def transform_data(query, data, **kwargs):
        return FundCompositionData.model_validate(data)


def fetch_fund_composition(symbol: str) -> ResearchData:
    try:
        row = run_async(YahooFundCompositionFetcher.fetch_data, {"symbol": symbol}, credentials=None)
    except Exception as exc:
        raise ResearchProviderError(
            "Yahoo fund composition retrieval failed.", provider="yfinance",
            public_message="Fund holdings and sector data are currently unavailable.",
        ) from exc
    return ResearchData(
        symbol=symbol, asset_type="etf", category="fund_composition", provider="yfinance",
        retrieved_at=datetime.now(timezone.utc), data=(row.model_dump(mode="json"),),
        attempts=(ProviderAttempt("yfinance", "success"),),
    )


def _weight(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 <= result <= 1 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def normalize_fund_composition(raw: ResearchData, asset: AssetIdentity, *, now=None) -> FundComposition:
    row = raw.data[0] if raw.data else {}
    holdings = tuple(
        FundHolding(str(item["symbol"]) if item.get("symbol") else None, str(item["name"]) if item.get("name") else None, weight)
        for item in row.get("holdings", ())
        if (item.get("symbol") or item.get("name")) and (weight := _weight(item.get("weight"))) is not None
    )
    sectors = tuple(sorted(
        (str(name), weight) for name, value in row.get("sectors", {}).items()
        if (weight := _weight(value)) is not None
    ))
    missing = tuple(key for key, values in (("holdings", holdings), ("sectors", sectors)) if not values)
    def observed_date(value):
        return datetime.combine(date.fromisoformat(str(value)[:10]), datetime.min.time(), tzinfo=timezone.utc) if value else None
    as_of = observed_date(row.get("holdings_as_of"))
    sectors_as_of = observed_date(row.get("sectors_as_of"))
    is_complete = row.get("holdings_complete") is True and as_of is not None and bool(holdings) and len(holdings) == len(row.get("holdings", ()))
    warnings = () if is_complete else (("The supplied positions are not a verified complete portfolio." if as_of is not None else "Only provider top holdings are shown; this is not the complete portfolio. The portfolio observation date is unknown."),)
    if sectors and sectors_as_of is None and is_complete:
        warnings += ("The sector observation date is unknown.",)
    return FundComposition(
        asset, holdings, sectors,
        ResearchProvenance(raw.provider, raw.category, raw.retrieved_at, attempts=raw.attempts),
        as_of, FreshnessPolicy().status_for(raw.category, raw.retrieved_at, now=now),
        DataQuality(
            QualityStatus.COMPLETE if is_complete and holdings and sectors and sectors_as_of else (QualityStatus.PARTIAL if holdings or sectors else QualityStatus.EMPTY),
            warnings=warnings,
            missing_fields=missing,
        ),
        is_complete=is_complete,
        reference_url=row.get("holdings_url"),
        sectors_as_of=sectors_as_of,
    )

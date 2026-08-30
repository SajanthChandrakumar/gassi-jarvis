"""Immutable, provider-agnostic research observations for later phases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal


class CanonicalAssetType(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"
    INDEX = "index"
    MACRO_SERIES = "macro_series"
    UNKNOWN = "unknown"


class StatementPeriod(StrEnum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    TTM = "ttm"
    OTHER = "other"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class QualityStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    STALE = "stale"
    ERROR = "error"


class Availability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    NOT_SUPPORTED = "not_supported"
    NOT_REQUESTED = "not_requested"
    UPSTREAM_ERROR = "upstream_error"


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str | None
    outcome: Literal["success", "failure"]
    code: str | None = None

    def __post_init__(self) -> None:
        if self.provider is not None:
            object.__setattr__(self, "provider", _identifier(self.provider, "provider"))
        if self.outcome not in {"success", "failure"}:
            raise ValueError("outcome must be success or failure")


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class AssetIdentity:
    symbol: str
    asset_type: CanonicalAssetType
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    country: str | None = None
    provider_identifiers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _identifier(self.symbol, "symbol").upper())
        if not isinstance(self.asset_type, CanonicalAssetType):
            raise TypeError("asset_type must be a CanonicalAssetType")
        for field in ("name", "exchange", "currency", "country"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _identifier(value, field))
        object.__setattr__(
            self,
            "provider_identifiers",
            tuple(sorted((_identifier(provider, "provider"), _identifier(identifier, "identifier")) for provider, identifier in self.provider_identifiers)),
        )


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    provider: str | None
    source_category: str
    retrieved_at: datetime
    request_parameters: tuple[tuple[str, str], ...] = ()
    attempts: tuple[ProviderAttempt, ...] = ()

    def __post_init__(self) -> None:
        if self.provider is not None:
            object.__setattr__(self, "provider", _identifier(self.provider, "provider"))
        object.__setattr__(self, "source_category", _identifier(self.source_category, "source_category"))
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "request_parameters", tuple(sorted((str(key), str(value)) for key, value in self.request_parameters)))
        object.__setattr__(self, "attempts", tuple(self.attempts))


@dataclass(frozen=True, slots=True)
class DataQuality:
    status: QualityStatus
    availability: Availability = Availability.AVAILABLE
    warnings: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, QualityStatus) or not isinstance(self.availability, Availability):
            raise TypeError("status and availability must use their canonical enums")
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "missing_fields", tuple(sorted(set(str(item) for item in self.missing_fields))) )


@dataclass(frozen=True, slots=True)
class PriceBar:
    timestamp: datetime
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None = None
    vwap: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "timestamp"))


@dataclass(frozen=True, slots=True)
class PriceSeries:
    asset: AssetIdentity
    bars: tuple[PriceBar, ...]
    interval: str | None
    currency: str | None
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        bars = tuple(sorted(self.bars, key=lambda bar: bar.timestamp))
        if any(not isinstance(bar, PriceBar) for bar in bars):
            raise TypeError("bars must contain PriceBar values")
        object.__setattr__(self, "bars", bars)
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class EquityQuote:
    asset: AssetIdentity
    last_price: Decimal | None
    previous_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: Decimal | None
    year_high: Decimal | None
    year_low: Decimal | None
    moving_average_50d: Decimal | None
    moving_average_200d: Decimal | None
    currency: str | None
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class CompanyProfile:
    asset: AssetIdentity
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality


@dataclass(frozen=True, slots=True)
class FinancialStatement:
    statement_type: str
    period_end: datetime | None
    period: StatementPeriod
    values: tuple[tuple[str, Decimal | None], ...]
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    reported_at: datetime | None = None
    native_fields: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement_type", _identifier(self.statement_type, "statement_type"))
        if self.period_end is not None:
            object.__setattr__(self, "period_end", _utc(self.period_end, "period_end"))
        if self.reported_at is not None:
            object.__setattr__(self, "reported_at", _utc(self.reported_at, "reported_at"))
        object.__setattr__(self, "values", tuple(sorted(self.values)))
        object.__setattr__(self, "native_fields", tuple(sorted(self.native_fields, key=lambda item: item[0])))


@dataclass(frozen=True, slots=True)
class FundamentalsData:
    asset: AssetIdentity
    statements: tuple[FinancialStatement, ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality


@dataclass(frozen=True, slots=True)
class ValuationData:
    asset: AssetIdentity
    metrics: tuple[tuple[str, Decimal | None], ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics)))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class EarningsObservation:
    earnings_date: datetime | None
    period_end: datetime | None
    reported_eps: Decimal | None
    estimated_eps: Decimal | None
    reported_revenue: Decimal | None
    estimated_revenue: Decimal | None
    surprise: Decimal | None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class EarningsData:
    asset: AssetIdentity
    observations: tuple[EarningsObservation, ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality


@dataclass(frozen=True, slots=True)
class NewsArticle:
    published_at: datetime
    title: str
    excerpt: str | None = None
    url: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "published_at", _utc(self.published_at, "published_at"))
        object.__setattr__(self, "title", _identifier(self.title, "title"))


@dataclass(frozen=True, slots=True)
class CompanyNews:
    asset: AssetIdentity
    articles: tuple[NewsArticle, ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "articles", tuple(sorted(self.articles, key=lambda item: item.published_at, reverse=True)))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class CompanyFiling:
    form_type: str
    filing_date: datetime
    report_date: datetime | None
    description: str | None
    accession_number: str | None
    url: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "form_type", _identifier(self.form_type, "form_type").upper())
        object.__setattr__(self, "filing_date", _utc(self.filing_date, "filing_date"))
        if self.report_date is not None:
            object.__setattr__(self, "report_date", _utc(self.report_date, "report_date"))
        object.__setattr__(self, "url", _identifier(self.url, "url"))


@dataclass(frozen=True, slots=True)
class CompanyFilings:
    asset: AssetIdentity
    items: tuple[CompanyFiling, ...]
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: item.filing_date, reverse=True)))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class EstimatesData:
    asset: AssetIdentity
    availability: Availability
    provenance: ResearchProvenance | None
    freshness: FreshnessStatus
    quality: DataQuality
    metrics: tuple[tuple[str, Decimal | None], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics)))


@dataclass(frozen=True, slots=True)
class MacroObservation:
    timestamp: datetime
    value: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "timestamp"))


@dataclass(frozen=True, slots=True)
class MacroSeries:
    asset: AssetIdentity
    observations: tuple[MacroObservation, ...]
    unit: str | None
    frequency: str | None
    provenance: ResearchProvenance
    as_of: datetime | None
    freshness: FreshnessStatus
    quality: DataQuality

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(sorted(self.observations, key=lambda item: item.timestamp)))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))


@dataclass(frozen=True, slots=True)
class CryptoMarketData:
    asset: AssetIdentity
    price_history: PriceSeries
    market_cap: Decimal | None
    circulating_supply: Decimal | None
    total_supply: Decimal | None
    provenance: ResearchProvenance
    freshness: FreshnessStatus
    quality: DataQuality


@dataclass(frozen=True, slots=True)
class SectionFailure:
    section: str
    code: str
    message: str
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class AssetResearchData:
    """Selective aggregate; omitted sections were not requested, not zero."""

    asset: AssetIdentity
    quote: EquityQuote | None = None
    prices: PriceSeries | None = None
    profile: CompanyProfile | None = None
    fundamentals: FundamentalsData | None = None
    valuation: ValuationData | None = None
    earnings: EarningsData | None = None
    news: CompanyNews | None = None
    filings: CompanyFilings | None = None
    estimates: EstimatesData | None = None
    crypto: CryptoMarketData | None = None
    failures: tuple[SectionFailure, ...] = ()
    quality: DataQuality = DataQuality(QualityStatus.COMPLETE)

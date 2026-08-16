"""Deterministic conversion from Phase-1 OpenBB adapter data to canonical models."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .canonical import (
    AssetIdentity,
    CanonicalAssetType,
    CompanyProfile,
    CryptoMarketData,
    DataQuality,
    EarningsData,
    EarningsObservation,
    FinancialStatement,
    FreshnessStatus,
    FundamentalsData,
    MacroObservation,
    MacroSeries,
    PriceBar,
    PriceSeries,
    QualityStatus,
    ResearchProvenance,
    StatementPeriod,
    ValuationData,
)
from .freshness import FreshnessPolicy
from .openbb_client import ResearchData


class NormalizationError(ValueError):
    """The upstream shape cannot be represented safely by the canonical model."""


def _utc_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise NormalizationError(f"{field} must be timezone-aware")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            # A calendar date represents a daily observation, not a naive
            # instant. Canonicalize it explicitly to UTC midnight.
            if len(value) == 10:
                return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value), time.min, tzinfo=timezone.utc)
            except ValueError as exc:
                raise NormalizationError(f"{field} is not an ISO date or timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            # A date-only string is handled above. A timestamp without an
            # offset is ambiguous and must not become an invented timezone.
            raise NormalizationError(f"{field} timestamp must include a timezone")
        return parsed.astimezone(timezone.utc)
    raise NormalizationError(f"{field} must be a date or timestamp")


def _decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise NormalizationError(f"{field} must be numeric, not bool")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"{field} must be numeric or null") from exc
    if not decimal.is_finite():
        raise NormalizationError(f"{field} must be finite")
    return decimal


def _provenance(raw: ResearchData, **parameters: str | None) -> ResearchProvenance:
    return ResearchProvenance(
        provider=raw.provider,
        source_category=raw.category,
        retrieved_at=raw.retrieved_at,
        request_parameters=tuple((key, value) for key, value in parameters.items() if value is not None),
    )


def _quality(
    *,
    has_data: bool,
    warnings: tuple[str, ...],
    missing_fields: tuple[str, ...],
    freshness: FreshnessStatus,
) -> DataQuality:
    if not has_data:
        status = QualityStatus.EMPTY
    elif freshness is FreshnessStatus.STALE:
        status = QualityStatus.STALE
    elif warnings or missing_fields:
        status = QualityStatus.PARTIAL
    else:
        status = QualityStatus.COMPLETE
    return DataQuality(status=status, warnings=warnings, missing_fields=missing_fields)


def identity_from_profile(
    raw: ResearchData,
    *,
    fallback_type: CanonicalAssetType = CanonicalAssetType.EQUITY,
) -> AssetIdentity:
    row = raw.data[0] if raw.data else {}
    asset_type = str(row.get("asset_type") or row.get("issue_type") or fallback_type.value).lower()
    type_mapping = {
        "equity": CanonicalAssetType.EQUITY,
        "etf": CanonicalAssetType.ETF,
        "crypto": CanonicalAssetType.CRYPTO,
        "index": CanonicalAssetType.INDEX,
    }
    return AssetIdentity(
        symbol=str(row.get("symbol") or raw.symbol),
        asset_type=type_mapping.get(asset_type, fallback_type),
        name=row.get("name") or row.get("long_name"),
        exchange=row.get("exchange") or row.get("stock_exchange"),
        currency=row.get("currency"),
        country=row.get("country") or row.get("hq_country"),
        provider_identifiers=tuple((key, str(row[key])) for key in ("cik", "isin", "cusip", "lei") if row.get(key)),
    )


def normalize_price_data(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    interval: str | None = None,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> PriceSeries:
    """Normalize OHLCV rows, rejecting ambiguous timestamps and invalid numbers."""
    if raw.category != "price_history":
        raise NormalizationError(f"Expected price_history data, got {raw.category}")
    bars = tuple(
        PriceBar(
            timestamp=_utc_datetime(row.get("date") or row.get("timestamp"), "price timestamp"),
            open=_decimal(row.get("open"), "open"),
            high=_decimal(row.get("high"), "high"),
            low=_decimal(row.get("low"), "low"),
            close=_decimal(row.get("close"), "close"),
            volume=_decimal(row.get("volume"), "volume"),
            vwap=_decimal(row.get("vwap"), "vwap"),
        )
        for row in raw.data
    )
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, interval=interval, now=now)
    missing = tuple(field for field in ("open", "high", "low", "close", "volume") if bars and any(getattr(bar, field) is None for bar in bars))
    return PriceSeries(
        asset=asset,
        bars=bars,
        interval=interval,
        currency=asset.currency,
        provenance=_provenance(raw, start_date=raw.start_date, end_date=raw.end_date, interval=interval),
        as_of=max((bar.timestamp for bar in bars), default=None),
        freshness=freshness,
        quality=_quality(has_data=bool(bars), warnings=raw.warnings, missing_fields=missing, freshness=freshness),
    )


_STATEMENT_FIELDS = {
    "income": {
        "revenue": ("total_revenue", "operating_revenue"),
        "operating_income": ("operating_income",),
        "net_income": ("net_income",),
    },
    "balance": {
        "total_assets": ("total_assets",),
        "total_debt": ("total_debt",),
        "cash": ("cash_and_cash_equivalents", "cash_cash_equivalents_and_short_term_investments"),
        "equity": ("stockholders_equity", "total_stockholders_equity", "total_equity_gross_minority_interest"),
    },
    "cash_flow": {
        "free_cash_flow": ("free_cash_flow",),
        "operating_cash_flow": ("operating_cash_flow", "cash_flow_from_continuing_operating_activities"),
    },
}


def _period_from_row(row: Mapping[str, Any]) -> StatementPeriod:
    raw_period = str(row.get("fiscal_period") or row.get("period") or "").upper()
    if raw_period in {"FY", "ANNUAL", "YEAR"}:
        return StatementPeriod.ANNUAL
    if raw_period.startswith("Q"):
        return StatementPeriod.QUARTERLY
    if raw_period == "TTM":
        return StatementPeriod.TTM
    return StatementPeriod.OTHER


def _first_value(row: Mapping[str, Any], candidates: tuple[str, ...]) -> Any:
    for candidate in candidates:
        if candidate in row:
            return row[candidate]
    return None


def normalize_fundamentals(
    raw_sections: tuple[tuple[str, ResearchData], ...],
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> FundamentalsData:
    """Normalize selected high-value accounting concepts without inventing values."""
    policy = policy or FreshnessPolicy()
    statements: list[FinancialStatement] = []
    warnings: list[str] = []
    missing: set[str] = set()
    freshest: datetime | None = None
    statuses: list[FreshnessStatus] = []
    for statement_type, raw in raw_sections:
        if statement_type not in _STATEMENT_FIELDS:
            raise NormalizationError(f"Unsupported statement type: {statement_type}")
        warnings.extend(raw.warnings)
        statuses.append(policy.status_for(raw.category, raw.retrieved_at, now=now))
        freshest = max(filter(None, (freshest, raw.retrieved_at)), default=raw.retrieved_at)
        for row in raw.data:
            period_end_value = row.get("period_ending") or row.get("date")
            period_end = _utc_datetime(period_end_value, "period_ending") if period_end_value is not None else None
            values = tuple((concept, _decimal(_first_value(row, sources), concept)) for concept, sources in _STATEMENT_FIELDS[statement_type].items())
            missing.update(concept for concept, value in values if value is None)
            native = tuple((key, value) for key, value in row.items() if key not in {item for sources in _STATEMENT_FIELDS[statement_type].values() for item in sources})
            fiscal_period = str(row.get("fiscal_period") or "")
            fiscal_quarter = int(fiscal_period[1:]) if fiscal_period.upper().startswith("Q") and fiscal_period[1:].isdigit() else None
            statements.append(
                FinancialStatement(
                    statement_type=statement_type,
                    period_end=period_end,
                    period=_period_from_row(row),
                    values=values,
                    fiscal_year=int(row["fiscal_year"]) if row.get("fiscal_year") is not None else None,
                    fiscal_quarter=fiscal_quarter,
                    reported_at=_utc_datetime(row["reported_date"], "reported_date") if row.get("reported_date") else None,
                    native_fields=native,
                )
            )
    freshness = FreshnessStatus.STALE if FreshnessStatus.STALE in statuses else (FreshnessStatus.FRESH if statuses else FreshnessStatus.UNKNOWN)
    provenance = _provenance(raw_sections[0][1], statement_types=",".join(kind for kind, _ in raw_sections)) if raw_sections else ResearchProvenance(None, "fundamentals", datetime.now(timezone.utc))
    return FundamentalsData(
        asset=asset,
        statements=tuple(sorted(statements, key=lambda item: (item.period_end or datetime.min.replace(tzinfo=timezone.utc), item.statement_type))),
        provenance=provenance,
        as_of=max((item.period_end for item in statements if item.period_end), default=None),
        freshness=freshness,
        quality=_quality(has_data=bool(statements), warnings=tuple(warnings), missing_fields=tuple(missing), freshness=freshness),
    )


def normalize_profile(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> tuple[CompanyProfile, ValuationData]:
    row = raw.data[0] if raw.data else {}
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    quality = _quality(has_data=bool(raw.data), warnings=raw.warnings, missing_fields=(), freshness=freshness)
    provenance = _provenance(raw)
    metrics = tuple((concept, _decimal(_first_value(row, sources), concept)) for concept, sources in {
        "market_cap": ("market_cap",),
        "enterprise_value": ("enterprise_value",),
        "pe_ratio": ("pe_ratio", "trailing_pe"),
        "forward_pe": ("forward_pe",),
        "price_to_sales": ("price_to_sales",),
        "price_to_book": ("price_to_book",),
        "ev_to_ebitda": ("ev_to_ebitda",),
        "free_cash_flow_yield": ("free_cash_flow_yield",),
    }.items())
    return (
        CompanyProfile(asset=asset, provenance=provenance, as_of=None, freshness=freshness, quality=quality),
        ValuationData(asset=asset, metrics=metrics, provenance=provenance, as_of=None, freshness=freshness, quality=_quality(has_data=bool(raw.data), warnings=raw.warnings, missing_fields=tuple(name for name, value in metrics if value is None), freshness=freshness)),
    )


def normalize_earnings(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> EarningsData:
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    observations = tuple(
        EarningsObservation(
            earnings_date=_utc_datetime(row["date"], "earnings date") if row.get("date") else None,
            period_end=_utc_datetime(row["period_ending"], "period_ending") if row.get("period_ending") else None,
            reported_eps=_decimal(row.get("eps"), "reported_eps"),
            estimated_eps=_decimal(row.get("eps_estimate"), "estimated_eps"),
            reported_revenue=_decimal(row.get("revenue"), "reported_revenue"),
            estimated_revenue=_decimal(row.get("revenue_estimate"), "estimated_revenue"),
            surprise=_decimal(row.get("surprise"), "surprise"),
            status=row.get("status"),
        )
        for row in raw.data
    )
    return EarningsData(
        asset=asset,
        observations=observations,
        provenance=_provenance(raw, start_date=raw.start_date, end_date=raw.end_date),
        as_of=max((item.earnings_date for item in observations if item.earnings_date), default=None),
        freshness=freshness,
        quality=_quality(has_data=bool(observations), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )


def normalize_macro(
    raw: ResearchData,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> MacroSeries:
    if raw.category != "macro_series":
        raise NormalizationError(f"Expected macro_series data, got {raw.category}")
    first = raw.data[0] if raw.data else {}
    asset = AssetIdentity(
        symbol=str(first.get("symbol") or raw.symbol),
        asset_type=CanonicalAssetType.MACRO_SERIES,
        name=first.get("title") or first.get("symbol_root"),
        country=first.get("country"),
    )
    observations = tuple(MacroObservation(_utc_datetime(row.get("date"), "macro timestamp"), _decimal(row.get("value"), "macro value")) for row in raw.data)
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return MacroSeries(
        asset=asset,
        observations=observations,
        unit=first.get("unit"),
        frequency=first.get("frequency"),
        provenance=_provenance(raw, start_date=raw.start_date, end_date=raw.end_date),
        as_of=max((item.timestamp for item in observations), default=None),
        freshness=freshness,
        quality=_quality(has_data=bool(observations), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )


def normalize_crypto(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    interval: str | None = None,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> CryptoMarketData:
    price_history = normalize_price_data(raw, asset, interval=interval, policy=policy, now=now)
    return CryptoMarketData(
        asset=asset,
        price_history=price_history,
        market_cap=None,
        circulating_supply=None,
        total_supply=None,
        provenance=price_history.provenance,
        freshness=price_history.freshness,
        quality=price_history.quality,
    )

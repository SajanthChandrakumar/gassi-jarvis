"""Deterministic conversion from Phase-1 OpenBB adapter data to canonical models."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import urlparse
import re

from .canonical import (
    AssetIdentity,
    Availability,
    CanonicalAssetType,
    CompanyNews,
    CompanyFiling,
    CompanyFilings,
    CompanyProfile,
    CryptoMarketData,
    DataQuality,
    EarningsData,
    EarningsObservation,
    EquityQuote,
    EstimatesData,
    FinancialStatement,
    FreshnessStatus,
    FundamentalsData,
    MacroObservation,
    MacroSeries,
    NewsArticle,
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
    request_parameters = dict(raw.request_parameters)
    request_parameters.update((key, value) for key, value in parameters.items() if value is not None)
    return ResearchProvenance(
        provider=raw.provider,
        source_category=raw.category,
        retrieved_at=raw.retrieved_at,
        request_parameters=tuple(request_parameters.items()),
        attempts=raw.attempts,
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


def normalize_equity_quote(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> EquityQuote:
    if raw.category != "equity_quote":
        raise NormalizationError(f"Expected equity_quote data, got {raw.category}")
    row = raw.data[0] if raw.data else {}
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    timestamp = row.get("last_timestamp") or row.get("timestamp")
    last_price = _decimal(_first_value(row, ("last_price", "price", "close")), "last_price")
    return EquityQuote(
        asset=asset,
        last_price=last_price,
        previous_close=_decimal(_first_value(row, ("prev_close", "previous_close")), "previous_close"),
        open=_decimal(row.get("open"), "open"),
        high=_decimal(row.get("high"), "high"),
        low=_decimal(row.get("low"), "low"),
        volume=_decimal(row.get("volume"), "volume"),
        year_high=_decimal(_first_value(row, ("year_high", "fifty_two_week_high")), "year_high"),
        year_low=_decimal(_first_value(row, ("year_low", "fifty_two_week_low")), "year_low"),
        moving_average_50d=_decimal(_first_value(row, ("ma_50d", "fifty_day_average")), "moving_average_50d"),
        moving_average_200d=_decimal(_first_value(row, ("ma_200d", "two_hundred_day_average")), "moving_average_200d"),
        currency=str(row["currency"]).strip() if row.get("currency") else asset.currency,
        provenance=_provenance(raw),
        as_of=_utc_datetime(timestamp, "quote timestamp") if timestamp else None,
        freshness=freshness,
        quality=_quality(
            has_data=last_price is not None,
            warnings=raw.warnings,
            missing_fields=(() if last_price is not None else ("last_price",)),
            freshness=freshness,
        ),
    )


_VALUATION_FIELDS = {
    "market_cap": ("market_cap",),
    "enterprise_value": ("enterprise_value",),
    "pe_ratio": ("pe_ratio", "trailing_pe"),
    "forward_pe": ("forward_pe",),
    "price_to_sales": ("price_to_sales", "price_to_revenue"),
    "price_to_book": ("price_to_book",),
    "ev_to_ebitda": ("ev_to_ebitda", "enterprise_to_ebitda"),
    "free_cash_flow_yield": ("free_cash_flow_yield",),
    "revenue_growth": ("revenue_growth",),
    "earnings_growth": ("earnings_growth", "net_income_growth"),
    "gross_margin": ("gross_margin",),
    "operating_margin": ("operating_margin", "ebit_margin"),
    "return_on_equity": ("return_on_equity",),
}


def normalize_valuation_metrics(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> ValuationData:
    if raw.category != "fundamental_metrics":
        raise NormalizationError(f"Expected fundamental_metrics data, got {raw.category}")
    row = raw.data[0] if raw.data else {}
    metrics = tuple(
        (concept, _decimal(value, concept))
        for concept, aliases in _VALUATION_FIELDS.items()
        if (value := _first_value(row, aliases)) is not None
    )
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return ValuationData(
        asset=asset,
        metrics=metrics,
        provenance=_provenance(raw),
        as_of=None,
        freshness=freshness,
        quality=_quality(has_data=bool(metrics), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )
_STATEMENT_FIELDS = {
    "income": {
        "revenue": ("total_revenue", "operating_revenue"),
        "operating_income": ("operating_income",),
        "net_income": ("net_income",),
    },
    "balance": {
        "total_assets": ("total_assets",),
        "total_debt": ("total_debt", "long_term_debt", "long_term_debt_and_capital_lease_obligation"),
        "cash": ("cash_and_cash_equivalents", "cash_cash_equivalents_and_short_term_investments", "cash_and_equivalents", "cash_and_short_term_investments"),
        "equity": ("stockholders_equity", "total_stockholders_equity", "total_equity_gross_minority_interest", "common_stock_equity", "total_common_equity", "common_equity"),
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
        if row.get(candidate) is not None:
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
    statuses: list[FreshnessStatus] = []
    latest_values: dict[str, tuple[datetime, tuple[tuple[str, Decimal | None], ...]]] = {}
    for statement_type, raw in raw_sections:
        if statement_type not in _STATEMENT_FIELDS:
            raise NormalizationError(f"Unsupported statement type: {statement_type}")
        warnings.extend(raw.warnings)
        statuses.append(policy.status_for(raw.category, raw.retrieved_at, now=now))
        for row in raw.data:
            period_end_value = row.get("period_ending") or row.get("date")
            period_end = _utc_datetime(period_end_value, "period_ending") if period_end_value is not None else None
            values = tuple((concept, _decimal(_first_value(row, sources), concept)) for concept, sources in _STATEMENT_FIELDS[statement_type].items())
            if not any(value is not None for _, value in values):
                continue
            recency = period_end or datetime.min.replace(tzinfo=timezone.utc)
            if statement_type not in latest_values or recency > latest_values[statement_type][0]:
                latest_values[statement_type] = (recency, values)
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
    for _, values in latest_values.values():
        missing.update(concept for concept, value in values if value is None)
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
) -> CompanyProfile:
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    quality = _quality(has_data=bool(raw.data), warnings=raw.warnings, missing_fields=(), freshness=freshness)
    return CompanyProfile(
        asset=asset,
        provenance=_provenance(raw),
        as_of=None,
        freshness=freshness,
        quality=quality,
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
            earnings_date=_utc_datetime(value, "earnings date") if (value := _first_value(row, ("report_date", "date"))) else None,
            period_end=_utc_datetime(value, "period_ending") if (value := _first_value(row, ("period_ending", "period_end"))) else None,
            reported_eps=_decimal(_first_value(row, ("eps_actual", "eps")), "reported_eps"),
            estimated_eps=_decimal(_first_value(row, ("eps_consensus", "eps_estimate")), "estimated_eps"),
            reported_revenue=_decimal(_first_value(row, ("revenue_actual", "revenue")), "reported_revenue"),
            estimated_revenue=_decimal(_first_value(row, ("revenue_consensus", "revenue_estimate")), "estimated_revenue"),
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


def normalize_company_news(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> CompanyNews:
    if raw.category != "company_news":
        raise NormalizationError(f"Expected company_news data, got {raw.category}")
    articles = tuple(
        NewsArticle(
            published_at=_utc_datetime(row.get("date"), "news timestamp"),
            title=str(row.get("title") or "").strip(),
            excerpt=str(value).strip() if (value := _first_value(row, ("excerpt", "summary", "text"))) else None,
            url=str(row["url"]).strip() if row.get("url") else None,
            source=str(row["source"]).strip() if row.get("source") else None,
        )
        for row in raw.data
    )
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return CompanyNews(
        asset=asset,
        articles=articles,
        provenance=_provenance(raw, start_date=raw.start_date, end_date=raw.end_date),
        as_of=max((item.published_at for item in articles), default=None),
        freshness=freshness,
        quality=_quality(has_data=bool(articles), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )


_COMPANY_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "company", "limited", "ltd", "plc"}


def filter_company_news(raw: ResearchData, asset: AssetIdentity) -> ResearchData:
    tokens = {asset.symbol.lower()}
    tokens.update(
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+", asset.name or "")
        if len(token) >= 4 and token.lower() not in _COMPANY_SUFFIXES
    )
    rows = tuple(
        row for row in raw.data
        if any(
            re.search(
                rf"\b{re.escape(token)}\b",
                " ".join(str(row.get(key) or "") for key in ("title", "excerpt", "summary", "text")).lower(),
            )
            for token in tokens
        )
    )[:3]
    return replace(raw, data=rows)


def normalize_filings(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> CompanyFilings:
    if raw.category != "company_filings":
        raise NormalizationError(f"Expected company_filings data, got {raw.category}")
    items: list[CompanyFiling] = []
    for row in raw.data:
        form_type = str(_first_value(row, ("report_type", "form_type", "form")) or "").upper()
        url = str(_first_value(row, ("report_url", "filing_url", "url")) or "").strip()
        if form_type not in {"10-K", "10-Q", "8-K"} or urlparse(url).scheme not in {"http", "https"}:
            continue
        filing_date = _first_value(row, ("filing_date", "accepted_date"))
        if not filing_date:
            continue
        report_date = _first_value(row, ("report_date", "period_ending"))
        items.append(CompanyFiling(
            form_type=form_type,
            filing_date=_utc_datetime(filing_date, "filing_date"),
            report_date=_utc_datetime(report_date, "report_date") if report_date else None,
            description=str(value).strip() if (value := _first_value(row, ("primary_doc_description", "description"))) else None,
            accession_number=str(row["accession_number"]).strip() if row.get("accession_number") else None,
            url=url,
        ))
    items = sorted(items, key=lambda item: item.filing_date, reverse=True)[:5]
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return CompanyFilings(
        asset=asset,
        items=tuple(items),
        provenance=_provenance(raw),
        as_of=items[0].filing_date if items else None,
        freshness=freshness,
        quality=_quality(has_data=bool(items), warnings=raw.warnings, missing_fields=(), freshness=freshness),
    )
def normalize_estimates(
    raw: ResearchData,
    asset: AssetIdentity,
    *,
    policy: FreshnessPolicy | None = None,
    now: datetime | None = None,
) -> EstimatesData:
    if raw.category != "estimates_consensus":
        raise NormalizationError(f"Expected estimates_consensus data, got {raw.category}")
    row = raw.data[0] if raw.data else {}
    metrics = tuple(
        (name, _decimal(row.get(name), name))
        for name in ("target_high", "target_low", "target_consensus", "target_median", "number_of_analysts")
        if row.get(name) is not None
    )
    freshness = (policy or FreshnessPolicy()).status_for(raw.category, raw.retrieved_at, now=now)
    return EstimatesData(
        asset=asset,
        availability=Availability.AVAILABLE,
        provenance=_provenance(raw),
        freshness=freshness,
        quality=_quality(has_data=bool(metrics), warnings=raw.warnings, missing_fields=(), freshness=freshness),
        metrics=metrics,
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

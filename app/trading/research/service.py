"""Selective canonical-research aggregation above the Phase-1 OpenBB adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from .cache import InMemoryResearchCache, ResearchCacheKey
from .canonical import (
    AssetIdentity,
    AssetResearchData,
    Availability,
    CanonicalAssetType,
    DataQuality,
    FundProfile,
    ProviderAttempt,
    QualityStatus,
    SectionFailure,
)
from .freshness import FreshnessPolicy
from .fund_composition import normalize_fund_composition
from .issuer_fund_data import supports_issuer_fund_data
from .normalizers import (
    identity_from_fund_info,
    identity_from_profile,
    filter_company_news,
    normalize_crypto,
    normalize_earnings,
    normalize_equity_quote,
    normalize_fundamentals,
    normalize_fund_profile,
    normalize_filings,
    normalize_company_news,
    normalize_estimates,
    normalize_macro,
    normalize_price_data,
    normalize_profile,
    normalize_valuation_metrics,
)
from .openbb_client import OpenBBResearchClient, ResearchData, ResearchError


AssetSection = Literal["quote", "prices", "profile", "fund", "fundamentals", "valuation", "earnings", "filings", "news", "estimates", "crypto"]
_VALID_SECTIONS = frozenset({"quote", "prices", "profile", "fund", "fundamentals", "valuation", "earnings", "filings", "news", "estimates", "crypto"})


class CanonicalResearchService:
    """Fetch selected sections, normalize them, and retain explicit partial failures."""

    def __init__(
        self,
        client: OpenBBResearchClient,
        *,
        freshness_policy: FreshnessPolicy | None = None,
        cache: InMemoryResearchCache[ResearchData] | None = None,
    ) -> None:
        self._client = client
        self._freshness_policy = freshness_policy or FreshnessPolicy()
        self._cache = cache or InMemoryResearchCache()

    def get_asset_research_data(
        self,
        symbol: str,
        *,
        asset_type: Literal["equity", "etf", "crypto"] = "equity",
        exchange: str | None = None,
        currency: str | None = None,
        sections: Iterable[AssetSection] = ("prices",),
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        interval: str | None = None,
        provider: str | None = None,
        refresh: bool = False,
        allow_stale: bool = False,
        now: datetime | None = None,
    ) -> AssetResearchData:
        selected = tuple(dict.fromkeys(sections))
        unknown = set(selected).difference(_VALID_SECTIONS)
        if unknown:
            raise ValueError(f"Unknown research sections: {', '.join(sorted(unknown))}")
        if asset_type not in {"equity", "etf", "crypto"}:
            raise ValueError(f"Unsupported asset type: {asset_type}")
        if asset_type == "crypto" and any(section in {"quote", "fund", "fundamentals", "valuation", "earnings", "filings", "news", "estimates", "profile"} for section in selected):
            raise ValueError("Equity-only sections cannot be requested for crypto assets")

        fallback_type = {
            "equity": CanonicalAssetType.EQUITY,
            "etf": CanonicalAssetType.ETF,
            "crypto": CanonicalAssetType.CRYPTO,
        }[asset_type]
        asset = AssetIdentity(symbol=symbol, asset_type=fallback_type, exchange=exchange, currency=currency)
        failures: list[SectionFailure] = []
        quote = prices = profile = fundamentals = valuation = earnings = filings = news = estimates = crypto = fund_profile = fund_composition = None
        fund_profile_secondary = None

        profile_raw: ResearchData | None = None
        if asset_type == "equity" and any(section in selected for section in ("profile", "fundamentals", "filings", "news")):
            try:
                profile_raw = self._fetch(
                    symbol, "company_profile", provider, (),
                    lambda: self._client.get_company_profile(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                asset = identity_from_profile(profile_raw, fallback_type=fallback_type, fallback=asset)
                normalized_profile = normalize_profile(profile_raw, asset, policy=self._freshness_policy, now=now)
                if "profile" in selected:
                    profile = normalized_profile
            except (ResearchError, ValueError) as exc:
                if "profile" in selected or "fundamentals" in selected:
                    failures.append(self._failure("profile", exc))

        if asset_type == "etf" and any(section in selected for section in ("fund", "profile", "valuation")):
            fund_attempts: tuple[ProviderAttempt, ...] = ()
            try:
                raw = self._fetch(
                    symbol, "etf_info", provider, (),
                    lambda: self._client.get_fund_info(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                fund_attempts = raw.attempts
                asset = identity_from_fund_info(raw, asset)
                fund_profile = normalize_fund_profile(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("fund_info", exc))
                fund_attempts += (ProviderAttempt(getattr(exc, "provider", None) or "fund_info", "failure", getattr(exc, "code", "normalization_error")),)

            if provider is None and supports_issuer_fund_data(symbol) and hasattr(self._client, "get_issuer_fund_data"):
                try:
                    issuer_raw = self._fetch(
                        symbol, "issuer_fund_data", "ssga", (),
                        lambda: self._client.get_issuer_fund_data(symbol),
                        refresh=refresh, allow_stale=allow_stale,
                    )
                    issuer_raw = replace(issuer_raw, attempts=fund_attempts + issuer_raw.attempts)
                    issuer_asset = identity_from_fund_info(issuer_raw, asset)
                    issuer_profile = normalize_fund_profile(issuer_raw, issuer_asset, policy=self._freshness_policy, now=now)
                    issuer_composition = normalize_fund_composition(issuer_raw, issuer_asset, now=now)
                    fund_profile_secondary = fund_profile
                    asset, fund_profile, fund_composition = issuer_asset, issuer_profile, issuer_composition
                    failures = [failure for failure in failures if failure.section != "fund_info"]
                except (ResearchError, ValueError) as exc:
                    failures.append(self._failure("issuer_fund_data", exc))

        if "quote" in selected:
            try:
                raw = self._fetch(
                    symbol, "equity_quote", provider, (),
                    lambda: self._client.get_equity_quote(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                quote = normalize_equity_quote(raw, asset, policy=self._freshness_policy, now=now)
                if quote.currency and asset.currency != quote.currency:
                    # A real quote can establish the listing currency even
                    # when search/fund metadata omits it. This says nothing
                    # about a fund's separate NAV/AUM or reporting currency.
                    asset = replace(asset, currency=quote.currency)
                    quote = replace(quote, asset=asset)
                    if profile is not None:
                        profile = replace(profile, asset=asset)
                    if fund_profile is not None:
                        fund_profile = replace(fund_profile, asset=asset)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("quote", exc))

        if "valuation" in selected and asset_type == "equity":
            try:
                raw = self._fetch(
                    symbol, "fundamental_metrics", provider, (),
                    lambda: self._client.get_fundamental_metrics(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                valuation = normalize_valuation_metrics(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("valuation", exc))

        if "prices" in selected or "crypto" in selected:
            try:
                raw = self._fetch(
                    symbol, "price_history", provider,
                    (("asset_type", asset_type), ("start_date", str(start_date or "")), ("end_date", str(end_date or "")), ("interval", interval or "")),
                    lambda: self._client.get_price_history(symbol, asset_type=asset_type, start_date=start_date, end_date=end_date, interval=interval, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                normalized = normalize_price_data(raw, asset, interval=interval, policy=self._freshness_policy, now=now)
                if asset_type == "crypto":
                    market_raw = None
                    try:
                        market_raw = self._fetch(
                            symbol, "crypto_info", provider, (("asset_type", "crypto"),),
                            lambda: self._client.get_crypto_info(symbol, provider=provider),
                            refresh=refresh, allow_stale=allow_stale,
                        )
                    except ResearchError as exc:
                        failures.append(self._failure("crypto_info", exc))
                    crypto = normalize_crypto(
                        raw, asset, market_raw=market_raw, interval=interval,
                        policy=self._freshness_policy, now=now,
                    )
                if "prices" in selected:
                    prices = normalized
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("prices", exc))

        if "fundamentals" in selected and asset_type == "equity":
            statements: list[tuple[str, ResearchData]] = []
            for statement in ("income", "balance", "cash_flow"):
                try:
                    statements.append((statement, self._fetch(
                        symbol, f"{statement}_statement", provider, (("statement", statement),),
                        lambda statement=statement: self._client.get_financial_statements(symbol, statement=statement, provider=provider),
                        refresh=refresh, allow_stale=allow_stale,
                    )))
                except ResearchError as exc:
                    failures.append(self._failure(f"fundamentals.{statement}", exc))
            if statements:
                try:
                    fundamentals = normalize_fundamentals(tuple(statements), asset, policy=self._freshness_policy, now=now)
                except ValueError as exc:
                    failures.append(self._failure("fundamentals", exc))

        if "earnings" in selected and asset_type == "equity":
            try:
                anchor = (now or datetime.now(timezone.utc)).date()
                earnings_start = anchor - timedelta(days=14)
                earnings_end = anchor + timedelta(days=30)
                raw = self._fetch(
                    symbol, "earnings_calendar", provider,
                    (("start_date", earnings_start.isoformat()), ("end_date", earnings_end.isoformat())),
                    lambda: self._client.get_earnings_calendar(
                        symbol,
                        start_date=earnings_start,
                        end_date=earnings_end,
                        provider=provider,
                    ),
                    refresh=refresh, allow_stale=allow_stale,
                )
                earnings = normalize_earnings(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("earnings", exc))

        if "news" in selected and asset_type == "equity":
            try:
                raw = self._fetch(
                    symbol, "company_news", provider,
                    (("start_date", str(start_date or "")), ("end_date", str(end_date or "")), ("limit", "8")),
                    lambda: self._client.get_company_news(symbol, start_date=start_date, end_date=end_date, limit=8, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                news = normalize_company_news(filter_company_news(raw, asset), asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("news", exc))

        if "filings" in selected and asset_type == "equity":
            try:
                raw = self._fetch(
                    symbol, "company_filings", provider, (("limit", "12"),),
                    lambda: self._client.get_company_filings(symbol, limit=12, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                filings = normalize_filings(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("filings", exc))

        if "estimates" in selected and asset_type == "equity":
            try:
                raw = self._fetch(
                    symbol, "estimates_consensus", provider, (),
                    lambda: self._client.get_estimates_consensus(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                estimates = normalize_estimates(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("estimates", exc))

        if asset_type == "etf" and fund_composition is None and any(section in selected for section in ("fund", "profile", "valuation")) and hasattr(self._client, "get_fund_composition"):
            try:
                raw = self._fetch(
                    symbol, "fund_composition", "yfinance", (),
                    lambda: self._client.get_fund_composition(symbol),
                    refresh=refresh, allow_stale=allow_stale,
                )
                fund_composition = normalize_fund_composition(raw, asset, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("fund_composition", exc))

        quality = self._aggregate_quality((quote, prices, profile, fundamentals, valuation, earnings, filings, news, estimates, crypto, fund_profile, fund_composition), failures)
        return AssetResearchData(
            asset=asset,
            quote=quote,
            prices=prices,
            profile=profile,
            fundamentals=fundamentals,
            valuation=valuation,
            earnings=earnings,
            filings=filings,
            news=news,
            estimates=estimates,
            crypto=crypto,
            fund_profile=fund_profile,
            fund_composition=fund_composition,
            fund_profile_secondary=fund_profile_secondary,
            failures=tuple(failures),
            quality=quality,
        )

    def get_macro_series(
        self,
        indicator: str,
        *,
        series_id: str | None = None,
        transform: str | None = None,
        unit: str | None = None,
        country: str = "united_states",
        frequency: Literal["annual", "quarter", "month"] = "month",
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        provider: str | None = None,
        refresh: bool = False,
        allow_stale: bool = False,
        now: datetime | None = None,
    ):
        raw = self._fetch(
            indicator, "macro_series", provider,
            (("series_id", series_id or ""), ("transform", transform or ""), ("unit", unit or ""), ("country", country), ("frequency", frequency), ("start_date", str(start_date or "")), ("end_date", str(end_date or ""))),
            lambda: self._client.get_macro_series(
                indicator, series_id=series_id, transform=transform, unit=unit,
                country=country, frequency=frequency, start_date=start_date,
                end_date=end_date, provider=provider,
            ),
            refresh=refresh, allow_stale=allow_stale,
        )
        return normalize_macro(raw, policy=self._freshness_policy, now=now)

    def _fetch(
        self,
        symbol: str,
        category: str,
        provider: str | None,
        dimensions: tuple[tuple[str, str], ...],
        request: Callable[[], ResearchData],
        *,
        refresh: bool,
        allow_stale: bool,
    ) -> ResearchData:
        key = ResearchCacheKey(symbol, category, provider, dimensions)
        if not refresh:
            cached = self._cache.get(key, policy=self._freshness_policy, interval=dict(dimensions).get("interval"), allow_stale=allow_stale)
            if cached is not None:
                return cached.value
        raw = request()
        self._cache.set(key, raw, retrieved_at=raw.retrieved_at, interval=dict(dimensions).get("interval"))
        return raw

    @staticmethod
    def _failure(section: str, exc: Exception) -> SectionFailure:
        return SectionFailure(
            section=section,
            code=getattr(exc, "code", "normalization_error"),
            message=getattr(exc, "public_message", "This research section is unavailable."),
            provider=getattr(exc, "provider", None),
        )

    @staticmethod
    def _aggregate_quality(sections: tuple[Any, ...], failures: list[SectionFailure]) -> DataQuality:
        available = [section for section in sections if section is not None]
        if not available:
            return DataQuality(QualityStatus.ERROR if failures else QualityStatus.EMPTY, Availability.UPSTREAM_ERROR if failures else Availability.NOT_REQUESTED, warnings=tuple(failure.message for failure in failures))
        if failures or any(section.quality.status in {QualityStatus.PARTIAL, QualityStatus.STALE, QualityStatus.EMPTY} for section in available):
            return DataQuality(QualityStatus.PARTIAL, warnings=tuple(failure.message for failure in failures))
        return DataQuality(QualityStatus.COMPLETE)

"""Selective canonical-research aggregation above the Phase-1 OpenBB adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Any, Literal

from .cache import InMemoryResearchCache, ResearchCacheKey
from .canonical import (
    AssetIdentity,
    AssetResearchData,
    Availability,
    CanonicalAssetType,
    DataQuality,
    EstimatesData,
    FreshnessStatus,
    QualityStatus,
    SectionFailure,
)
from .freshness import FreshnessPolicy
from .normalizers import (
    identity_from_profile,
    normalize_crypto,
    normalize_earnings,
    normalize_fundamentals,
    normalize_macro,
    normalize_price_data,
    normalize_profile,
)
from .openbb_client import OpenBBResearchClient, ResearchData, ResearchError


AssetSection = Literal["prices", "profile", "fundamentals", "valuation", "earnings", "estimates", "crypto"]
_VALID_SECTIONS = frozenset({"prices", "profile", "fundamentals", "valuation", "earnings", "estimates", "crypto"})


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
        asset_type: Literal["equity", "crypto"] = "equity",
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
        if asset_type == "crypto" and any(section in {"fundamentals", "valuation", "earnings", "estimates", "profile"} for section in selected):
            raise ValueError("Equity-only sections cannot be requested for crypto assets")

        fallback_type = CanonicalAssetType.CRYPTO if asset_type == "crypto" else CanonicalAssetType.EQUITY
        asset = AssetIdentity(symbol=symbol, asset_type=fallback_type)
        failures: list[SectionFailure] = []
        prices = profile = fundamentals = valuation = earnings = estimates = crypto = None

        profile_raw: ResearchData | None = None
        if asset_type == "equity" and any(section in selected for section in ("profile", "valuation", "fundamentals")):
            try:
                profile_raw = self._fetch(
                    symbol, "company_profile", provider, (),
                    lambda: self._client.get_company_profile(symbol, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                asset = identity_from_profile(profile_raw, fallback_type=fallback_type)
                normalized_profile, normalized_valuation = normalize_profile(profile_raw, asset, policy=self._freshness_policy, now=now)
                if "profile" in selected:
                    profile = normalized_profile
                if "valuation" in selected:
                    valuation = normalized_valuation
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("profile", exc))

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
                    crypto = normalize_crypto(raw, asset, interval=interval, policy=self._freshness_policy, now=now)
                if "prices" in selected:
                    prices = normalized
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("prices", exc))

        if "fundamentals" in selected:
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

        if "earnings" in selected:
            try:
                raw = self._fetch(
                    symbol, "earnings_calendar", provider,
                    (("start_date", str(start_date or "")), ("end_date", str(end_date or ""))),
                    lambda: self._client.get_earnings_calendar(start_date=start_date, end_date=end_date, provider=provider),
                    refresh=refresh, allow_stale=allow_stale,
                )
                earnings = normalize_earnings(raw, asset, policy=self._freshness_policy, now=now)
            except (ResearchError, ValueError) as exc:
                failures.append(self._failure("earnings", exc))

        if "estimates" in selected:
            estimates = EstimatesData(
                asset=asset,
                availability=Availability.NOT_SUPPORTED,
                provenance=None,
                freshness=FreshnessStatus.UNKNOWN,
                quality=DataQuality(QualityStatus.PARTIAL, Availability.NOT_SUPPORTED, warnings=("Phase 1 does not expose a provider-neutral estimates endpoint.",)),
            )

        quality = self._aggregate_quality((prices, profile, fundamentals, valuation, earnings, estimates, crypto), failures)
        return AssetResearchData(
            asset=asset,
            prices=prices,
            profile=profile,
            fundamentals=fundamentals,
            valuation=valuation,
            earnings=earnings,
            estimates=estimates,
            crypto=crypto,
            failures=tuple(failures),
            quality=quality,
        )

    def get_macro_series(
        self,
        indicator: str,
        *,
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
            (("country", country), ("frequency", frequency), ("start_date", str(start_date or "")), ("end_date", str(end_date or ""))),
            lambda: self._client.get_macro_series(indicator, country=country, frequency=frequency, start_date=start_date, end_date=end_date, provider=provider),
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
            message=str(exc),
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

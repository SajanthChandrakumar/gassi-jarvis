"""Explicit, configurable freshness semantics for canonical research data."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .canonical import FreshnessStatus


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """TTL values are policy, not hidden business-logic constants."""

    category_ttls: Mapping[str, timedelta] = field(default_factory=lambda: {
        "price_history": timedelta(days=1),
        "price_history_intraday": timedelta(minutes=15),
        "company_profile": timedelta(days=7),
        "income_statement": timedelta(days=120),
        "balance_statement": timedelta(days=120),
        "cash_flow_statement": timedelta(days=120),
        "earnings_calendar": timedelta(days=1),
        "macro_series": timedelta(days=35),
    })

    def ttl_for(self, category: str, interval: str | None = None) -> timedelta | None:
        if category == "price_history" and interval and any(token in interval.lower() for token in ("m", "h")):
            return self.category_ttls.get("price_history_intraday")
        return self.category_ttls.get(category)

    def status_for(
        self,
        category: str,
        retrieved_at: datetime,
        *,
        interval: str | None = None,
        now: datetime | None = None,
    ) -> FreshnessStatus:
        ttl = self.ttl_for(category, interval)
        if ttl is None:
            return FreshnessStatus.UNKNOWN
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or retrieved_at.tzinfo is None:
            return FreshnessStatus.UNKNOWN
        return FreshnessStatus.FRESH if now.astimezone(timezone.utc) - retrieved_at.astimezone(timezone.utc) <= ttl else FreshnessStatus.STALE

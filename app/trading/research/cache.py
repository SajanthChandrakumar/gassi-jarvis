"""Small in-memory cache for research retrievals; never a financial truth source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

from .canonical import FreshnessStatus
from .freshness import FreshnessPolicy

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ResearchCacheKey:
    symbol: str
    category: str
    provider: str | None
    dimensions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        object.__setattr__(self, "dimensions", tuple(sorted((str(key), str(value)) for key, value in self.dimensions)))


@dataclass(frozen=True, slots=True)
class CacheLookup(Generic[T]):
    value: T
    freshness: FreshnessStatus
    from_cache: bool = True


@dataclass(frozen=True, slots=True)
class _CacheEntry(Generic[T]):
    value: T
    retrieved_at: datetime
    interval: str | None


class InMemoryResearchCache(Generic[T]):
    """Per-process cache with explicit bypass and opt-in stale return behaviour."""

    def __init__(self) -> None:
        self._entries: dict[ResearchCacheKey, _CacheEntry[T]] = {}

    def get(
        self,
        key: ResearchCacheKey,
        *,
        policy: FreshnessPolicy,
        interval: str | None = None,
        now: datetime | None = None,
        allow_stale: bool = False,
    ) -> CacheLookup[T] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        status = policy.status_for(key.category, entry.retrieved_at, interval=interval or entry.interval, now=now)
        if status is FreshnessStatus.STALE and not allow_stale:
            return None
        return CacheLookup(entry.value, status)

    def set(self, key: ResearchCacheKey, value: T, *, retrieved_at: datetime, interval: str | None = None) -> None:
        self._entries[key] = _CacheEntry(value, retrieved_at.astimezone(timezone.utc), interval)

    def clear(self) -> None:
        self._entries.clear()

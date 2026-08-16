"""Provider-independent, inspectable output of the Phase-3 relevance engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .canonical import AssetIdentity, DataQuality, ResearchProvenance, _utc


class FindingCategory(StrEnum):
    PRICE = "price"
    VOLUME = "volume"
    GROWTH = "growth"
    PROFITABILITY = "profitability"
    VALUATION = "valuation"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    EARNINGS = "earnings"
    ESTIMATES = "estimates"
    MACRO = "macro"
    CRYPTO_MARKET = "crypto_market"
    RISK = "risk"
    CROSS_METRIC = "cross_metric"
    DATA_QUALITY = "data_quality"


class FindingType(StrEnum):
    CHANGE = "change"
    ACCELERATION = "acceleration"
    DECELERATION = "deceleration"
    HISTORICAL_EXTREME = "historical_extreme"
    ANOMALY = "anomaly"
    DIVERGENCE = "divergence"
    CONTRADICTION = "contradiction"
    TREND = "trend"
    REVERSAL = "reversal"
    DATA_GAP = "data_gap"
    STALE_DATA = "stale_data"


class FindingDirection(StrEnum):
    """Direction of the observed metric, never an asset-return recommendation."""

    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


def _unit_interval(value: Decimal, field: str) -> Decimal:
    if not Decimal("0") <= value <= Decimal("1"):
        raise ValueError(f"{field} must be between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    """Quantities needed to reproduce the evaluator's conclusion."""

    metric: str
    current_value: Decimal | None = None
    previous_value: Decimal | None = None
    absolute_change: Decimal | None = None
    relative_change: Decimal | None = None
    comparison_period: str | None = None
    history_size: int = 0
    percentile: Decimal | None = None
    observations: tuple[tuple[str, Decimal], ...] = ()

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric must be non-empty")
        if self.history_size < 0:
            raise ValueError("history_size cannot be negative")
        if self.percentile is not None:
            _unit_interval(self.percentile, "percentile")
        object.__setattr__(self, "observations", tuple(sorted(self.observations)))


@dataclass(frozen=True, slots=True)
class ResearchFinding:
    """One structured observation; it intentionally contains no advice or rating."""

    id: str
    asset: AssetIdentity
    category: FindingCategory
    finding_type: FindingType
    metric: str
    theme: str
    relevance_score: Decimal
    confidence: Decimal
    direction: FindingDirection
    evidence: FindingEvidence
    context: tuple[tuple[str, str], ...]
    provenance: tuple[ResearchProvenance, ...]
    quality: DataQuality
    as_of: datetime | None
    relevance_components: tuple[tuple[str, Decimal], ...]
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.metric or not self.theme:
            raise ValueError("id, metric, and theme must be non-empty")
        _unit_interval(self.relevance_score, "relevance_score")
        _unit_interval(self.confidence, "confidence")
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))
        object.__setattr__(self, "context", tuple(sorted((str(key), str(value)) for key, value in self.context)))
        object.__setattr__(self, "provenance", tuple(sorted(self.provenance, key=lambda item: (item.provider or "", item.source_category, item.retrieved_at))))
        object.__setattr__(self, "relevance_components", tuple(sorted(self.relevance_components)))
        object.__setattr__(self, "conflicts_with", tuple(sorted(set(self.conflicts_with))))


@dataclass(frozen=True, slots=True)
class ResearchTheme:
    key: str
    finding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "finding_ids", tuple(sorted(set(self.finding_ids))))


@dataclass(frozen=True, slots=True)
class ResearchAnalysis:
    asset: AssetIdentity
    findings: tuple[ResearchFinding, ...]
    top_findings: tuple[ResearchFinding, ...]
    themes: tuple[ResearchTheme, ...]
    warnings: tuple[str, ...]
    metadata: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "top_findings", tuple(self.top_findings))
        object.__setattr__(self, "themes", tuple(sorted(self.themes, key=lambda item: item.key)))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "metadata", tuple(sorted((str(key), str(value)) for key, value in self.metadata)))

"""Immutable, provider-independent structured research-report contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .canonical import (
    AssetIdentity,
    Availability,
    CompanyFiling,
    DataQuality,
    EarningsObservation,
    FreshnessStatus,
    NewsArticle,
    ProviderAttempt,
    ResearchProvenance,
    SectionFailure,
    _utc,
)
from .findings import ResearchFinding


class ReportDepth(StrEnum):
    BRIEF = "brief"
    STANDARD = "standard"
    DETAILED = "detailed"


class ReportDataConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class ReportMetric:
    """A compact raw value or finding-derived quantity, never an interpretation."""

    key: str
    value: Decimal | None
    previous_value: Decimal | None = None
    unit: str | None = None
    finding_id: str | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("metric key must be non-empty")


@dataclass(frozen=True, slots=True)
class ReportSection:
    key: str
    title: str
    findings: tuple[ResearchFinding, ...] = ()
    metrics: tuple[ReportMetric, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: tuple[ResearchProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not self.key or not self.title:
            raise ValueError("section key and title must be non-empty")
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "metrics", tuple(sorted(self.metrics, key=lambda item: item.key)))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "provenance", tuple(sorted(self.provenance, key=lambda item: (item.provider or "", item.source_category, item.retrieved_at))))


@dataclass(frozen=True, slots=True)
class ReportFactor:
    """An observed positive, negative, or mixed research factor; not a rating."""

    finding_id: str
    category: str
    metric: str
    direction: str
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class ReportRisk:
    finding_id: str | None
    category: str
    metric: str
    evidence: tuple[tuple[str, str], ...]
    confidence: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(sorted((str(key), str(value)) for key, value in self.evidence)))


@dataclass(frozen=True, slots=True)
class ReportDataCoverage:
    section: str
    availability: Availability
    freshness: FreshnessStatus
    warnings: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    failures: tuple[SectionFailure, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))
        object.__setattr__(self, "missing_fields", tuple(sorted(set(self.missing_fields))))
        object.__setattr__(self, "failures", tuple(self.failures))


@dataclass(frozen=True, slots=True)
class ReportSource:
    provider: str | None
    source_category: str
    retrieved_at: datetime
    attempts: tuple[ProviderAttempt, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "attempts", tuple(self.attempts))


@dataclass(frozen=True, slots=True)
class ReportPricePoint:
    timestamp: datetime
    close: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "timestamp"))


@dataclass(frozen=True, slots=True)
class ReportSummary:
    dominant_theme: str | None
    strongest_positive_finding_id: str | None
    strongest_negative_finding_id: str | None
    main_risk_finding_id: str | None
    data_confidence: ReportDataConfidence


@dataclass(frozen=True, slots=True)
class AssetResearchReport:
    """Authoritative structured report; optional narrative is intentionally absent."""

    asset: AssetIdentity
    depth: ReportDepth
    summary: ReportSummary
    sections: tuple[ReportSection, ...]
    key_findings: tuple[ResearchFinding, ...]
    positive_factors: tuple[ReportFactor, ...]
    negative_factors: tuple[ReportFactor, ...]
    mixed_factors: tuple[ReportFactor, ...]
    risks: tuple[ReportRisk, ...]
    data_quality: DataQuality
    data_coverage: tuple[ReportDataCoverage, ...]
    sources: tuple[ReportSource, ...]
    as_of: datetime | None
    generated_at: datetime | None
    price_history: tuple[ReportPricePoint, ...] = ()
    earnings: tuple[EarningsObservation, ...] = ()
    news: tuple[NewsArticle, ...] = ()
    filings: tuple[CompanyFiling, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "key_findings", tuple(self.key_findings))
        object.__setattr__(self, "positive_factors", tuple(self.positive_factors))
        object.__setattr__(self, "negative_factors", tuple(self.negative_factors))
        object.__setattr__(self, "mixed_factors", tuple(self.mixed_factors))
        object.__setattr__(self, "risks", tuple(self.risks))
        object.__setattr__(self, "data_coverage", tuple(self.data_coverage))
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "price_history", tuple(self.price_history))
        object.__setattr__(self, "earnings", tuple(self.earnings))
        object.__setattr__(self, "news", tuple(self.news))
        object.__setattr__(self, "filings", tuple(self.filings))
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _utc(self.as_of, "as_of"))
        if self.generated_at is not None:
            object.__setattr__(self, "generated_at", _utc(self.generated_at, "generated_at"))
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))

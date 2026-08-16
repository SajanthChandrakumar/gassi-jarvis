"""Immutable, provider-independent models for deterministic statistical research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .canonical import AssetIdentity, DataQuality, FreshnessStatus, ResearchProvenance, _utc


class ReturnType(StrEnum):
    SIMPLE = "simple"
    LOG = "log"


class ResultStatus(StrEnum):
    COMPLETE = "complete"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"


class CorrelationMethod(StrEnum):
    PEARSON = "pearson"
    SPEARMAN = "spearman"


class RegimeTest(StrEnum):
    WELCH_T = "welch_t"
    MANN_WHITNEY_U = "mann_whitney_u"


@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    timestamp: datetime
    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "timestamp"))
        if not self.value.is_finite():
            raise ValueError("statistical point values must be finite")


@dataclass(frozen=True, slots=True)
class StatisticalSeries:
    """A prepared price-derived or externally classified numeric series."""

    asset: AssetIdentity
    points: tuple[TimeSeriesPoint, ...]
    value_type: str
    return_type: ReturnType | None
    provenance: ResearchProvenance
    freshness: FreshnessStatus
    quality: DataQuality
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        points = tuple(sorted(self.points, key=lambda item: item.timestamp))
        if len({item.timestamp for item in points}) != len(points):
            raise ValueError("statistical series timestamps must be unique")
        if not self.value_type:
            raise ValueError("value_type must be non-empty")
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))


@dataclass(frozen=True, slots=True)
class StatisticalInput:
    asset: AssetIdentity
    value_type: str
    return_type: ReturnType | None
    provenance: ResearchProvenance
    freshness: FreshnessStatus
    quality: DataQuality


@dataclass(frozen=True, slots=True)
class StatisticalContext:
    analysis_type: str
    inputs: tuple[StatisticalInput, ...]
    sample_start: datetime | None
    sample_end: datetime | None
    observations: int
    alignment: str
    parameters: tuple[tuple[str, str], ...]
    generated_at: datetime | None
    quality: DataQuality

    def __post_init__(self) -> None:
        if not self.analysis_type:
            raise ValueError("analysis_type must be non-empty")
        if self.observations < 0:
            raise ValueError("observations cannot be negative")
        if self.sample_start is not None:
            object.__setattr__(self, "sample_start", _utc(self.sample_start, "sample_start"))
        if self.sample_end is not None:
            object.__setattr__(self, "sample_end", _utc(self.sample_end, "sample_end"))
        if self.generated_at is not None:
            object.__setattr__(self, "generated_at", _utc(self.generated_at, "generated_at"))
        object.__setattr__(self, "inputs", tuple(self.inputs))
        object.__setattr__(self, "parameters", tuple(sorted((str(key), str(value)) for key, value in self.parameters)))


@dataclass(frozen=True, slots=True)
class StatisticalResult:
    context: StatisticalContext
    status: ResultStatus
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(sorted(set(self.warnings))))


@dataclass(frozen=True, slots=True)
class CorrelationResult(StatisticalResult):
    method: CorrelationMethod = CorrelationMethod.PEARSON
    coefficient: Decimal | None = None
    p_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RollingCorrelationResult(StatisticalResult):
    method: CorrelationMethod = CorrelationMethod.PEARSON
    window: int = 0
    points: tuple[TimeSeriesPoint, ...] = ()
    latest: Decimal | None = None
    mean: Decimal | None = None
    median: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RegressionCoefficient:
    name: str
    estimate: Decimal | None
    standard_error: Decimal | None
    t_statistic: Decimal | None
    p_value: Decimal | None
    confidence_interval: tuple[Decimal | None, Decimal | None]


@dataclass(frozen=True, slots=True)
class RegressionResult(StatisticalResult):
    coefficients: tuple[RegressionCoefficient, ...] = ()
    r_squared: Decimal | None = None
    adjusted_r_squared: Decimal | None = None
    residual_standard_error: Decimal | None = None
    durbin_watson: Decimal | None = None
    residual_normality_p_value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BetaResult(StatisticalResult):
    beta: Decimal | None = None
    alpha: Decimal | None = None
    r_squared: Decimal | None = None
    correlation: Decimal | None = None
    regression: RegressionResult | None = None


@dataclass(frozen=True, slots=True)
class DistributionResult(StatisticalResult):
    count: int = 0
    mean: Decimal | None = None
    median: Decimal | None = None
    standard_deviation: Decimal | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    quantiles: tuple[tuple[str, Decimal], ...] = ()
    skewness: Decimal | None = None
    excess_kurtosis: Decimal | None = None
    positive_frequency: Decimal | None = None
    downside_frequency: Decimal | None = None

    def __post_init__(self) -> None:
        StatisticalResult.__post_init__(self)
        object.__setattr__(self, "quantiles", tuple(sorted(self.quantiles)))


@dataclass(frozen=True, slots=True)
class ZScoreResult(StatisticalResult):
    current_value: Decimal | None = None
    reference_mean: Decimal | None = None
    dispersion: Decimal | None = None
    z_score: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PercentileResult(StatisticalResult):
    current_value: Decimal | None = None
    percentile: Decimal | None = None


@dataclass(frozen=True, slots=True)
class HypothesisTestResult(StatisticalResult):
    test: RegimeTest = RegimeTest.WELCH_T
    null_hypothesis: str = ""
    statistic: Decimal | None = None
    p_value: Decimal | None = None
    alpha: Decimal = Decimal("0.05")
    statistically_significant: bool | None = None
    effect_size: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RegimeComparisonResult(StatisticalResult):
    first_distribution: DistributionResult | None = None
    second_distribution: DistributionResult | None = None
    mean_difference: Decimal | None = None
    median_difference: Decimal | None = None
    hypothesis_test: HypothesisTestResult | None = None


@dataclass(frozen=True, slots=True)
class VolatilityResult(StatisticalResult):
    window: int = 0
    annualization_factor: int = 0
    realized_volatility: Decimal | None = None
    volatility_change: Decimal | None = None
    percentile: Decimal | None = None
    rolling_values: tuple[TimeSeriesPoint, ...] = ()

"""Established-library statistical primitives over canonical price series."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import isfinite, log, sqrt

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

from .canonical import DataQuality, FreshnessStatus, PriceSeries, QualityStatus
from .statistics import (
    BetaResult,
    CorrelationMethod,
    CorrelationResult,
    DistributionResult,
    HypothesisTestResult,
    PercentileResult,
    RegressionCoefficient,
    RegressionResult,
    RegimeComparisonResult,
    RegimeTest,
    ResultStatus,
    ReturnType,
    RollingCorrelationResult,
    StatisticalContext,
    StatisticalInput,
    StatisticalResult,
    StatisticalSeries,
    TimeSeriesPoint,
    VolatilityResult,
    ZScoreResult,
)


ZERO = Decimal("0")


def _decimal(value: float | np.floating | int | None) -> Decimal | None:
    if value is None or not isfinite(float(value)):
        return None
    return Decimal(str(round(float(value), 12)))


@dataclass(frozen=True, slots=True)
class StatisticalPolicy:
    """Visible safeguards against false precision from sparse samples."""

    minimum_correlation_observations: int = 20
    minimum_regression_observations: int = 30
    minimum_distribution_observations: int = 10
    minimum_hypothesis_observations: int = 10
    minimum_volatility_observations: int = 20
    material_alignment_loss: Decimal = Decimal("0.20")

    def __post_init__(self) -> None:
        if any(value < 2 for value in (
            self.minimum_correlation_observations,
            self.minimum_regression_observations,
            self.minimum_distribution_observations,
            self.minimum_hypothesis_observations,
            self.minimum_volatility_observations,
        )):
            raise ValueError("minimum sample sizes must be at least 2")


class StatisticalResearchService:
    """Pure deterministic calculations; no data fetching, caching, or LLM calls."""

    def __init__(self, policy: StatisticalPolicy | None = None) -> None:
        self.policy = policy or StatisticalPolicy()

    def prepare_returns(self, prices: PriceSeries, *, return_type: ReturnType = ReturnType.SIMPLE) -> StatisticalSeries:
        """Calculate adjacent-observation returns without forward filling gaps."""
        warnings = list(prices.quality.warnings)
        seen: set[datetime] = set()
        closes: list[tuple[datetime, Decimal]] = []
        for bar in prices.bars:
            if bar.timestamp in seen:
                warnings.append("Duplicate price timestamps were discarded.")
                continue
            seen.add(bar.timestamp)
            if bar.close is None:
                warnings.append("Missing close observations were excluded; no forward fill was applied.")
                continue
            closes.append((bar.timestamp, bar.close))
        points: list[TimeSeriesPoint] = []
        for (previous_at, previous), (current_at, current) in zip(closes, closes[1:]):
            if previous <= ZERO or current <= ZERO:
                warnings.append("Non-positive prices were excluded from return calculation.")
                continue
            value = (current / previous) - Decimal("1") if return_type is ReturnType.SIMPLE else Decimal(str(log(float(current / previous))))
            points.append(TimeSeriesPoint(current_at, value))
        if len(closes) < 2:
            warnings.append("At least two valid close observations are required for returns.")
        return StatisticalSeries(
            asset=prices.asset,
            points=tuple(points),
            value_type="return",
            return_type=return_type,
            provenance=prices.provenance,
            freshness=prices.freshness,
            quality=prices.quality,
            warnings=tuple(warnings),
        )

    def correlation(
        self,
        left: PriceSeries | StatisticalSeries,
        right: PriceSeries | StatisticalSeries,
        *,
        method: CorrelationMethod = CorrelationMethod.PEARSON,
        return_type: ReturnType = ReturnType.SIMPLE,
    ) -> CorrelationResult:
        first, second = self._returns_or_series(left, return_type), self._returns_or_series(right, return_type)
        timestamps, values, warnings = self._align((first, second))
        context = self._context("correlation", (first, second), timestamps, len(timestamps), (("method", method.value), ("return_type", return_type.value)))
        if len(timestamps) < self.policy.minimum_correlation_observations:
            return CorrelationResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(warnings + [self._minimum_warning("correlation", self.policy.minimum_correlation_observations)]), method)
        x, y = values[:, 0], values[:, 1]
        if np.isclose(np.std(x), 0) or np.isclose(np.std(y), 0):
            return CorrelationResult(context, ResultStatus.INVALID_INPUT, tuple(warnings + ["Correlation is undefined for zero-variance input."]), method)
        calculation = stats.pearsonr(x, y) if method is CorrelationMethod.PEARSON else stats.spearmanr(x, y)
        assumption = "Pearson measures linear dependence and does not establish causality." if method is CorrelationMethod.PEARSON else "Spearman measures monotonic association and does not establish causality."
        return CorrelationResult(context, ResultStatus.COMPLETE, tuple(warnings + [assumption]), method, _decimal(calculation.statistic), _decimal(calculation.pvalue))

    def rolling_correlation(
        self,
        left: PriceSeries | StatisticalSeries,
        right: PriceSeries | StatisticalSeries,
        *,
        window: int = 60,
        minimum_observations: int | None = None,
        return_type: ReturnType = ReturnType.SIMPLE,
    ) -> RollingCorrelationResult:
        if window < 2:
            raise ValueError("window must be at least 2")
        minimum_observations = minimum_observations or window
        if minimum_observations < 2 or minimum_observations > window:
            raise ValueError("minimum_observations must be between 2 and window")
        first, second = self._returns_or_series(left, return_type), self._returns_or_series(right, return_type)
        timestamps, values, warnings = self._align((first, second))
        context = self._context("rolling_correlation", (first, second), timestamps, len(timestamps), (("window", str(window)), ("minimum_observations", str(minimum_observations)), ("return_type", return_type.value)))
        if len(timestamps) < minimum_observations:
            return RollingCorrelationResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(warnings + [self._minimum_warning("rolling correlation", minimum_observations)]), CorrelationMethod.PEARSON, window)
        frame = pd.DataFrame(values, index=pd.DatetimeIndex(timestamps), columns=("left", "right"))
        rolling = frame["left"].rolling(window, min_periods=minimum_observations).corr(frame["right"]).dropna()
        points = tuple(TimeSeriesPoint(timestamp.to_pydatetime(), _decimal(value)) for timestamp, value in rolling.items() if _decimal(value) is not None)
        if not points:
            return RollingCorrelationResult(context, ResultStatus.INVALID_INPUT, tuple(warnings + ["Rolling correlation is undefined for zero-variance windows."]), CorrelationMethod.PEARSON, window)
        numeric = np.array([float(item.value) for item in points])
        return RollingCorrelationResult(context, ResultStatus.COMPLETE, tuple(warnings), CorrelationMethod.PEARSON, window, points, points[-1].value, _decimal(np.mean(numeric)), _decimal(np.median(numeric)), _decimal(np.min(numeric)), _decimal(np.max(numeric)))

    def regression(
        self,
        dependent: PriceSeries | StatisticalSeries,
        predictors: Sequence[PriceSeries | StatisticalSeries],
        *,
        return_type: ReturnType = ReturnType.SIMPLE,
    ) -> RegressionResult:
        if not predictors:
            raise ValueError("at least one predictor is required")
        all_series = (self._returns_or_series(dependent, return_type),) + tuple(self._returns_or_series(item, return_type) for item in predictors)
        timestamps, values, warnings = self._align(all_series)
        minimum = max(self.policy.minimum_regression_observations, 5 + 10 * len(predictors))
        context = self._context("ols_regression", all_series, timestamps, len(timestamps), (("return_type", return_type.value), ("predictors", str(len(predictors))), ("minimum_observations", str(minimum))))
        if len(timestamps) < minimum:
            return RegressionResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(warnings + [self._minimum_warning("regression", minimum)]))
        y, x = values[:, 0], values[:, 1:]
        if any(np.isclose(np.std(x[:, index]), 0) for index in range(x.shape[1])):
            return RegressionResult(context, ResultStatus.INVALID_INPUT, tuple(warnings + ["OLS cannot estimate a coefficient for zero-variance predictors."]))
        fitted = sm.OLS(y, sm.add_constant(x, has_constant="add")).fit()
        intervals = fitted.conf_int(alpha=0.05)
        labels = ("intercept",) + tuple(item.asset.symbol for item in all_series[1:])
        coefficients = tuple(
            RegressionCoefficient(label, _decimal(fitted.params[index]), _decimal(fitted.bse[index]), _decimal(fitted.tvalues[index]), _decimal(fitted.pvalues[index]), (_decimal(intervals[index][0]), _decimal(intervals[index][1])))
            for index, label in enumerate(labels)
        )
        _, normality_p, _, _ = sm.stats.jarque_bera(fitted.resid)
        diagnostics = list(warnings) + ["OLS describes linear association; it does not establish causality."]
        if normality_p < 0.05:
            diagnostics.append("Residual normality diagnostic is below 0.05; inference should be interpreted cautiously.")
        return RegressionResult(context, ResultStatus.COMPLETE, tuple(diagnostics), coefficients, _decimal(fitted.rsquared), _decimal(fitted.rsquared_adj), _decimal(sqrt(fitted.mse_resid)), _decimal(sm.stats.durbin_watson(fitted.resid)), _decimal(normality_p))

    def beta(
        self,
        asset: PriceSeries | StatisticalSeries,
        benchmark: PriceSeries | StatisticalSeries,
        *,
        return_type: ReturnType = ReturnType.SIMPLE,
    ) -> BetaResult:
        regression = self.regression(asset, (benchmark,), return_type=return_type)
        correlation = self.correlation(asset, benchmark, return_type=return_type)
        beta = next((item.estimate for item in regression.coefficients if item.name != "intercept"), None)
        alpha = next((item.estimate for item in regression.coefficients if item.name == "intercept"), None)
        warnings = tuple(sorted(set(regression.warnings + correlation.warnings)))
        status = regression.status if regression.status is not ResultStatus.COMPLETE else correlation.status
        return BetaResult(regression.context, status, warnings, beta, alpha, regression.r_squared, correlation.coefficient, regression)

    def describe_distribution(self, series: PriceSeries | StatisticalSeries, *, return_type: ReturnType = ReturnType.SIMPLE) -> DistributionResult:
        prepared = self._returns_or_series(series, return_type)
        values = self._values(prepared)
        context = self._context("distribution", (prepared,), [item.timestamp for item in prepared.points], len(values), (("return_type", return_type.value),))
        return self._distribution(context, values, prepared.warnings)

    def z_score(self, series: PriceSeries | StatisticalSeries, *, return_type: ReturnType = ReturnType.SIMPLE) -> ZScoreResult:
        prepared = self._returns_or_series(series, return_type)
        values = self._values(prepared)
        context = self._context("z_score", (prepared,), [item.timestamp for item in prepared.points], len(values), (("method", "classic"), ("return_type", return_type.value)))
        if len(values) < self.policy.minimum_distribution_observations:
            return ZScoreResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(prepared.warnings) + (self._minimum_warning("z-score", self.policy.minimum_distribution_observations),))
        mean, deviation = float(np.mean(values)), float(np.std(values, ddof=1))
        if np.isclose(deviation, 0):
            return ZScoreResult(context, ResultStatus.INVALID_INPUT, tuple(prepared.warnings) + ("Z-score is undefined for zero-variance input.",), _decimal(values[-1]), _decimal(mean), _decimal(deviation))
        return ZScoreResult(context, ResultStatus.COMPLETE, prepared.warnings, _decimal(values[-1]), _decimal(mean), _decimal(deviation), _decimal((values[-1] - mean) / deviation))

    def percentile(self, series: PriceSeries | StatisticalSeries, *, return_type: ReturnType = ReturnType.SIMPLE) -> PercentileResult:
        prepared = self._returns_or_series(series, return_type)
        values = self._values(prepared)
        context = self._context("percentile", (prepared,), [item.timestamp for item in prepared.points], len(values), (("return_type", return_type.value),))
        if len(values) < self.policy.minimum_distribution_observations:
            return PercentileResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(prepared.warnings) + (self._minimum_warning("percentile", self.policy.minimum_distribution_observations),))
        current = values[-1]
        return PercentileResult(context, ResultStatus.COMPLETE, prepared.warnings, _decimal(current), _decimal(np.sum(values <= current) / len(values)))

    def compare_regimes(
        self,
        first: StatisticalSeries,
        second: StatisticalSeries,
        *,
        test: RegimeTest = RegimeTest.WELCH_T,
        alpha: Decimal = Decimal("0.05"),
    ) -> RegimeComparisonResult:
        if not ZERO < alpha < Decimal("1"):
            raise ValueError("alpha must be between 0 and 1")
        first_values, second_values = self._values(first), self._values(second)
        timestamps = [item.timestamp for item in first.points] + [item.timestamp for item in second.points]
        context = self._context("regime_comparison", (first, second), timestamps, len(first_values) + len(second_values), (("test", test.value), ("alpha", str(alpha))))
        first_distribution = self._distribution(self._context("first_regime_distribution", (first,), [item.timestamp for item in first.points], len(first_values), ()), first_values, first.warnings)
        second_distribution = self._distribution(self._context("second_regime_distribution", (second,), [item.timestamp for item in second.points], len(second_values), ()), second_values, second.warnings)
        if min(len(first_values), len(second_values)) < self.policy.minimum_hypothesis_observations:
            test_result = HypothesisTestResult(context, ResultStatus.INSUFFICIENT_DATA, (self._minimum_warning("each regime", self.policy.minimum_hypothesis_observations),), test, "The two regimes have equal central tendency.", alpha=alpha)
            return RegimeComparisonResult(context, ResultStatus.INSUFFICIENT_DATA, test_result.warnings, first_distribution, second_distribution, hypothesis_test=test_result)
        test_result = self._hypothesis(context, first_values, second_values, test, alpha)
        return RegimeComparisonResult(context, ResultStatus.COMPLETE, test_result.warnings, first_distribution, second_distribution, _decimal(np.mean(first_values) - np.mean(second_values)), _decimal(np.median(first_values) - np.median(second_values)), test_result)

    def volatility(
        self,
        series: PriceSeries | StatisticalSeries,
        *,
        window: int = 20,
        annualization_factor: int = 252,
        return_type: ReturnType = ReturnType.LOG,
    ) -> VolatilityResult:
        if window < 2 or annualization_factor < 1:
            raise ValueError("window must be >= 2 and annualization_factor must be positive")
        prepared = self._returns_or_series(series, return_type)
        values = self._values(prepared)
        context = self._context("realized_volatility", (prepared,), [item.timestamp for item in prepared.points], len(values), (("window", str(window)), ("annualization_factor", str(annualization_factor)), ("return_type", return_type.value)))
        minimum = max(window, self.policy.minimum_volatility_observations)
        if len(values) < minimum:
            return VolatilityResult(context, ResultStatus.INSUFFICIENT_DATA, tuple(prepared.warnings) + (self._minimum_warning("volatility", minimum),), window, annualization_factor)
        frame = pd.Series(values, index=pd.DatetimeIndex([item.timestamp for item in prepared.points]))
        rolling = frame.rolling(window, min_periods=window).std(ddof=1).dropna() * sqrt(annualization_factor)
        points = tuple(TimeSeriesPoint(timestamp.to_pydatetime(), _decimal(value)) for timestamp, value in rolling.items() if _decimal(value) is not None)
        if not points:
            return VolatilityResult(context, ResultStatus.INVALID_INPUT, tuple(prepared.warnings) + ("Volatility is undefined for zero-variance input.",), window, annualization_factor)
        current = points[-1].value
        previous = points[-2].value if len(points) > 1 else None
        change = None if previous in (None, ZERO) else _decimal((float(current) - float(previous)) / float(previous))
        percentile = _decimal(sum(item.value <= current for item in points) / len(points))
        return VolatilityResult(context, ResultStatus.COMPLETE, prepared.warnings, window, annualization_factor, current, change, percentile, points)

    def _returns_or_series(self, value: PriceSeries | StatisticalSeries, return_type: ReturnType) -> StatisticalSeries:
        if isinstance(value, StatisticalSeries):
            if value.value_type == "return" and value.return_type is not return_type:
                raise ValueError("prepared series return_type does not match the requested analysis")
            return value
        return self.prepare_returns(value, return_type=return_type)

    def _align(self, series: Sequence[StatisticalSeries]) -> tuple[list[datetime], np.ndarray, list[str]]:
        if not series:
            raise ValueError("at least one series is required")
        frames = [pd.Series([float(item.value) for item in current.points], index=pd.DatetimeIndex([item.timestamp for item in current.points]), name=index) for index, current in enumerate(series)]
        aligned = pd.concat(frames, axis=1, join="inner").dropna()
        warnings = [warning for current in series for warning in current.warnings]
        smallest = min(len(current.points) for current in series)
        if smallest and Decimal("1") - (Decimal(len(aligned)) / Decimal(smallest)) >= self.policy.material_alignment_loss:
            warnings.append(f"Timestamp intersection removed material observations ({len(aligned)} retained from smallest input of {smallest}); no forward fill was applied.")
        return [item.to_pydatetime() for item in aligned.index], aligned.to_numpy(dtype=float), sorted(set(warnings))

    def _context(self, analysis_type: str, series: Sequence[StatisticalSeries], timestamps: Sequence[datetime], observations: int, parameters: tuple[tuple[str, str], ...]) -> StatisticalContext:
        provenance = [item.provenance for item in series]
        statuses = [item.quality.status for item in series]
        quality = DataQuality(QualityStatus.COMPLETE if statuses and all(item is QualityStatus.COMPLETE for item in statuses) else QualityStatus.PARTIAL)
        return StatisticalContext(
            analysis_type=analysis_type,
            inputs=tuple(StatisticalInput(item.asset, item.value_type, item.return_type, item.provenance, item.freshness, item.quality) for item in series),
            sample_start=min(timestamps) if timestamps else None,
            sample_end=max(timestamps) if timestamps else None,
            observations=observations,
            alignment="timestamp_intersection" if len(series) > 1 else "source_order",
            parameters=parameters,
            generated_at=max((item.retrieved_at for item in provenance), default=None),
            quality=quality,
        )

    def _distribution(self, context: StatisticalContext, values: np.ndarray, warnings: Iterable[str]) -> DistributionResult:
        warnings = tuple(warnings)
        if len(values) < self.policy.minimum_distribution_observations:
            return DistributionResult(context, ResultStatus.INSUFFICIENT_DATA, warnings + (self._minimum_warning("distribution", self.policy.minimum_distribution_observations),), count=len(values))
        standard_deviation = float(np.std(values, ddof=1))
        quantiles = tuple((label, _decimal(np.quantile(values, fraction))) for label, fraction in (("p05", 0.05), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p95", 0.95)))
        return DistributionResult(
            context, ResultStatus.COMPLETE, warnings, len(values), _decimal(np.mean(values)), _decimal(np.median(values)), _decimal(standard_deviation), _decimal(np.min(values)), _decimal(np.max(values)), quantiles,
            _decimal(stats.skew(values, bias=False)), _decimal(stats.kurtosis(values, fisher=True, bias=False)), _decimal(np.mean(values > 0)), _decimal(np.mean(values < 0)),
        )

    def _hypothesis(self, context: StatisticalContext, first: np.ndarray, second: np.ndarray, test: RegimeTest, alpha: Decimal) -> HypothesisTestResult:
        calculation = stats.ttest_ind(first, second, equal_var=False) if test is RegimeTest.WELCH_T else stats.mannwhitneyu(first, second, alternative="two-sided")
        denominator = sqrt(((len(first) - 1) * np.var(first, ddof=1) + (len(second) - 1) * np.var(second, ddof=1)) / (len(first) + len(second) - 2))
        effect = None if denominator == 0 else _decimal((np.mean(first) - np.mean(second)) / denominator)
        warnings = ["A p-value is not evidence of economic importance; inspect the reported effect size."]
        if test is RegimeTest.WELCH_T:
            warnings.append("Welch t-test assumes independent observations; serial dependence can weaken inference.")
        else:
            warnings.append("Mann–Whitney U tests distributional rank differences, not causality.")
        p_value = _decimal(calculation.pvalue)
        return HypothesisTestResult(context, ResultStatus.COMPLETE, tuple(warnings), test, "The two regimes have equal central tendency.", _decimal(calculation.statistic), p_value, alpha, p_value is not None and p_value < alpha, effect)

    @staticmethod
    def _values(series: StatisticalSeries) -> np.ndarray:
        return np.array([float(item.value) for item in series.points], dtype=float)

    @staticmethod
    def _minimum_warning(analysis: str, minimum: int) -> str:
        return f"Insufficient observations for {analysis}; at least {minimum} are required by policy."

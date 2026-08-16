from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.trading.research.canonical import (
    AssetIdentity,
    CanonicalAssetType,
    DataQuality,
    FreshnessStatus,
    PriceBar,
    PriceSeries,
    QualityStatus,
    ResearchProvenance,
)
from app.trading.research.serialization import canonical_json
from app.trading.research.statistical_service import StatisticalPolicy, StatisticalResearchService
from app.trading.research.statistics import (
    CorrelationMethod,
    RegimeTest,
    ResultStatus,
    ReturnType,
    StatisticalSeries,
    TimeSeriesPoint,
)


NOW = datetime(2026, 8, 16, 12, tzinfo=timezone.utc)
POLICY = StatisticalPolicy(
    minimum_correlation_observations=8,
    minimum_regression_observations=12,
    minimum_distribution_observations=8,
    minimum_hypothesis_observations=8,
    minimum_volatility_observations=8,
)


def _prices(symbol: str, returns: list[float], *, start: int = 0) -> PriceSeries:
    asset = AssetIdentity(symbol, CanonicalAssetType.EQUITY, currency="USD")
    value = Decimal("100")
    bars = [PriceBar(NOW + timedelta(days=start), value, value, value, value, Decimal("100"))]
    for index, change in enumerate(returns, start=1):
        value *= Decimal(str(1 + change))
        at = NOW + timedelta(days=start + index)
        bars.append(PriceBar(at, value, value, value, value, Decimal("100")))
    provenance = ResearchProvenance("fixture", "price_history", NOW)
    return PriceSeries(asset, tuple(bars), "1d", "USD", provenance, bars[-1].timestamp, FreshnessStatus.FRESH, DataQuality(QualityStatus.COMPLETE))


def _prepared(symbol: str, values: list[float]) -> StatisticalSeries:
    asset = AssetIdentity(symbol, CanonicalAssetType.EQUITY)
    provenance = ResearchProvenance("fixture", "synthetic_regime", NOW)
    return StatisticalSeries(asset, tuple(TimeSeriesPoint(NOW + timedelta(days=index), Decimal(str(value))) for index, value in enumerate(values)), "return", ReturnType.SIMPLE, provenance, FreshnessStatus.FRESH, DataQuality(QualityStatus.COMPLETE))


def test_perfect_and_negative_correlations_are_calculated_from_aligned_returns():
    engine = StatisticalResearchService(POLICY)
    values = [(-1) ** index * (0.005 + index / 10000) for index in range(20)]
    same = engine.correlation(_prices("AAA", values), _prices("BBB", values), method=CorrelationMethod.PEARSON)
    rank_same = engine.correlation(_prices("AAA", values), _prices("BBB", values), method=CorrelationMethod.SPEARMAN)
    inverse = engine.correlation(_prices("AAA", values), _prices("CCC", [-item for item in values]))

    assert same.status is ResultStatus.COMPLETE and same.coefficient == Decimal("1.0")
    assert rank_same.status is ResultStatus.COMPLETE and rank_same.coefficient == Decimal("1.0")
    assert inverse.status is ResultStatus.COMPLETE and inverse.coefficient == Decimal("-1.0")
    assert same.context.alignment == "timestamp_intersection"


def test_return_type_is_explicit_and_log_returns_are_supported():
    source = _prices("AAA", [0.10] * 12)
    prepared = StatisticalResearchService(POLICY).prepare_returns(source, return_type=ReturnType.LOG)

    assert prepared.return_type is ReturnType.LOG
    assert prepared.points[0].value > Decimal("0")


def test_alignment_uses_timestamp_intersection_without_forward_fill():
    engine = StatisticalResearchService(POLICY)
    result = engine.correlation(_prices("AAA", [0.01] * 20), _prices("BBB", [0.01] * 20, start=10))

    assert result.status is ResultStatus.INVALID_INPUT
    assert any("Timestamp intersection" in warning for warning in result.warnings)


def test_rolling_correlation_respects_window_and_missing_history():
    engine = StatisticalResearchService(POLICY)
    values = [0.01, -0.01, 0.02, -0.02] * 5
    result = engine.rolling_correlation(_prices("AAA", values), _prices("BBB", values), window=5, minimum_observations=5)
    sparse = engine.rolling_correlation(_prices("AAA", values[:3]), _prices("BBB", values[:3]), window=5, minimum_observations=5)

    assert result.status is ResultStatus.COMPLETE
    assert len(result.points) == len(values) - 5 + 1
    assert sparse.status is ResultStatus.INSUFFICIENT_DATA


def test_ols_and_beta_recover_known_synthetic_relationship():
    engine = StatisticalResearchService(POLICY)
    benchmark = [(-1) ** index * (0.003 + index / 10000) for index in range(30)]
    dependent = [0.001 + 2 * item for item in benchmark]
    regression = engine.regression(_prices("NVDA", dependent), (_prices("QQQ", benchmark),))
    multi_factor = engine.regression(_prices("NVDA", dependent), (_prices("QQQ", benchmark), _prices("DUMMY", [0.004 if index % 3 else -0.002 for index in range(30)])))
    beta = engine.beta(_prices("NVDA", dependent), _prices("QQQ", benchmark))

    assert regression.status is ResultStatus.COMPLETE
    assert abs(regression.coefficients[0].estimate - Decimal("0.001")) < Decimal("0.000001")
    assert abs(regression.coefficients[1].estimate - Decimal("2")) < Decimal("0.000001")
    assert regression.r_squared > Decimal("0.999")
    assert beta.beta == regression.coefficients[1].estimate and beta.correlation is not None
    assert multi_factor.status is ResultStatus.COMPLETE and len(multi_factor.coefficients) == 3


def test_distribution_zscore_and_percentile_are_deterministic_and_safe():
    engine = StatisticalResearchService(POLICY)
    values = [0.01, -0.01, 0.02, -0.02, 0.03, -0.03, 0.04, -0.04, 0.05, 0.10]
    source = _prices("AAA", values)
    distribution = engine.describe_distribution(source)
    zscore = engine.z_score(source)
    percentile = engine.percentile(source)
    zero_variance = engine.z_score(_prices("ZERO", [0.01] * 12))

    assert distribution.status is ResultStatus.COMPLETE and distribution.count == 10
    assert zscore.status is ResultStatus.COMPLETE and zscore.z_score is not None
    assert percentile.status is ResultStatus.COMPLETE and percentile.percentile == Decimal("1.0")
    assert zero_variance.status is ResultStatus.INVALID_INPUT
    assert canonical_json(distribution) == canonical_json(engine.describe_distribution(source))


def test_hypothesis_regime_comparison_reports_effect_and_not_just_significance():
    engine = StatisticalResearchService(POLICY)
    first = _prepared("HIGH", [0.03 + index / 10000 for index in range(12)])
    second = _prepared("LOW", [-0.02 - index / 10000 for index in range(12)])
    comparison = engine.compare_regimes(first, second, test=RegimeTest.WELCH_T)
    equal = engine.compare_regimes(_prepared("A", [0.01, -0.01] * 6), _prepared("B", [0.01, -0.01] * 6))

    assert comparison.status is ResultStatus.COMPLETE
    assert comparison.mean_difference > Decimal("0")
    assert comparison.hypothesis_test.effect_size is not None
    assert any("economic importance" in warning for warning in comparison.hypothesis_test.warnings)
    assert equal.hypothesis_test.statistically_significant is False


def test_volatility_uses_explicit_annualization_and_constant_prices_stay_finite():
    engine = StatisticalResearchService(POLICY)
    volatile = engine.volatility(_prices("AAA", [0.01, -0.02, 0.03, -0.01] * 4), window=4, annualization_factor=252)
    constant = engine.volatility(_prices("ZERO", [0.0] * 12), window=4, annualization_factor=252)

    assert volatile.status is ResultStatus.COMPLETE
    assert volatile.annualization_factor == 252 and volatile.realized_volatility is not None
    assert constant.status is ResultStatus.COMPLETE
    assert constant.realized_volatility == Decimal("0.0")


def test_insufficient_samples_and_nan_like_cases_do_not_fabricate_precision():
    engine = StatisticalResearchService(POLICY)
    short = _prices("SHORT", [0.01] * 3)
    correlation = engine.correlation(short, _prices("OTHER", [0.02] * 3))
    distribution = engine.describe_distribution(short)
    regression = engine.regression(short, (_prices("OTHER", [0.02] * 3),))

    assert correlation.status is ResultStatus.INSUFFICIENT_DATA
    assert distribution.status is ResultStatus.INSUFFICIENT_DATA
    assert regression.status is ResultStatus.INSUFFICIENT_DATA

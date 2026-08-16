# Statistical Research Engine (Phase 6)

Phase 6 adds deterministic statistical research above canonical `PriceSeries`.
It never fetches data, does not call Gemini, and returns normalised Jarvis
models rather than raw SciPy or Statsmodels objects.

```text
Canonical PriceSeries -> return preparation -> timestamp alignment
                      -> statistical primitive -> structured result
```

The public entry point is `StatisticalResearchService`. It supports
`correlation`, `rolling_correlation`, `regression`, `beta`,
`describe_distribution`, `z_score`, `percentile`, `compare_regimes`, and
`volatility`.

## Preparation and alignment

`prepare_returns` is the single return mechanism. It supports explicit simple
returns `(p_t / p_t-1) - 1` and log returns `ln(p_t / p_t-1)`. It discards
missing close values and non-positive return inputs with a warning; it never
forward-fills them. Duplicate timestamps are removed deterministically (first
valid observation retained).

Cross-series analysis uses the exact UTC timestamp intersection. Different
trading calendars, frequencies, and non-overlap therefore lower the sample
size visibly; no financial value is invented. When alignment removes at least
20% of the smallest input, the result includes an explicit warning.

## Supported analyses

- Pearson and Spearman correlation with coefficient, p-value, sample period,
  return definition, source provenance, and no-causality caveat.
- Rolling Pearson correlation with configurable window/minimum observations,
  latest value, mean, median, minimum, and maximum.
- Statsmodels OLS for one or multiple explanatory return series. Outputs
  intercept, coefficients, standard errors, t-statistics, p-values, 95%
  confidence intervals, R-squared, adjusted R-squared, residual standard
  error, Durbin-Watson, and a residual normality diagnostic.
- Beta as the single-predictor OLS coefficient, accompanied by alpha,
  R-squared, correlation, and the underlying regression result.
- Return distributions: count, mean, median, standard deviation, extrema,
  quantiles, skewness, excess kurtosis, and positive/downside frequency.
- Classic Z-score and percentile rank for the latest available observation.
- Regime comparison with Welch two-sample t-test or Mann–Whitney U, sample
  distributions, mean/median difference, p-value, chosen alpha, and Cohen's
  d where defined.
- Rolling annualized realised volatility with explicit window, return type, and
  annualisation factor (default 252), plus change and percentile.

Lagged correlation, broad multiple-testing correction, advanced factor models,
drawdown statistics, and event-study reuse are intentionally outside this
phase. The current checkout contains no Phase-5 VectorBT module to reuse, so
no drawdown implementation was duplicated here.

## Guardrails and significance

`StatisticalPolicy` centralises minimum observations: 20 correlation, 30 OLS
(and at least `5 + 10 * number_of_predictors`), 10 distribution/Z-score/
percentile, 10 observations per hypothesis-test group, and 20 volatility by
default. Analyses return `insufficient_data` or `invalid_input` with warnings,
not fabricated precision, for sparse inputs, zero variance, or invalid values.

Statistical significance and economic significance are deliberately separate.
Regime results always expose the effect size and warn that a p-value alone is
not evidence of material economic impact. OLS and correlation results also
state their linear/association assumptions and do not imply causality.

Every result carries a `StatisticalContext`: input assets, canonical
provenance, freshness and quality, sample range, observation count, alignment
method, selected return convention, analysis parameters, and a deterministic
`generated_at` equal to the latest input retrieval timestamp.

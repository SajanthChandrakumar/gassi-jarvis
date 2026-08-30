# Research & Relevance Engine (Phase 3)

Phase 3 transforms Phase-2 canonical data into a small, provider-independent
set of structured observations. It does not call Gemini, predict returns,
produce investment ratings, or create narrative reports.

```text
Canonical Research Data
        -> domain-specific evaluators
        -> candidate findings
        -> deterministic relevance scoring
        -> deduplication
        -> diversity-aware selection
        -> top findings
```

The public entry point is `ResearchRelevanceEngine.analyze(asset_data)`. It
returns `ResearchAnalysis` with all deduplicated findings, its top findings,
structured themes, warnings, and machine-readable metadata. Macro data is
analysed separately with `analyze_macro(macro_series)` because it is not a
field of `AssetResearchData`.

## Finding contract

`ResearchFinding` is immutable and deterministic. Its primary content is
structured: `category`, `finding_type`, metric, direction, evidence,
comparison context, quality, provenance, `as_of`, relevance components, and
references to conflicting evidence. Its evidence retains the current and
previous value, absolute and relative change, comparison period, history size,
and percentile where applicable. `None` remains missing data; it is never
converted to zero.

Categories are deliberately small: price, volume, growth, profitability,
valuation, balance sheet, cash flow, earnings, estimates, macro, crypto
market, risk, cross metric, and data quality. The typed finding taxonomy is
change, acceleration, deceleration, historical extreme, anomaly, divergence,
contradiction, trend, reversal, data gap, and stale data. Not every taxonomy
member has an evaluator yet; the types make later additions compatible without
changing the output contract.

`direction` describes only the measured data movement (`up`, `down`,
`neutral`, `mixed`, or `unknown`). It is not bullish/bearish language and is
not a recommendation.

## Supported analyses

- Price and crypto-market: material close-price changes, close-price
  historical extremes, volume spikes/extremes, and price/volume divergence.
- Fundamentals: compatible annual, quarterly, or TTM changes for revenue,
  operating income, net income, debt, free cash flow, and operating cash flow;
  operating-margin change; acceleration/deceleration with three compatible
  periods; and revenue/free-cash-flow divergence.
- Earnings: material reported-EPS versus estimate surprises when both values
  exist.
- Macro: material previous-observation change and historical extremes.
- Data quality: explicit stale-data and data-gap findings for retrieved
  sections or upstream section failures.

The current Phase-2 contract has only point-in-time valuation and analyst
consensus snapshots. Consequently, the engine intentionally emits no invented
valuation-history, valuation extreme, estimate-revision trend, or
price/estimates divergence finding. Those evaluators can be added only once
comparable canonical historical data is available.

## Rules, materiality, and confidence

All thresholds live in `RelevancePolicy`, rather than in individual
evaluators. Defaults include a 5% equity price move, 8% crypto/fundamental
change, 2 percentage-point margin move, 50% volume spike, five observations
for an extreme, and three compatible observations for acceleration. A generic
minimum absolute prior value of 1 prevents a tiny base value (for example
`0.0001 -> 0.0002`) from becoming highly relevant merely because its percentage
change is large. Margin uses percentage points because it is already a ratio.

Relevance and confidence answer different questions:

- `relevance_score` ranks how worth investigating an observed condition is.
- `confidence` describes deterministic evidence sufficiency; it is not a
  probability of an asset outcome.

The score is clamped to 0–1 and calculated as:

```text
0.35 * magnitude
+ 0.25 * historical rarity
+ 0.15 * recency
+ 0.15 * materiality
+ 0.10 * quality
```

Each component is included in `relevance_components`. Recency is `1.0` for
the latest selected canonical observation; no wall-clock inference is hidden in
the rank. Quality is complete `1.0`, partial `0.70`, stale `0.50`, and
empty/error `0.0`.

Confidence is also clamped to 0–1:

```text
0.45 * quality factor
+ 0.35 * min(history_size / 5, 1)
+ 0.20 * freshness factor
```

Freshness factors are fresh `1.0`, stale `0.50`, unknown `0.65`. Unsupported
or absent optional sections simply produce no financial finding. A present
partial or stale section can still be analysed, but its confidence falls and a
separate quality finding makes that limitation visible.

## Selection and conflicts

Candidates are grouped deterministically by category, metric, and finding
family. Change is separate from trend; historical extreme and anomaly share
the `unusual` family. The highest relevance, then confidence, then stable ID
wins. This collapses equivalent descriptions of the same metric without LLM
semantic matching.

Top findings are selected greedily in that stable rank order with a configured
maximum of two per category, defaulting to five total. That creates basic
diversity without concealing the full candidate list.

The engine marks a conflict only for the currently justified relationship:
opposite-direction price/crypto price and fundamental (growth, profitability,
or cash-flow) observations. Both immutable findings list each other by ID in
`conflicts_with`; the engine does not decide which side is right.

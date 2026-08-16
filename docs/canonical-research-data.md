# Canonical Research Data Model (Phase 2)

## Boundary and hierarchy

Phase 1 retrieves provider-specific `ResearchData` through OpenBB. Phase 2
normalizers convert that boundary to immutable, provider-agnostic models:

```text
OpenBB
  -> provider response / Phase-1 ResearchData
  -> explicit normalizer
  -> canonical research model
  -> future research engine
```

Future research code should use the canonical models rather than OpenBB object
or provider-specific row shapes. Phase 1 remains responsible for retrieval;
`normalizers.py` remains responsible for conversion; `service.py` coordinates
selective aggregation. Gemini is not part of this path.

## Canonical models

- `AssetIdentity`: normalized symbol, type (`equity`, `etf`, `crypto`, `index`,
  `macro_series`, or `unknown`), optional name/exchange/currency/country, and
  stable provider identifiers when supplied.
- `PriceSeries` and `PriceBar`: ordered UTC OHLCV observations with optional
  VWAP and explicit interval/currency.
- `FundamentalsData` and `FinancialStatement`: income, balance-sheet, and
  cash-flow observations with canonical high-value concepts such as revenue,
  operating income, net income, free cash flow, total assets, debt, cash, and
  equity. Provider fields that are not safely normalized are retained per
  observation as `native_fields`.
- `ValuationData`: optional market-cap, enterprise-value, P/E, forward P/E,
  price-to-sales, price-to-book, EV/EBITDA, and free-cash-flow-yield values.
- `EarningsData` and `EstimatesData`: distinct actual/estimate fields. Estimates
  are explicitly `not_supported` until Phase 1 exposes a provider-neutral
  source; they are never represented as zero.
- `MacroSeries`: dated, unit/frequency-aware macro observations.
- `CryptoMarketData`: a crypto-specific wrapper around price history plus
  optional supply/market-cap fields, without inventing unsupported derivatives
  data.
- `AssetResearchData`: selective aggregate of requested asset sections and
  explicit `SectionFailure` records for optional failures.

## Provenance, as-of, and missing values

Each canonical section carries `ResearchProvenance` with provider, source
category, UTC `retrieved_at`, and relevant request parameters. `retrieved_at`
means when Jarvis fetched the response. `as_of` means the latest date/time that
the observation itself represents; the two fields must not be substituted.

`None` means an unavailable provider value, never numeric zero. `Availability`
distinguishes available, missing, not-supported, not-requested, and upstream
error. Empty data, provider failure, and omitted sections remain distinct.

## Quality and freshness

`DataQuality` is deterministic: `complete`, `partial`, `empty`, `stale`, or
`error`, with warnings and missing-field names. `FreshnessStatus` is `fresh`,
`stale`, or `unknown` and is calculated from `retrieved_at` against the
configurable `FreshnessPolicy`.

The default policy is deliberately centralized, not hidden in normalizers:
intraday prices 15 minutes, daily prices 1 day, profile 7 days, statements 120
days, earnings calendars 1 day, and macro series 35 days. Callers can supply a
different policy for their use case. These freshness rules are operational
metadata, not a claim that data is financially authoritative.

## Cache contract

`InMemoryResearchCache` is a per-process optimization, never source of truth.
Its key contains normalized symbol, category, requested provider, and every
request dimension supplied by the service (asset type, interval, dates,
statement type, country, and frequency where applicable).

On a fresh hit, the cached Phase-1 response is normalized normally. On a stale
hit, the default is to refresh upstream. A caller may opt into `allow_stale`;
the canonical result then remains visibly stale through its freshness and
quality fields. `refresh=True` bypasses the cache and replaces the entry.

## Aggregate behaviour

`CanonicalResearchService.get_asset_research_data` takes only the requested
sections (`prices`, `profile`, `fundamentals`, `valuation`, `earnings`,
`estimates`, and `crypto`). It does not fetch every possible dataset. A failure
in one optional section creates a `SectionFailure` while independent successful
sections remain available. `get_macro_series` returns a standalone canonical
macro series because macro context is not an equity-shaped asset section.

All canonical models serialize deterministically with `to_jsonable` or
`canonical_json`, making them suitable for future cache/persistence boundaries
and tests. Phase 2 adds no relevance scoring, recommendation logic, indicators,
statistics, portfolio logic, trading, or LLM tools.

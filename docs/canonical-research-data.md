# Canonical Research Data Model (Phase 2)

The optional SPY issuer profile preserves separately labeled sponsor, trustee,
investment-region classification, NAV/AUM dates and currencies, and NAV-based
trailing distribution yield/date. `fund_profile_secondary` retains the original
Yahoo profile with its own provenance. No source's fields are silently assigned
to another provider. Official compositions carry `is_complete`, their original
holdings link and independent holdings/sector observation dates. A cash holding
can have no ticker; its observed name and weight remain intact.

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
- `EquityQuote`: last price, previous close, session OHLC/volume, 52-week range,
  moving averages, currency, quality, and provenance without client-side math.
- `FundamentalsData` and `FinancialStatement`: income, balance-sheet, and
  cash-flow observations with canonical high-value concepts such as revenue,
  operating income, net income, free cash flow, total assets, debt, cash, and
  equity. Provider-reported currency is optional and never inferred. Provider
  fields that are not safely normalized are retained per observation as
  `native_fields`.
- `FundProfile`: observed ETF name, issuer, fund family, objective, benchmark,
  fee, AUM, NAV, distribution frequency, dividend fields, replication method,
  listing currency/exchange, inception date, and an observed provider website.
  AUM/NAV currency are separate optional fields and stay absent unless the
  provider supplies them directly.
- `ValuationData`: optional market-cap, enterprise-value, P/E, forward P/E,
  price-to-sales, price-to-book, EV/EBITDA, and free-cash-flow-yield values.
- `EarningsData` and `EstimatesData`: distinct actual/estimate fields.
  `EstimatesData` retains only numeric observations supplied by the consensus
  endpoint (target high/low/consensus/median and analyst count when present).
  Provider recommendation labels are deliberately excluded.
- `CompanyNews` and `NewsArticle`: ordered headline records with source,
  publication time, optional URL/excerpt, and section-level provenance. The
  canonical layer does not interpret headline sentiment.
- `CompanyFilings` and `CompanyFiling`: at most five recent 10-K, 10-Q, or 8-K
  records with official evidence links and SEC provenance.
- `MacroSeries`: dated, unit/frequency-aware macro observations, with optional
  definition, source name/link, dataset publication timestamp, and original
  observation period. The Swiss SNB Fetcher supplies these fields; older
  providers may leave them absent.
- `CryptoMarketData`: a crypto-specific wrapper around price history plus
  optional supply/market-cap fields, without inventing unsupported derivatives
  data.
- `AssetResearchData`: selective aggregate of requested asset sections and
  explicit `SectionFailure` records for optional failures. ETF research has a
  distinct `fund` section; it does not reuse company fundamentals as fund data.

## Provenance, as-of, and missing values

Each canonical section carries `ResearchProvenance` with provider, source
category, UTC `retrieved_at`, relevant request parameters, and ordered
`ProviderAttempt` outcomes. `retrieved_at`
means when Jarvis fetched the response. `as_of` means the latest date/time that
the observation itself represents; the two fields must not be substituted.

For Swiss monthly/quarterly series, `as_of` is the period end and the original
`period` is retained on each observation. `published_at` is the SNB dataset's
publication timestamp (Europe/Zurich converted to UTC), not `retrieved_at` or
the first release date of each historical observation. Cache freshness never
means that the underlying reporting period is current.

`None` means an unavailable provider value, never numeric zero. `Availability`
distinguishes available, missing, not-supported, not-requested, and upstream
error. Empty data, provider failure, and omitted sections remain distinct.

## Quality and freshness

`DataQuality` is deterministic: `complete`, `partial`, `empty`, `stale`, or
`error`, with warnings and missing-field names. `FreshnessStatus` is `fresh`,
`stale`, or `unknown` and is calculated from `retrieved_at` against the
configurable `FreshnessPolicy`. ETF info, fund composition and crypto info use
a one-day retrieval TTL. A fresh retrieval does not establish an unknown
portfolio observation date. `FundComposition` separately preserves up to ten
observed holdings and sector weights as fractions, source provenance and the
unknown portfolio date; it does not represent a complete portfolio.

The default policy is deliberately centralized, not hidden in normalizers:
quotes and intraday prices 15 minutes, daily prices and filings 1 day, profile 7
days, statements 120 days, earnings calendars, metrics, and company news 1 day,
and macro series 35 days. Callers can supply a
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
sections (`quote`, `prices`, `profile`, `fundamentals`, `valuation`, `earnings`,
`estimates`, `filings`, `news`, `crypto`, and `fund`). It does not fetch every possible dataset. A failure
in one optional section creates a `SectionFailure` while independent successful
sections remain available. `get_macro_series` returns a standalone canonical
macro series because macro context is not an equity-shaped asset section.

All canonical models serialize deterministically with `to_jsonable` or
`canonical_json`, making them suitable for future cache/persistence boundaries
and tests. Phase 2 adds no relevance scoring, recommendation logic, indicators,
statistics, portfolio logic, trading, or LLM tools.

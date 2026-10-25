# Asset Research Reports (Phase 4)

Phase 4 composes existing canonical research data and Phase-3 findings into an
immutable, provider-independent `AssetResearchReport`.

`price_as_of` identifies the observation time of the displayed price separately
from newer fund metadata. Optional full issuer holdings retain their source
link and dates, while `fund_profile_secondary` and the separately attributed
`fund_provider_observations` section retain Yahoo-specific distribution data.

```text
OpenBB -> Canonical Data -> Relevance Engine -> Structured Findings
       -> Report Builder -> Structured Asset Research Report
```

`AssetResearchReportService.build_asset_report()` accepts an
`AssetResearchData` and its matching `ResearchAnalysis`. It has no OpenBB
client, performs no network access, invokes no Gemini model, and does not
rescore or recompute research conditions. The structured report is therefore
the authoritative output. A future narrative renderer, if introduced, may only
present this structure and has no authority to add facts, adjust findings, or
make recommendations.

## Contract and evidence

The report contains a deterministic summary, ordered sections, selected key
findings, positive/negative/mixed factors, evidence-backed risks, explicit
data coverage, compact sources with provider attempts, a bounded presentation
price history, company-news records, recent filings, `as_of`, and warnings.
Equity reports also preserve the canonical multi-period `financial_history`
array so a renderer can show dated revenue, income, cash flow, and balance
sheet values rather than only a latest-period summary. Currency is included
only when the provider returned it. ETF reports include observed
`fund_characteristics`, and coverage rows may carry an observed
`reference_url`.
`ReportSection` keeps
the original `ResearchFinding` objects, compact raw `ReportMetric` values, and
section provenance. Findings retain their source IDs, metric values,
comparisons, freshness, quality, confidence, and provider provenance.

`generated_at` intentionally is **not** a wall-clock build time: it is the
latest retained input retrieval timestamp. This makes identical inputs produce
identical reports while still exposing when the evidence was retrieved.

Positive, negative, and mixed factors are observed research factors, not
ratings. Positive/negative factors are limited to currently justified
fundamental and earnings directions; a rising debt observation is negative.
Mixed factors include explicit Phase-3 divergences and conflicts. Risk entries
are created only from a finding-backed data-quality issue, divergence,
fundamental decline, or rising debt. They always retain the originating
finding ID and structured evidence.

## Depths and selection

`ReportDepth` is presentation-only:

- `brief`: up to five key findings.
- `standard`: up to eight key findings.
- `detailed`: up to twelve key findings.

The builder preserves the Phase-3 deterministic order and applies the same
two-per-category diversity cap; it never recalculates relevance or confidence.
Sections also use stable asset-template ordering.

## Asset templates

Only meaningful sections appear; raw payloads are not dumped.

- Equity: Snapshot, Key Findings, Fundamentals, Growth, Profitability/Margins,
  Cash Flow, Balance Sheet, Valuation, Earnings/Analyst Consensus,
  Price/Market Behavior, Risks, Data Quality, Sources. Company news and filings
  are attached as sourced evidence, not interpreted report factors.
- Crypto: Snapshot, Key Findings, Price/Trend, Volume, Market Structure (only
  if canonical market-cap/supply fields exist), Risks, Data Quality, Sources.
- ETF: Snapshot, Key Findings, Price/Trend, Market Behavior, Fund/Market
  Characteristics when available, Risks, Data Quality, Sources. The fund
  section distinguishes listing currency from explicit AUM/NAV currency and
  links only provider-returned HTTP(S) websites. The report does not infer
  expense ratios, distribution policy, replication, holdings, sectors,
  geography, or fund currency from unrelated fields.

Macro is not part of `AssetResearchData`, so a macro section is not fabricated.
It can be attached only after a future explicit canonical asset-to-macro
composition layer exists.

## Data quality and unsupported coverage

`ReportDataCoverage` distinguishes `available`, `missing`, `not_requested`,
`not_supported`, and `upstream_error`, using Phase-2 `Availability` directly.
Missing remains distinct from `0`; an absent section is marked not requested,
whereas a recorded fetch failure is upstream error. Stable failure codes and
canonical missing-field names are retained alongside safe messages. Stale, partial, and empty
retrieved sections add explicit caveats. Crypto derivatives metadata is marked
not supported in coverage, but no fake report section or metric is created.

Overall report data confidence maps canonical quality deterministically:
complete to high, partial/stale to medium, and empty/error to low.

`is_partial` is true when essential fields are missing, the aggregate quality
is not complete, or a requested section failed or is stale. The additive
`missing_essentials` list names class-specific gaps: equity prices and
fundamentals; ETF prices, fund information, fee, and holdings; crypto prices,
market capitalization, circulating supply, and total supply. Local OpenBB Yahoo
Fetchers supply fees, top holdings/sectors and crypto market data where the
source actually returns them. The additive `fund_composition` retains the
top-holdings subset, unknown portfolio observation date, provenance and quality.
Missing regional coverage remains explicit; full portfolio coverage is never
implied by a successful top-holdings response.

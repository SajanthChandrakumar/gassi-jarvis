# Research-First Command Center and Free-Tier Data Design

Date: 2026-08-20
Status: approved direction, implementation pending
Scope: read-only Jarvis financial research and the Command Center

## Objective

Turn the existing Command Center into a calm, editorial research workspace and
use the configured OpenBB providers for the maximum useful free-tier coverage.
The result must foreground current research, essential financial evidence, data
quality, and provenance without presenting provider internals or decorative
"AI" interface patterns.

This remains research software. It does not add recommendations, portfolios,
market scanning, order entry, autonomous tools, or Gemini-authored financial
calculations.

## Evidence behind the design

The provider choices below are based on small live calls made through the
project's pinned OpenBB installation. No credential values or raw payloads were
recorded.

| Provider | Verified free-tier result | Design use |
|---|---|---|
| Yahoo Finance | price history, quote, profile, statements, metrics, estimates, company news | resilient credential-free default and final fallback |
| FMP | price history, quote, profile, statements, metrics, consensus estimates, short current earnings-calendar windows | richer profile, valuation, consensus, and bounded earnings |
| SEC | statements and recent filings | authoritative US-company statements and filing links |
| Tiingo | price history | first price-history fallback |
| FRED | CPI, GDP, unemployment, and other US macro series | primary macro context with explicit units and transformations |
| EconDB | macro series | credential-free macro fallback |
| Benzinga | configured credential, but the tested company-news request returned empty | configured capability only; not the default while it is operationally empty |

FMP and Tiingo news returned entitlement errors under the configured free-tier
accounts and are not used for news. A recent 44-day FMP earnings window
returned an NVDA row, while a one-year window was rejected because its `from`
date exceeded the subscription entitlement. Therefore provider-specific
calendar scope must be independent of the user's price-history timeframe.

## Architecture

The existing boundary remains intact:

```text
Command Center
  -> authenticated FastAPI research endpoint
  -> validated ResearchRequest and deterministic ResearchPlanner
  -> CanonicalResearchService
  -> OpenBBResearchClient
  -> endpoint-specific provider policy
  -> canonical data, quality, provenance, and report builders
  -> presentation-only UI
```

Gemini may select an existing high-level research tool or present validated
output. It does not select providers, combine raw fields, calculate metrics,
filter evidence, or repair missing values.

Provider routing is endpoint-specific rather than controlled by one global
equity provider. Each fallback preserves the successful provider and the failed
attempt as structured provenance. A successful fallback is an informational
notice, not by itself a partial-data condition.

## Provider policy

The first provider returning semantically valid data wins. Empty, restricted,
rate-limited, unsupported, or malformed results advance to the next provider;
explicit per-call provider overrides remain single-provider requests.

| Data section | Provider order | Notes |
|---|---|---|
| Equity price history | Yahoo Finance -> Tiingo -> FMP | Preserve requested range and interval; no synthetic bars |
| Equity quote | Yahoo Finance -> FMP | Delayed/current status and provider timestamp stay visible |
| Company profile | FMP -> Yahoo Finance | Prefer richer identity metadata; profile failure must not remove successful prices |
| US financial statements | SEC -> FMP -> Yahoo Finance | SEC first for authoritative filings; non-US/unsupported assets fall through |
| Valuation and fundamental metrics | FMP -> Yahoo Finance | Use the dedicated OpenBB metrics route instead of inferring ratios from statements |
| Analyst consensus | FMP -> Yahoo Finance | Observed provider values only; explicitly not a recommendation |
| Earnings calendar | FMP | Query `today - 14 days` through `today + 30 days`, then retain only the requested symbol |
| Company news | Yahoo Finance | Keep only directly attributable articles; do not call known-restricted FMP/Tiingo routes or the currently empty Benzinga route by default |
| SEC filings | SEC | Return a bounded recent list of 10-K, 10-Q, and material 8-K metadata and source links |
| Macro context | FRED -> EconDB where an equivalent series exists | Keep transformations, unit, observation date, and provider explicit |

The policy is code-owned, deterministic, and covered by fixtures. Environment
variables may disable or reorder configured providers, but the UI never sends a
provider name.

## Canonical data changes

### Market snapshot

Add a canonical equity quote section containing observed last price, previous
close, open, daily high/low, volume, 52-week high/low, 50/200-day moving
averages when supplied, currency, provider timestamp, freshness, quality, and
provenance. Missing quote fields remain `None`. Crypto continues to use its
canonical price-series boundary rather than an equity quote.

### Fundamentals

Normalize provider aliases for SEC, FMP, and Yahoo Finance. Drop a statement
row only when every selected canonical accounting concept is missing; preserve
its native source data nowhere else as financial truth. Determine section
`missing_fields` from the latest valid row for each statement type instead of
allowing one old empty period to mark all history partial. Preserve every valid
period and its filing/report date.

### Valuation metrics

Fetch `equity.fundamental.metrics` as a separate raw category and normalize a
small essential set:

- market capitalization and enterprise value;
- trailing and forward P/E;
- price-to-sales and price-to-book;
- EV/EBITDA and free-cash-flow yield;
- revenue growth, earnings growth, gross margin, operating margin, and return
  on equity when supplied.

The backend does not derive missing ratios. Report sections use only observed
metrics and expose their provider.

### Earnings

Map the actual OpenBB calendar schema: `report_date`, `eps_actual`,
`eps_consensus`, `revenue_actual`, `revenue_consensus`, and `last_updated`.
Filter calendar rows by exact requested symbol before normalization. Other
companies' rows must never be attached to the requested asset. The price
timeframe is not forwarded to this global calendar route.

If no matching event exists in the bounded window, the section is empty with a
clear scoped message, not an upstream error. Past surprise analysis runs only
when both actual and consensus observations are present.

### Filings

Add a canonical recent-filings section with form type, filing date, report
date, description, accession identifier, and official SEC report/detail URL.
Limit the report presentation to the five most relevant recent 10-K, 10-Q, and
8-K records. Jarvis links to filings but does not summarize or interpret their
contents in this scope.

### News relevance

Yahoo's symbol query can return loosely related market stories. Apply a
conservative deterministic filter after company identity is known: retain an
article only when its title or excerpt directly mentions the ticker or a
meaningful company-name token. Ignore generic legal suffixes and short
ambiguous tokens. Present at most three newest matches. If none match, state
that no directly attributable headlines were found in the requested window.

### Macro context

Replace unlabeled absolute values with a compact, interpretable set:

| UI label | FRED series | Transform | Unit |
|---|---|---|---|
| Inflation | CPIAUCSL | year-over-year percent change | % YoY |
| Unemployment | UNRATE | none | % |
| Policy rate | FEDFUNDS | none | % |
| US 10-year yield | DGS10 | none | % |
| Real GDP growth | GDPC1 | year-over-year percent change | % YoY |

The canonical observation and retrieval dates remain distinct. EconDB is used
only when it exposes a semantically equivalent series; otherwise the missing
FRED series remains explicit.

The implementation was extended on 2026-09-12 with a backward-compatible
`countries` collection for Switzerland and the United States. The original
table above remains the US contract; current country mappings and semantic
limitations are documented in `docs/openbb-research.md`.

## Quality, errors, and provider state

Provider failures are converted at the boundary into stable codes such as
`entitlement_required`, `rate_limited`, `no_data`, `unsupported`, and
`missing_credential`. Raw stack text, subscription URLs, and provider query
parameters are retained in server logs where appropriate but never rendered in
the Command Center.

The provider-status endpoint reports configuration, not unverified liveness:

- `built_in`: no Jarvis-managed credential required;
- `configured`: credential is present and a Jarvis route exists;
- `not_configured`: optional route is unavailable;
- `last_result`: optional in-process metadata from a real research call,
  including success/fallback/failure code and timestamp, never a key value.

The UI must not label a configured key as "active" before a successful request.
Per-report coverage remains authoritative for the data actually displayed.

`complete` means all required observed fields for the selected section are
present and fresh. `partial` means useful data exists but required fields or
periods are missing. A successful provider fallback is shown as a source note
and does not automatically change `complete` to `partial`.

## Command Center experience

The application remains a dependency-free FastAPI-served frontend. React is
not introduced: one interactive workspace does not justify a bundler, client
router, component runtime, or duplicate state layer. The existing single file
is split into semantic `index.html`, `styles.css`, and `app.js` so the design
and behavior remain maintainable with native browser APIs.

### Visual direction

The interface is an editorial research product, not a chat demo or trading
terminal:

- opaque near-black and graphite surfaces;
- one neutral sans-serif family, with monospace reserved for numeric tabular
  data and timestamps;
- cyan only for focus, selected state, and live activity;
- no glass, gradients on panels, glowing borders, decorative orb, HUD labels,
  uppercase microcopy, or status-chip clusters;
- hierarchy from type scale, alignment, whitespace, and thin dividers;
- compact number formatting such as `$216.61`, `$5.25T`, and `31.8x`, always
  retaining the canonical raw value in exports.

### Page structure

The default page is command-first:

1. A restrained top bar with Jarvis, connection state, and new-session action.
2. A focused research header titled `Research an asset` with one large input.
3. Four quiet mode tabs: Asset, Compare, History, and Relationship.
4. A useful empty state containing recent research and the local watchlist;
   explanatory onboarding rails are removed.
5. The research workspace below, with the newest result at the top.

Desktop uses a narrow navigation column, a flexible report column, and a
context column that appears only when it contains relevant coverage, sources,
or limitations. Tablet collapses navigation to horizontal tabs. Mobile places
the prompt first, then the report, with provenance and local utilities in
disclosures. No view has horizontal overflow.

### Report structure

The result is a document with sections, not one oversized bordered card:

1. **Asset header:** ticker, company name, exchange, currency, observed price,
   daily context, provider, and `as_of`.
2. **Price history:** the primary chart with readable start/end labels and no
   raw floating-point tails.
3. **Key metrics:** four to six observed valuation and operating metrics.
4. **Fundamentals:** latest revenue, operating income, net income, free cash
   flow, cash, and debt where present, followed by compact historical rows.
5. **Earnings and consensus:** upcoming/recent event and analyst consensus,
   clearly labeled as observed data rather than advice.
6. **Filings:** recent official SEC links.
7. **Directly relevant news:** at most three headlines.
8. **Context column/disclosure:** coverage, actual successful sources, fallback
   notes, missing sections, and export actions.

Warnings appear beside the affected section in one sentence. Technical details
are available in an optional disclosure, but provider exception strings never
dominate the report summary.

### Local utilities

Watchlist and saved research remain browser-local and bounded. The watchlist is
a launcher, not a background scanner. A saved item may show the last observed
price and timestamp already present in its saved payload, but it does not
silently refresh or create portfolio state. JSON and CSV exports keep canonical
values and provenance.

## File boundaries

Expected implementation areas:

- `app/trading/research/openbb_client.py`: endpoint-specific provider attempts,
  metrics, quote, filings, earnings scope/filtering, safe errors;
- `app/trading/research/canonical.py`: quote and filings models plus observed
  valuation fields;
- `app/trading/research/normalizers.py`: provider aliases, latest-period quality,
  earnings schema, metrics, quote, filings, and news relevance;
- `app/trading/research/service.py`: selective fetching and fallback provenance;
- `app/trading/research/orchestration.py`: section plans with independent
  provider scopes;
- report/relevance/serialization modules: expose the new canonical evidence
  without calculating in the UI;
- `app/main.py` and request/response models: retain bounded authenticated routes;
- `app/static/index.html`, `styles.css`, `app.js`, and `sw.js`: editorial UI and
  updated static asset caching;
- focused trading, endpoint, static UI, and browser-level tests;
- research and UI contract documentation.

No financial data is written to ChromaDB, `jarvis_sessions.json`, conversation
history, or localStorage beyond the already bounded saved presentation payload.

## Testing and acceptance

Implementation follows fixture-first TDD. Standard tests use no network or
credentials.

### Provider and canonical tests

- endpoint-specific provider order, explicit override behavior, and fallback
  provenance;
- FMP calendar field mapping, exact symbol filtering, and independent bounded
  date window;
- SEC/FMP/Yahoo statement aliases, empty-row removal, and latest-period missing
  fields;
- metrics, quote, filing, news-relevance, and macro transformations;
- fallback notices do not falsely mark complete returned data partial;
- entitlement and configuration errors expose stable safe messages;
- serialization preserves `None`, provider, `as_of`, `retrieved_at`, and units.

### API and UI tests

- authenticated provider, macro, direct research, and chat response contracts;
- no credential values or raw provider subscription URLs in responses;
- semantic report headings and presentation-only rendering;
- compact currency, ratio, percentage, and date formatting;
- empty, loading, complete, partial, fallback, and failed-section states;
- keyboard focus, accessible names, live regions, and reduced motion;
- desktop, tablet, and mobile composition without horizontal overflow;
- no translucent panels, backdrop filters, decorative orb, or uppercase/HUD
  treatment.

### Live verification

After unit and full-suite tests pass, run bounded opt-in probes against only the
configured free-tier providers. Verify an NVDA asset report, an equity
comparison, BTC/ETH research, historical research, relationship analysis, and
macro context in the local browser. Live probes report provider, row count,
field coverage, fallback, and failure code only; they never print credentials
or persist raw provider payloads.

## Non-goals

- investment recommendations or buy/sell ratings;
- generated price targets or inferred missing ratios;
- portfolio tracking, holdings, P&L, alerts, scanning, trading, or execution;
- scraping provider websites or bypassing free-tier restrictions;
- React or another frontend framework;
- background provider health polling;
- LLM-based news relevance or financial calculations.

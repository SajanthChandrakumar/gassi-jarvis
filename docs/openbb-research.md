# OpenBB Research Backbone (Phase 1)

## Boundary

`app.trading.research.OpenBBResearchClient` is Jarvis' only Phase-1 boundary
to OpenBB. `main.py`, `agent.py`, ChromaDB, session state, and Gemini do not
fetch, validate, or interpret financial provider data. Each call returns
`ResearchData`: requested symbol, asset type, category, supplying provider,
UTC retrieval time, requested date range, raw rows, sanitized provider warnings,
and the ordered provider attempts made for that endpoint.

## Supported interface

| Method | OpenBB route | Default provider | Data |
|---|---|---|---|
| `get_price_history(..., asset_type="equity")` | `equity.price.historical` | `yfinance` | Equity/ETF OHLCV |
| `get_price_history(..., asset_type="crypto")` | `crypto.price.historical` | `yfinance` | Crypto-pair OHLCV and volume |
| `get_equity_quote` | `equity.price.quote` | `yfinance`, then configured FMP | Current quote snapshot |
| `get_company_profile` | `equity.profile` | configured FMP, then `yfinance` | Raw company/ETF profile fields |
| `get_financial_statements` | `equity.fundamental.{income,balance,cash}` | SEC, configured FMP, then `yfinance` | Raw financial statements |
| `get_fundamental_metrics` | `equity.fundamental.metrics` | configured FMP, then `yfinance` | Observed valuation metrics |
| `get_earnings_calendar` | `equity.calendar.earnings` | configured FMP | Symbol-filtered 44-day calendar window |
| `get_company_filings` | `equity.fundamental.filings` | SEC | Recent 10-K, 10-Q, and 8-K filings |
| `get_company_news` | `news.company` | `yfinance` | Direct-mention company-news records |
| `get_estimates_consensus` | `equity.estimates.consensus` | `fmp` when configured, otherwise `yfinance` | Observed analyst-consensus fields |
| `get_macro_series` | `economy.fred_series` or `economy.indicators` | configured FRED, then semantic EconDB fallback | Interpretable macro observations |

For canonical crypto identifiers such as `BTC` or `ETH`, the yfinance request
adapter uses the provider-required `BTC-USD` or `ETH-USD` pair while retaining
the canonical asset identity. Asset reports and comparisons request the
crypto-specific canonical section only; historical and relationship workflows
continue to request their price series directly. This prevents provider-specific
pair syntax and equity-only sections from leaking into the research models or
breaking crypto/benchmark analysis.

OpenBB 4.7.2 is intentionally used through its supported `from openbb import
obb` interface. The `openbb` package currently bundles the OpenBB routers and
provider extensions, including the default `yfinance` and `econdb` connectors;
no separate provider package is pinned in this repository.

## Dependency impact

Phase 1 adds one direct package: `openbb==4.7.2`. Its published distribution
brings the official OpenBB routers and provider extensions as transitive
dependencies; this is required by OpenBB's supported top-level Python
interface, rather than a Jarvis-specific installation of every provider.
Jarvis keeps `yfinance` and `econdb` as credential-free defaults. When their
credentials are present, FMP, Benzinga, FRED, and Tiingo are selected only for
the bounded routes described below.

OpenBB Core 1.6.13 requires FastAPI 0.136.3 and Uvicorn below 0.41, so the
project pins were aligned to `fastapi==0.136.3` and `uvicorn==0.40.0`. No data
provider API key or additional provider package is added directly by Jarvis.

## Provider configuration and credentials

The default providers can be overridden for a call or configured through:

| Variable | Default |
|---|---|
| `JARVIS_OPENBB_EQUITY_PROVIDER` | `yfinance` |
| `JARVIS_OPENBB_CRYPTO_PROVIDER` | `yfinance` |
| `JARVIS_OPENBB_MACRO_PROVIDER` | `fred` with `FRED_API_KEY`, otherwise `econdb` |
| `JARVIS_OPENBB_NEWS_PROVIDER` | `benzinga` with `BENZINGA_API_KEY`, otherwise `yfinance` |
| `JARVIS_OPENBB_ESTIMATES_PROVIDER` | `fmp` with `FMP_API_KEY`, otherwise `yfinance` |
| `JARVIS_OPENBB_PRICE_FALLBACK_PROVIDER` | `tiingo` with `TIINGO_TOKEN`, otherwise unset |

`yfinance` and `econdb` are intended to work without Jarvis-managed API keys.
Other installed OpenBB providers may require credentials in OpenBB's supported
settings/environment configuration (for example FMP, FRED, Polygon, Alpha
Vantage, Intrinio, Tiingo, Tradier, or TradingEconomics). Credentials never
belong in repository files, ChromaDB, sessions, or the financial ledger.

Provider/endpoint failures are exposed as structured adapter exceptions: missing
credential, rate limit, unsupported endpoint, invalid symbol, no data, or
generic provider failure. Empty upstream results raise `ResearchNoDataError`;
they are never silently represented as successful empty data.

## Provider readiness

`app.trading.research.provider_status` exposes a read-only, non-secret
readiness contract through `GET /api/research/providers`. It reports whether a
credential is present, which coverage is already wired into Jarvis, and which
coverage remains a future integration. It does not inspect key values, validate
them with a network call, or imply that a configured provider has returned
data.

Provider state uses only `built_in`, `configured`, and `not_configured`.
Configuration is not a liveness claim. Yahoo Finance, SEC, and EconDB are
built in. FMP adds bounded profile, statements, metrics, estimates, and earnings
coverage; FRED adds five US macro series; Tiingo is a price fallback. Benzinga
may be configured but is not in the current default route because the verified
free-tier company-news response was empty. Any provider may still return an
entitlement, rate-limit, empty-data, or endpoint error.

Each endpoint owns an ordered fallback chain. Failed and successful attempts
are preserved structurally in provenance; raw exception text and subscription
URLs are not returned to the UI. Explicit per-call provider overrides never
fall through to another provider.

News is limited to three records that directly mention the ticker or a
meaningful company-name token. Earnings uses exactly 14 days before through 30
days after the request date and discards calendar rows for other symbols. Macro
context consists of CPI inflation (`CPIAUCSL`, year-over-year percent),
unemployment (`UNRATE`), the federal funds rate (`FEDFUNDS`), the 10-year
Treasury yield (`DGS10`), and real-GDP growth (`GDPC1`, year-over-year percent).
EconDB substitutes only semantically equivalent inflation, unemployment, and
policy-rate series when FRED is unavailable.

## Caching and limitations

The Phase-1 adapter adds no cache. The Phase-2 canonical service owns the
documented in-process cache key, TTL, refresh, and stale-data behavior. Neither
cache is financial truth.

The developer-only probe is `python scripts/openbb_research_probe.py`. It
prints only provider, row count, non-empty field names, attempt outcomes, and
stable failure codes—never values, URLs, settings, credentials, or exception
strings.

Phase 1 intentionally does not add reports, relevance/ranking, portfolio
state, trades, paper trading, or live execution. Dedicated crypto derivatives
metadata and provider-neutral historical estimates remain unsupported; Jarvis
does not infer either from snapshots.

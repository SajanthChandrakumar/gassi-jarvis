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
| `get_price_history(..., asset_type="equity")` | `equity.price.historical` | `yfinance`, then configured FMP | Equity OHLCV |
| `get_price_history(..., asset_type="etf")` | `equity.price.historical` | `yfinance` | ETF OHLCV; no paid-provider fallback is activated |
| `get_price_history(..., asset_type="crypto")` | `crypto.price.historical` | `yfinance` | Crypto-pair OHLCV and volume |
| `get_fund_info` | `etf.info` | `yfinance` | Provider-returned ETF description, listing currency/exchange, NAV, total assets, and dividend fields |
| `get_equity_quote` | `equity.price.quote` | `yfinance`, then configured FMP | Current quote snapshot |
| `get_company_profile` | `equity.profile` | configured FMP, then `yfinance` | Raw company/ETF profile fields |
| `get_financial_statements` | `equity.fundamental.{income,balance,cash}` | SEC, configured FMP, then `yfinance` | Raw financial statements |
| `get_fundamental_metrics` | `equity.fundamental.metrics` | configured FMP, then `yfinance` | Observed valuation metrics |
| `get_earnings_calendar` | `equity.calendar.earnings` | configured FMP | Symbol-filtered 44-day calendar window |
| `get_company_filings` | `equity.fundamental.filings` | SEC | Recent 10-K, 10-Q, and 8-K filings |
| `get_company_news` | `news.company` | `yfinance` | Direct-mention company-news records |
| `get_estimates_consensus` | `equity.estimates.consensus` | `fmp` when configured, otherwise `yfinance` | Observed analyst-consensus fields |
| `get_macro_series` | `economy.fred_series`, `economy.indicators`, or local OpenBB `SnbMacroFetcher` | US: configured FRED, then semantic EconDB fallback; CH: explicit SNB | Interpretable macro observations |

For canonical crypto identifiers such as `BTC` or `ETH`, the yfinance request
adapter uses the provider-required `BTC-USD` or `ETH-USD` pair while retaining
the canonical asset identity. Asset reports and comparisons request the
crypto-specific canonical section only; historical and relationship workflows
continue to request their price series directly. This prevents provider-specific
pair syntax and equity-only sections from leaking into the research models or
breaking crypto/benchmark analysis.

Explicit Yahoo-style compact crypto pair symbols such as `BTCUSD` are adapted
to `BTC-USD` for price requests while the selected canonical symbol remains
`BTCUSD`. ETF metadata uses only the installed Yahoo route by default. Fields
not returned by that route are not inferred. Small local typed OpenBB Fetchers
expose existing Yahoo-library capabilities for expense ratio, top holdings,
sectors and crypto market cap/supply. They do not mutate OpenBB's provider
registry or add dependencies. Missing geography, full portfolio, observation
dates and fund asset-value currency remain explicit. Yahoo supplementary calls
have bounded request timeouts; failures preserve independently available data.

The table above describes configurable low-level adapter defaults. The German
terminal deliberately constructs free Yahoo/SEC market-data settings, even if
an FMP key exists. Its existing separate macro configuration is preserved.

Jarvis uses OpenBB 4 through its supported `from openbb import obb` interface.
The core package provides this interface; the required routers and provider
extensions are installed separately at their tested versions.

## Dependency impact

Both runtime requirement files pin OpenBB Core 1.6.13, the equity, crypto,
economy, and news routers, and five provider extensions: Yahoo Finance, SEC,
EconDB, FMP, and FRED. These are the component versions tested with the former
OpenBB 4.7.2 installation; this is not an upgrade to OpenBB 5.

Swiss macro data uses a small repository-local OpenBB Core Fetcher, not a
sixth installed provider package. It reuses the standard economic-indicator
models, request helper, and Fetcher pipeline without adding dependencies.

The all-provider `openbb` metapackage is no longer installed because it pulls
in unwanted provider extensions. Benzinga and Tiingo were removed on
2026-10-02. Their credentials no longer enable any Jarvis route or status entry.

OpenBB Core 1.6.13 requires FastAPI 0.136.3 and Uvicorn below 0.41, so the
project retains `fastapi==0.136.3` and `uvicorn==0.40.0`.

## Provider configuration and credentials

Each endpoint uses the bounded chain above. Optional credentials enable:

| Variable | Coverage |
|---|---|
| `FMP_API_KEY` | Price/quote fallback, profiles, statements, metrics, estimates, and earnings |
| `FRED_API_KEY` | US macro context |

Yahoo Finance, SEC, EconDB, and the Swiss SNB Fetcher do not need Jarvis-managed API keys. The adapter
also accepts an explicit per-call provider override for a supported installed
provider; `JARVIS_OPENBB_*_PROVIDER` environment overrides are not implemented.
Credentials never belong in repository files, ChromaDB, sessions, or the
financial ledger.

For an existing local virtual environment, installing the new requirements
alone does not uninstall old packages. Remove the former metapackage and the
two removed extensions, then install the pinned components and rebuild the SDK:

```bash
.venv/bin/python -m pip uninstall -y openbb openbb-benzinga openbb-tiingo
.venv/bin/python -m pip install --force-reinstall --no-deps openbb-core==1.6.13
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import openbb; openbb.build()'
```

The Core reinstall restores shared `openbb` import files that uninstalling the
old metapackage can remove. It is unnecessary for a fresh virtual environment.

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
Configuration is not a liveness claim. Yahoo Finance, SEC, EconDB, and SNB are
built in. FMP adds bounded profile, statements, metrics, estimates, and earnings
coverage and price/quote fallbacks; FRED adds the configured US macro
series. Any provider may still return an
entitlement, rate-limit, empty-data, or endpoint error.

Each endpoint owns an ordered fallback chain. Failed and successful attempts
are preserved structurally in provenance; raw exception text and subscription
URLs are not returned to the UI. Explicit per-call provider overrides never
fall through to another provider.

News is limited to three records that directly mention the ticker or a
meaningful company-name token. Earnings uses exactly 14 days before through 30
days after the request date and discards calendar rows for other symbols.

Macro context requests the same five slots for two explicitly separated
countries:

| Country | Inflation | Unemployment | Policy-rate slot | 10-year yield | Real GDP growth |
|---|---|---|---|---|---|
| United States | `CPIAUCSL`, `pc1` | `UNRATE` | `FEDFUNDS` | `DGS10` | `GDPC1`, `pc1` |
| Switzerland | National CPI, BFS via SNB | Registered unemployment, SECO via SNB | Official SNB policy rate | SNB 10-year Confederation spot yield | Real GDP, SECO via SNB, QoQ |

The endpoint returns Switzerland first and the United States second. Each
country has independent `series` and `failures`; the legacy top-level fields
remain the US group. EconDB substitutes only semantically equivalent US
inflation, unemployment, and policy-rate series when FRED is unavailable.

### Official Swiss definitions (2026-10-04)

The old Swiss FRED proxies have been replaced. `provider="snb"` uses only
allowlisted public SNB CSV datasets, with explicit dimensions checked again
after download. BFS/SECO data is republished by SNB; it is not fetched directly
from either agency and can lag their latest releases.

| Indicator | SNB cube and dimensions | Definition / unit | Official source |
|---|---|---|---|
| Inflation | `plkopr`, `D0(VVP)` | National CPI, change from same month a year earlier; `% YoY` | [BFS via SNB](https://data.snb.ch/en/topics/uvo/cube/plkopr?dimSel=D0%28VVP%29) |
| Unemployment | `amarbma`, `D0(T1)` | Registered unemployment, not seasonally adjusted and not ILO; `%` | [SECO via SNB](https://data.snb.ch/en/topics/uvo/cube/amarbma?dimSel=D0%28T1%29) |
| Policy rate | `snbgwdzid`, `D0(LZ)` | Official SNB policy rate, daily; `%` (zero is valid) | [SNB](https://data.snb.ch/en/topics/snb/cube/snbgwdzid?dimSel=D0%28LZ%29) |
| 10-year yield | `rendeiduebm`, `D0(CHF),D1(10J)` | Confederation zero-coupon spot yield, end of month, 2025 methodology; `%` | [SNB](https://data.snb.ch/en/topics/ziredev/cube/rendeiduebm?dimSel=D0%28CHF%29%2CD1%2810J%29) |
| Real GDP growth | `gdprpq`, `D0(VVK),D1(BBIPS)` | Previous-quarter change, seasonally/calendar/sports-event adjusted; `% QoQ` | [SECO via SNB](https://data.snb.ch/en/topics/uvo/cube/gdprpq?dimSel=D0%28VVK%29%2CD1%28BBIPS%29) |

The former `rendoblim` yield table ends in July 2025; its official footnote
links to `rendeiduebm`. Jarvis uses the current methodology rather than
continuing the discontinued series. Published percentage values are retained
without reapplying `pc1`, annualizing GDP, or replacing missing observations.
Swiss QoQ GDP and US YoY GDP have different comparison horizons.

Each Swiss series retains its definition, original period (`YYYY-MM`,
`YYYY-Qn`, or daily date), source name/link, dataset publication time in UTC,
and retrieval provenance. Monthly/quarterly `as_of` represents period end,
not the first day of the period or the retrieval time. The PWA displays both
period and publication date. Publication is dataset-level metadata, not a
claim about when every individual observation was first released.

Dashboard requests cover two years; the Fetcher accepts at most ten years
and no future date range. HTTP redirects, malformed/ambiguous CSV, mismatched
cubes/dimensions, and non-finite values are rejected. Empty cells are skipped,
not converted to zero. Failures stay SNB failures with no FRED proxy fallback.
The source portal has no rate-limit guarantee encoded here; bounded requests
and the existing in-process canonical cache are retained.

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

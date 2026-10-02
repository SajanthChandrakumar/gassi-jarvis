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
| `get_price_history(..., asset_type="equity")` | `equity.price.historical` | `yfinance`, then configured FMP | Equity/ETF OHLCV |
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

Jarvis uses OpenBB 4 through its supported `from openbb import obb` interface.
The core package provides this interface; the required routers and provider
extensions are installed separately at their tested versions.

## Dependency impact

Both runtime requirement files pin OpenBB Core 1.6.13, the equity, crypto,
economy, and news routers, and five provider extensions: Yahoo Finance, SEC,
EconDB, FMP, and FRED. These are the component versions tested with the former
OpenBB 4.7.2 installation; this is not an upgrade to OpenBB 5.

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
| `FRED_API_KEY` | US and Swiss macro context |

Yahoo Finance, SEC, and EconDB do not need Jarvis-managed API keys. The adapter
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
Configuration is not a liveness claim. Yahoo Finance, SEC, and EconDB are
built in. FMP adds bounded profile, statements, metrics, estimates, and earnings
coverage and price/quote fallbacks; FRED adds the configured US and Swiss macro
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
| Switzerland | `CP0000CHM086NEST`, `pc1` | `LRUNTTTTCHQ156S` | `IRSTCI01CHM156N` | `IRLTLT01CHM156N` | `CLVMNACSAB1GQCH`, `pc1` |

The endpoint returns Switzerland first and the United States second. Each
country has independent `series` and `failures`; the legacy top-level fields
remain the US group. EconDB substitutes only semantically equivalent US
inflation, unemployment, and policy-rate series when FRED is unavailable.

The Swiss inflation slot is Eurostat HICP, the unemployment slot is the OECD
labour-force measure, and GDP is transformed to year-over-year growth. These
definitions must not be presented as the Swiss national CPI, SECO registered
unemployment, or SECO quarter-over-quarter GDP. The configured Swiss
`IRSTCI01CHM156N` series is an OECD call-money/interbank rate, not the official
SNB policy-rate series; it can therefore be explicitly unavailable in the
two-year request window. Jarvis does not fabricate an SNB value to fill that
gap.

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

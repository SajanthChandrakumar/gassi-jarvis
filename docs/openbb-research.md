# OpenBB Research Backbone (Phase 1)

## Boundary

`app.trading.research.OpenBBResearchClient` is Jarvis' only Phase-1 boundary
to OpenBB. `main.py`, `agent.py`, ChromaDB, session state, and Gemini do not
fetch, validate, or interpret financial provider data. Each call returns
`ResearchData`: requested symbol, asset type, category, supplying provider,
UTC retrieval time, requested date range, raw rows, and provider warnings.

## Supported interface

| Method | OpenBB route | Default provider | Data |
|---|---|---|---|
| `get_price_history(..., asset_type="equity")` | `equity.price.historical` | `yfinance` | Equity/ETF OHLCV |
| `get_price_history(..., asset_type="crypto")` | `crypto.price.historical` | `yfinance` | Crypto-pair OHLCV and volume |
| `get_company_profile` | `equity.profile` | `yfinance` | Raw company/ETF profile fields |
| `get_financial_statements` | `equity.fundamental.{income,balance,cash}` | `yfinance` | Raw financial statements |
| `get_earnings_calendar` | `equity.calendar.earnings` | caller-selected | Raw earnings-calendar rows |
| `get_macro_series` | `economy.indicators` | `econdb` | Economic indicators, e.g. CPI/GDP |

OpenBB 4.7.2 is intentionally used through its supported `from openbb import
obb` interface. The `openbb` package currently bundles the OpenBB routers and
provider extensions, including the default `yfinance` and `econdb` connectors;
no separate provider package is pinned in this repository.

## Dependency impact

Phase 1 adds one direct package: `openbb==4.7.2`. Its published distribution
brings the official OpenBB routers and provider extensions as transitive
dependencies; this is required by OpenBB's supported top-level Python
interface, rather than a Jarvis-specific installation of every provider.
Jarvis uses only `yfinance` and `econdb` by default in this phase.

OpenBB Core 1.6.13 requires FastAPI 0.136.3 and Uvicorn below 0.41, so the
project pins were aligned to `fastapi==0.136.3` and `uvicorn==0.40.0`. No data
provider API key or additional provider package is added directly by Jarvis.

## Provider configuration and credentials

The default providers can be overridden for a call or configured through:

| Variable | Default |
|---|---|
| `JARVIS_OPENBB_EQUITY_PROVIDER` | `yfinance` |
| `JARVIS_OPENBB_CRYPTO_PROVIDER` | `yfinance` |
| `JARVIS_OPENBB_MACRO_PROVIDER` | `econdb` |

`yfinance` and `econdb` are intended to work without Jarvis-managed API keys.
Other installed OpenBB providers may require credentials in OpenBB's supported
settings/environment configuration (for example FMP, FRED, Polygon, Alpha
Vantage, Intrinio, Tiingo, Tradier, or TradingEconomics). Credentials never
belong in repository files, ChromaDB, sessions, or the financial ledger.

Provider/endpoint failures are exposed as structured adapter exceptions: missing
credential, rate limit, unsupported endpoint, invalid symbol, no data, or
generic provider failure. Empty upstream results raise `ResearchNoDataError`;
they are never silently represented as successful empty data.

## Caching and limitations

Jarvis adds no cache in Phase 1. OpenBB and individual providers may use their
own short-lived caches; such caches are not financial truth and callers can use
a provider override when they need a different source. Phase 2 should define
any Jarvis-level cache key, TTL, invalidation, and freshness policy.

The developer-only probe is `python scripts/openbb_research_probe.py`. It
fetches NVDA prices/profile, BTC-USD prices, and US CPI without Gemini.

Phase 1 intentionally does not add reports, relevance/ranking, indicators,
statistics, backtesting, portfolio state, trades, paper trading, or live
execution. More provider coverage, earnings estimates/consensus, dedicated
crypto market metadata, and normalized cross-provider schemas remain future
work.

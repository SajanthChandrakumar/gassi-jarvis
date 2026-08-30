# Historical Research (Phase 5)

`HistoricalResearchService` studies supplied canonical `PriceSeries`; it never
fetches data or invokes Gemini. It provides explicit event studies, simple
return-threshold and historically constrained volatility events, forward-return
summaries, VectorBT-backed drawdown episodes, and regime sample construction.

Forward returns use only `close[event + horizon] / close[event] - 1`; incomplete
end-of-series windows are excluded and reported as warnings. Events are defined
from data available at their timestamp. In particular, volatility events compare
the current rolling volatility only with preceding rolling observations, not a
future full-sample distribution.

Phase 5 constructs historical observations and summaries. It does not perform
hypothesis tests, correlations, OLS, or significance inference; those remain
the responsibility of Phase 6. VectorBT is isolated to drawdown record
extraction and no VectorBT object is exposed by the public API.

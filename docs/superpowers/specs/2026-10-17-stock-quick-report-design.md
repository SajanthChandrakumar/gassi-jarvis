# Stock quick report — approved design

Approved by the user in chat on 2026-10-17, followed by an explicit request to implement with Luna XHigh subagents.

## Goal and scope

Enter a stock or ETF ticker and receive a compact data-first report: closing-price chart, observed financial metrics, sourced findings, company news and filings. Jarvis remains the supplementary assistant. The user interprets, decides and executes; this feature provides no advice, forecasts, targets or trades.

Extend the existing native PWA and canonical OpenBB report path. No new provider, runtime dependency, UI framework, realtime feed or automatic Gemini summary. Existing chat, voice, HitL, compare/history/relationship workflows and Swiss/US macro context remain accessible. Preserve the current restrained styling and English interface.

## User-visible behavior

- The primary form submits a ticker and timeframe directly to `/api/research/run`, independent of Gemini. Chat/voice have a separate visible assistant entry.
- Compact report header: symbol/name, observed price, supplied currency, as-of and data quality. Unknown currency is explicit, never assumed USD.
- A larger closing-price line chart has date and price axes, mouse/touch/keyboard inspection and an expandable table with the exact displayed observations. Use real timestamps on the x axis; do not fabricate missing points.
- Group financial, valuation and earnings metrics in expandable sections. Show the first three existing key findings, with the remaining findings expandable; retain evidence, comparisons, periods and sources without rescoring or invented interpretation.
- Show up to three existing company news records with dates/publishers/links and up to five filings. No news sentiment calculation.
- An EPS actual-versus-estimate chart is shown only for observations containing both finite values from the same reporting period. Missing is never zero; true zero and negative numbers remain valid.
- Swiss/US macro data remains separate context; do not infer stock-specific macro effects.
- Desktop places chart and supporting information side-by-side; mobile stacks them without horizontal overflow. Shrink the oversized entry area and keep the report before utility sections.
- Existing coverage/failures/staleness remain visible. A failed or superseded request must not present old results as a successful current report.

## Data/API behavior

- Extend the existing request timeframe values with `1m` and `3m`; keep `6m`, `1y`, `2y`, `5y`, `all`, and the default `1y`.
- At most 180 original closing-price observations, sampled uniformly by input index across the whole available scope, preserving first/last observations. No averaging/interpolation. Expose additive optional `price_history_total` metadata so the UI can truthfully identify sampling. Older stored reports without this field remain renderable.
- Financial calculations stay server-side; JavaScript performs formatting and chart geometry only. Preserve Decimal serialization, identity, provenance, periods, warnings and missing-value semantics.

## Acceptance

Test timeframe compatibility, full-span deterministic sampling, true zero, missing/unknown currency, absent news, provider failures, stale/partial reports, flat/single-point prices and matched/missing EPS values. Prove the direct path works with Gemini unavailable. Run all tests and real browser checks for search, timeframes, charts, findings, sources and desktop/mobile. Update README/UI contract and record a screenshot. No push, merge, branch deletion or deployment is authorized by this implementation request.

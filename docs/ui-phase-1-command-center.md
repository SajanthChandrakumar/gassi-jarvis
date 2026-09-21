# Jarvis Editorial Command Center

## Direction

The Command Center is a command-first research workspace. Its hierarchy is
research prompt, recent/local context, canonical report, and supporting source
detail. Opaque near-black and graphite surfaces, hairline dividers, generous
spacing, and type establish hierarchy. Cyan is reserved for focus and current
activity. There is no glass, blur, panel gradient, decorative orb, glowing
frame, or HUD copy.

The frontend remains native HTML, CSS, and JavaScript. `index.html` owns the
semantic shell, `styles.css` owns the design system and responsive composition,
and `app.js` owns bounded interaction and presentation. No React, bundler,
client router, or runtime dependency is required.

## Layout

The research command is the first substantial element on every viewport. On
desktop, the lower workspace uses a compact mode rail, a wide report column,
and a narrow provenance/limitations column. Tablet moves the context sections
below the main column. Mobile uses a single readable column, keeps the prompt
immediately reachable, and has no horizontal overflow.

The empty state exposes useful existing capabilities without fake market data:
up to six locally saved reports, a local symbol watchlist, two country-grouped
macro panels with five slots each, provider configuration coverage, and the
four validated research modes. Local records stay in `localStorage`; they are
not financial truth and do not enter Jarvis sessions.

## Research rendering

The focused workflow calls `POST /api/research/run`; natural-language chat and
voice continue to call `POST /api/chat`. HitL approval remains unchanged.
Finance actions render only `research_payload` as the authoritative evidence
document:

- market snapshot from canonical quote fields;
- bounded price history with presentation-only SVG scaling;
- observed fundamentals, valuation, earnings, and analyst-consensus metrics;
- at most five recent 10-K, 10-Q, or 8-K filings;
- at most three backend-filtered direct company-news records;
- section availability, freshness, missing fields, stable failures, supplying
  sources, and ordered provider attempts;
- comparison, event-study, correlation, and beta output in their own document
  structures.

The browser formats supplied values by explicit metric kind. It does not
calculate returns, moving averages, valuation ratios, rankings, sentiment,
recommendations, or substitute missing evidence. JSON and CSV exports contain
only fields already present in the canonical response.

## Provider and macro state

`GET /api/research/providers` describes configuration only with `built_in`,
`configured`, and `not_configured`. It never labels a credential as live,
validates a key, or returns its value.

`GET /api/research/macro` fetches five independent two-year scopes for each of
Switzerland and the United States and returns only the latest observation for
inflation, unemployment, policy rate, 10-year government yield, and real-GDP
growth. The `countries` collection keeps the groups and failures separate;
legacy top-level fields still expose the US group. Every observation retains
its unit, as-of date, source, freshness, and quality. Failures remain explicit;
the UI never substitutes placeholder numbers. Wide layouts show the country
panels side by side and narrow layouts stack them.

## Accessibility and delivery

The page uses semantic landmarks, real labels, native forms, visible focus
rings, an `aria-live` activity state, and a polite report feed. Motion is
limited to loading and state transitions and is effectively disabled by
`prefers-reduced-motion`. The service worker versions the HTML shell, CSS,
JavaScript, manifest, and icons while leaving `/api/*` network-only.

## Scope boundary

There is no portfolio, scanner, alert engine, trade execution, server-side
watchlist, or investment recommendation. The current UI maximizes the evidence
already supported by the read-only research backend; capabilities without a
canonical contract remain absent rather than simulated.

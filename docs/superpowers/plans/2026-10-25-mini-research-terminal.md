# Mini research terminal — implementation record

Approved scope: German equity / ETF / crypto entry points, explicit instrument
search by name/ticker/ISIN, compact evidence-backed reports, free-first data,
Swiss/European/US coverage where supported. Preserve deterministic calculations,
provenance, missing-data semantics and existing research workflows.

## Work packages

1. Search and routing: authenticated search endpoint, explicit selected identity,
   compatibility with legacy ticker requests. Owner: search_backend.
2. Data: ETF/crypto canonical data and report fields, supported free OpenBB routes,
   explicit gaps and partial reports. Owner: asset_data.
3. UI: German class entry points, accessible search, compact reports and followups,
   secondary system panels. Owner: german_ui.
4. Integration: full suite, independent review, browser verification and live
   provider probes when network access permits. Owner: root.

## Decisions and progress

- Reuse current `codex/stock-quick-report` feature branch and clean checkout,
  following the user's established preference to work in this folder.
- All delegated agents use `gpt-6-luna` with `xhigh`, as requested.
- No commits, pushes or deployment are part of this implementation request.
- Search response: `{query, results: [{symbol, name, exchange, currency,
  asset_type, isin}]}`. No guessed match for an unknown ISIN.
- Obsidian vault is unset; user replied "ist egal" to the path question.
  Keep this repository record instead of guessing an external destination.
- Implementation in progress. Validation results will be recorded after integration.
- Baseline: 439 tests passed, two existing deprecation warnings.
- Ruling: installed OpenBB lacks free international ETF/crypto search. Add a
  small local OpenBB Fetcher using the already-installed Yahoo library for
  instrument discovery, instead of silently selecting paid provider defaults.
  Market data and calculations continue through the canonical pipeline.
- Public lookup preflight: raw urllib received HTTP 429; the installed Yahoo
  library successfully returned the observed NVDA identity. Missing lookup
  currency/ISIN remain null, never inferred from a guessed exchange.
- Statistical returns now disclose unverified dividend/split adjustment and
  unconverted source currencies; focused tests passed (10).

## Live free-provider sample (2026-10-25)

Ran the actual deterministic asset-report pipeline with explicit free default
provider settings (Yahoo, SEC; no configured FMP/Intrinio fallback). This is a
local provider check, not a deployment or a completeness certification.

| Instrument | Kind | Retained source prices | Outcome |
| --- | --- | ---: | --- |
| NVDA | US equity | 250 | Partial; earnings not configured, news unavailable |
| NESN.SW | Swiss equity | 249 | Partial; some company-event sections unavailable |
| SAP.DE | European equity | 252 | Partial; some company-event sections unavailable |
| VWCE.DE | UCITS ETF | 251 | Partial; fees and holdings missing |
| SPY | US ETF | 250 | Partial; fees and holdings missing |
| BTC | Crypto | 365 | Partial; market cap and supply unavailable |

All six produced structured reports and observed price histories. Prices were
not copied into repository fixtures. Review identified follow-up fixes before
acceptance: partial flags must include non-essential provider failures; fund
asset-value currency must not be inferred from listing currency; distribution
yield must not imply a distribution schedule.

Live lookup also returned observed matches for NVIDIA, Nestlé, SAP.DE, SPY,
Bitcoin, the UCITS ISIN IE00BK5BQT80 and Swiss ISIN CH0038863350. Lookup
currency and returned ISIN were absent in these Yahoo responses and remain
null. The UCITS ISIN returned the observed London listing VWRA.L; no German
listing was synthesized. All result choices require explicit user selection.

## Integration and final provider recheck

- Added local OpenBB Fetchers for observed Yahoo ETF fees, crypto market
  cap/supply, and top holdings/sectors. No dependency upgrades or registry
  monkey-patching. Yahoo metadata extensions use bounded network requests.
- SPY now supplies an observed 0.0945% expense ratio, ten top holdings and eleven
  sector weights. VWCE.DE supplies ten top holdings and eleven sector weights,
  but the fee remains absent. No country exposure is inferred from positions.
- BTC now supplies observed USD market cap, circulating/total/max supply.
  Its final data report met the requested market-data essentials; this does not
  constitute a protocol-security or tokenomics assessment.
- All three equity reports still explicitly identify source/event-data gaps.
- AUM/NAV and accounting currencies remain unknown unless separately supplied.
  Known metric periods are preserved; incompatible comparison units, currencies
  and periods are flagged. Same-ticker comparison legs retain positional identity.
- Terminal reports use explicitly free default market sources even if an FMP
  key exists. Low-level provider configuration remains available and separate
  macro configuration is preserved.
- Independent backend review raised comparison dimensions, identity fallback,
  crypto units and network timeout concerns; focused regression checks cover
  the fixes. Final browser and full-suite results follow below.

## Completion and verification

All four implementation tasks are complete. Final verification: 491 tests
passed with two existing dependency deprecation warnings; JavaScript syntax
and Git whitespace checks passed. Independent final review found no remaining
concrete regressions.

Desktop and mobile browser checks covered real reports, keyboard selection,
refresh, and expanded financial tables. At a 390px viewport the expanded table
stays inside its scrolling container without widening the page. Six public
instruments were checked against live free providers, with missing fields
retained explicitly. Browser evidence is saved outside the repository at
`/tmp/jarvis-mini-terminal-checks/jarvis-report.jpg`.

The work remains local and uncommitted; no push or deployment was performed.
Following the user's "ist egal" reply about the unavailable Obsidian vault,
this repository record serves as the project-note update.

## Browser feedback: concrete source limitations

Replaced repeated generic source-warning banners with deterministic German
explanations in the report and coverage details. The display now identifies
unsupported geographic exposure, the top-holdings subset and unknown observation
date, incomplete fund fields, and an empty current-quote response. Unmapped
messages remain available in one disclosure; duplicate notices are removed.
The partial-report banner names missing essentials only when the structured
report actually lists them. Provider data and availability states are unchanged.

Verified the regression first failed on the generic warning, then passed with
the fix. Full suite: 491 passed, two existing dependency warnings; JavaScript
syntax and whitespace checks passed. Confirmed the actual SPY report in the
browser at the user's narrow viewport. Static asset cache advanced to v13.

## Actual missing-data repair after user correction

The user clarified that the missing data itself should be repaired. The Yahoo
quote adapter now recovers an observed `regularMarketPrice` and its actual
`regularMarketTime` when `currentPrice` is absent/null, while preserving zero.
Null supplementary fields no longer overwrite observed profile currency.

A fixed, identity-checked local OpenBB Fetcher now retrieves the official SPY
page and daily holdings workbook from State Street. It supplies the source's
objective, benchmark, distribution frequency, sponsor/trustee, investment-region
classification, fee, listing identity, AUM/NAV and their currencies/dates,
NAV-based trailing distribution yield and all published holdings/sectors.
Requests, download size and expanded XLSX size are bounded; parsing uses the
standard library without new dependencies. Unsupported symbols do not trigger
issuer requests. Yahoo-specific observations remain separate with their own
provenance rather than being relabeled as issuer data. Cash rows without a
ticker remain present. Recovery attempts are retained in provenance.

Verified through the running browser against actual providers: SPY current
quote now has an observed 2026-10-23 timestamp; State Street supplies 505 holding
rows and eleven sectors dated 2026-10-22, the benchmark, quarterly frequency,
0.0945% fee, 0.99% distribution yield and explicitly denominated AUM/NAV.
The header retains the price date when metadata has a later observation date.
The separate Yahoo dividend observations also remain visible in report details.

Remaining limits are explicit: the additional issuer adapter currently covers
SPY only; country allocation percentages and a separately labeled replication
method/issuer are not supplied by this adapter. Sponsor and trustee are not
silently substituted for issuer. No complete international-ETF coverage is claimed.

Final validation: 509 tests passed with two existing dependency warnings;
JavaScript syntax and whitespace checks passed. Browser evidence is saved at
`/tmp/jarvis-mini-terminal-checks/actual-data-fixed.png`. Local preview restarted
with isolated temporary state and assets v14. No commit, push or deployment.

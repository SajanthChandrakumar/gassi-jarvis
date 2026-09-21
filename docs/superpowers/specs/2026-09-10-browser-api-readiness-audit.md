# Browser and API Readiness Audit Design

## Goal

Make the existing Jarvis MVP reliably usable from its PWA by verifying every
published browser flow and API contract, fixing only reproduced defects, and
preserving explicit partial/unavailable data states.

## Scope

- Verify static PWA delivery, runtime configuration, authentication, chat,
  task inbox, memory, research, macro context, Calendar states, and the Mac
  device lifecycle.
- Exercise asset, comparison, historical, and relationship research with live
  read-only providers while keeping structured payloads authoritative.
- Verify browser rendering, local watchlist/saved-research behavior, exports,
  responsive layout, and service-worker behavior.
- Keep user state safe by running live checks against temporary copies.

## Confirmed defect and design

Gemini can occasionally return neither text nor a function call for an
unambiguous task-inbox request. The inbox implementation itself works, but the
chat route currently turns that empty model response into a generic failure.

Add a narrow deterministic fallback at the empty-response boundary. It may
recognize only explicit German or English requests to capture a task or list
open tasks. It must not pre-empt a valid Gemini response, infer vague reminders,
or route unrelated memory requests. Regression tests will mock an empty Gemini
response and assert the real chat result and temporary inbox side effect.

## Constraints

- No financial recommendations, trading, portfolio actions, fabricated values,
  or LLM-calculated authoritative metrics.
- Preserve provenance, freshness, quality, missing values, and partial/failure
  warnings in research payloads and browser rendering.
- No changes to real sessions, Chroma data, task inbox, or device queue during
  verification.
- Screenshot, microphone, and app-opening checks require explicit user consent.

## Acceptance criteria

- Every OpenAPI route has a recorded success or expected error-path check.
- All four deterministic research modes return browser-renderable structured
  data and truthful limitations.
- Clear task capture/list prompts work even when Gemini returns an empty result.
- The complete automated suite passes, followed by a live API and browser run.

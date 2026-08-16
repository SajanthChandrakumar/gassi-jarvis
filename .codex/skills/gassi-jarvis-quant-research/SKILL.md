---
name: gassi-jarvis-quant-research
description: Build or change Gassi Jarvis financial research, including OpenBB data access, canonical research models, relevance, reports, historical/statistical research, and research-memory updates. Use for every trading/research phase or change under app/trading, docs research contracts, or tests/trading.
---

# Gassi Jarvis Quant Research

Build Jarvis as an evidence-backed quant-research assistant, not as an
autonomous trading bot. Follow the repository's established phase boundaries.

## Non-negotiable boundaries

- Keep `LLM != Quant Engine`. Gemini may orchestrate or present deterministic
  results, but must not calculate authoritative values, fill missing data,
  rank findings, invent facts, or override structured output.
- Keep provider access behind OpenBB and pass provider responses through the
  canonical research-data layer before higher-level use.
- Preserve asset identity, provider/provenance, `as_of`, `retrieved_at`,
  freshness, quality, availability, request scope, and `None` values. Never
  conflate zero, missing, unsupported, not requested, or upstream failure.
- Keep financial research in `app/trading/`; do not put research logic in
  `app/main.py` or `app/agent.py` except narrow orchestration.
- Do not introduce recommendations, price targets, automated trading,
  portfolio tooling, market scanning, or a later roadmap phase unless the user
  explicitly requests it.
- Preserve tested OpenBB dependency pins, notably the Uvicorn constraint,
  unless compatibility is verified and documented.

## Research workflow

1. Inspect the existing Phase-1–Phase-N implementation, tests, provenance,
   freshness, quality, missing-data semantics, cache behavior, and
   `architecture.md` before changing research code.
2. Reuse the smallest compatible deterministic layer. Do not duplicate an
   OpenBB capability without a concrete reason.
3. Separate factual data/evidence from interpretation. A structured finding or
   report must expose its metric, comparison, evidence, provenance, quality,
   confidence, and `as_of`.
4. Use deterministic, typed models and focused fixture-based tests. Standard
   tests must not need the internet or provider credentials.
5. Treat incomplete history, stale data, provider errors, and unsupported
   fields as explicit limitations. Lower confidence where appropriate; never
   fabricate a replacement.
6. For historical claims, event studies, backtests, or forward-return claims,
   use actual historical research (VectorBT where appropriate) and account for
   sample size, look-ahead bias, survivorship bias, outliers, and regimes.
7. Run the complete test suite, inspect the diff, document limitations, and
   stop at the requested roadmap phase.

## Research output rules

- Prefer: raw/canonical data -> deterministic evidence -> ranked findings ->
  concise structured report.
- Keep relevance deterministic and transparent; do not ask an LLM to decide
  importance from raw financial data.
- Keep relevance (priority) separate from confidence (evidence sufficiency).
- Make unsupported data visible in structured coverage instead of showing
  placeholder sections or zeros.
- Do not state that correlation proves causation or turn statistical
  significance into economic significance.

## Obsidian project memory

After substantial implementation work, an architectural decision, a roadmap
change, a completed research phase, or a material provider/test result, update
the Jarvis Obsidian project note.

1. Resolve the vault from `JARVIS_OBSIDIAN_VAULT`. If it is unset, look for a
   repository-local `.codex/obsidian-vault-path` containing one absolute vault
   path. If neither is available, ask the user for the vault path; do not guess
   or create a random external directory.
2. Use `<vault>/Jarvis/Gassi Jarvis Quant Research.md`. Create the `Jarvis`
   folder and note only after the vault itself is explicitly resolved.
3. Append a compact dated entry with: completed phase/change, architectural
   decision, files or modules affected, verification results, explicit
   limitations/unsupported data, and the next intended phase. Keep links or
   paths to repository artifacts; do not copy raw provider payloads.
4. Treat Obsidian notes as project memory, never as authoritative financial
   data. Do not store secrets, API keys, customer data, or unverified market
   measurements there.

For the first update after this skill is added, record the completed Phases
0–4 and note that Phase 4 produces deterministic structured reports without
Gemini, while valuation history, provider-neutral estimates, crypto derivatives
metadata, and later historical/statistical phases remain unsupported or out of
scope.

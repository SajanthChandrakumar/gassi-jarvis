# Natural-Language Quant Research (Phase 7)

Phase 7 connects a small set of read-only Jarvis finance tools to the existing deterministic research layers. It does not create a trading agent.

```text
Natural-language question / Gemini tool choice
  -> validated ResearchRequest
  -> AssetResolver + approved ResearchPlanner
  -> canonical OpenBB data -> Phase 3-6 engines
  -> validated ResearchResponse -> deterministic Jarvis rendering
```

`ResearchRequest` is the only entry to `ResearchOrchestrator`. It has a bounded intent, assets, optional benchmark/timeframe, requested analyses, report depth, and string-only parameters. The planner owns the approved section set; a Gemini response cannot provide Python, provider routes, or a tool chain. `AssetResolver` centralizes familiar names and the explicitly reported `Nasdaq -> QQQ` benchmark default. Unresolved mentions return an ambiguity result before any provider call.

The four agent-facing tools are `research_asset`, `compare_assets`, `research_history`, and `analyze_relationship`. They are all read-only and use only the Phase 1 canonical client, Phase 3 relevance engine, Phase 4 reports, Phase 5 historical event study, and Phase 6 correlation/beta. For example a BTC/QQQ relationship request fetches price series only; it does not fetch fundamentals or estimates.

`ResearchResponse` is authoritative and contains resolved identities, the selected plan, structured reports/results, provenance sources, warnings, and an execution trace. The validator rejects malformed/non-finite output and does not turn sparse statistical or historical samples into a success. Partial provider coverage remains visible. The current Jarvis response uses a small deterministic renderer, so provider-returned text never enters an instruction context. A later Gemini renderer may only summarize the validated structured response and must preserve its numbers and warnings.

Limitations: name resolution is intentionally small, `Nasdaq` uses QQQ rather than an index series, valuation history is not available, and no tool gives a recommendation, price target, causality claim, portfolio action, or order.

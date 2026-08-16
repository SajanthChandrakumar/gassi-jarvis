# Trading Financial Data Contract (Phase 0.5)

## Scope and trust boundary

Trading is a bounded module of Jarvis. Conversation history, Gemini output,
ChromaDB memory, and `jarvis_sessions.json` may help explain or collect input,
but are never financial source of truth. They must not determine trades,
balances, positions, cashflows, P&L, or portfolio state.

Authoritative financial state starts with structured `FinancialEvent` records.
Future positions, portfolio state, P&L, and analytics are reproducible
deterministic projections of those events:

```text
Authoritative financial events -> deterministic calculations -> derived views
```

## Authoritative event records

The ledger is append-only. Each event has a stable `event_id`, event type,
occurred/recorded timestamps, signed account movements, separately represented
fees, and provenance. The initial vocabulary is `trade`, `deposit`,
`withdrawal`, `transfer`, `adjustment`, and `correction`.

The event envelope is implemented in `app.trading.domain`. It is intentionally
not a position model. A correction is a new `correction` event that references
the original event; existing records must not be silently rewritten. Imports
retain a source, provider, external ID, optional batch ID, import time, and
optional source timestamp/raw timestamp. A future importer must use the source,
provider, and external ID as a duplicate-detection key whenever an external ID
exists, while retaining its own stable `event_id`.

`manual`, `csv_import`, `exchange_import`, `api_sync`, and `system_generated`
are the permitted provenance sources. They are generic deliberately: no
exchange-specific model exists at this stage.

## Money, assets, quantities, and fees

Authoritative amounts and quantities use `decimal.Decimal` only. Floats are
rejected. Asset and currency codes use normalized, exchange-independent
`AssetCode` values; no assumption is made about an asset's decimal places.
Amounts preserve input precision. Rounding is permitted only when rendering a
value for users or when a future, explicitly documented external settlement
rule requires it; the raw authoritative amount remains unchanged.

`FinancialLeg` uses signed quantities: positive enters a tracked account and
negative leaves it. Fee legs must be placed in `FinancialEvent.fees` and marked
explicitly, never hidden inside a trade price or quantity. Currency conversion
and cross-currency valuation are deferred.

## Time and ordering

`occurred_at`, `recorded_at`, `Provenance.imported_at`, and an optional source
timestamp must be timezone-aware. The domain normalizes persisted timestamps
to UTC and rejects naive datetimes. A source timestamp's original text/offset
may additionally be retained in `source_timestamp_raw` for audit purposes;
local timezone conversion is presentation only.

Event ordering is deterministic: first by `occurred_at`, then by
`recorded_at`, then by stable `event_id`. An importer must not invent a local
timezone for a timestamp lacking an offset; it must reject or require the
source timezone explicitly.

## Raw versus derived data

The following are authoritative when recorded as financial events: executed
trades, deposits, withdrawals, transfers, explicit fees, adjustments, and
corrections. Current positions, average entry price, realized/unrealized P&L,
portfolio value, exposure, performance metrics, and reports are derived data.
Derived values may be cached later for performance only when their source event
range/version is recorded; they never become a competing source of truth.

## Read, write, and approval boundaries

Future reads such as `get_portfolio`, `get_trade_history`, `calculate_pnl`, and
`analyze_performance` do not mutate financial records. A natural-language
utterance, including "I bought 0.2 BTC yesterday", is not a write.

Future writes such as `record_trade`, `record_deposit`, `import_transactions`,
and `correct_transaction` must be explicit, validated domain actions that
produce an auditable event. They require a confirmation UI/HitL policy suited
to local financial-record mutation; shell-command threat classification is not
the financial approval model.

External financial actions, including exchange orders, require a stronger,
separate approval boundary. Live execution, paper trading, exchange APIs, and
Gemini trading tools are out of scope.

## Persistence boundary

The domain depends only on the `FinancialEventRepository` protocol:

```text
Domain logic -> FinancialEventRepository -> persistence implementation
```

No persistence implementation is selected or created in Phase 0.5. Phase 1
may choose an independent ledger store (SQLite is a reasonable candidate) only
after defining transaction semantics, uniqueness constraints, backups, and
reconciliation needs. It must remain separate from ChromaDB and session JSON.

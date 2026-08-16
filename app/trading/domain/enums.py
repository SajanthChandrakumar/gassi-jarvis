"""Closed vocabularies for the financial event ledger."""

from enum import StrEnum


class FinancialEventType(StrEnum):
    """Kinds of authoritative financial events supported by the ledger."""

    TRADE = "trade"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    CORRECTION = "correction"


class RecordSource(StrEnum):
    """How an authoritative financial event entered the local ledger."""

    MANUAL = "manual"
    CSV_IMPORT = "csv_import"
    EXCHANGE_IMPORT = "exchange_import"
    API_SYNC = "api_sync"
    SYSTEM_GENERATED = "system_generated"

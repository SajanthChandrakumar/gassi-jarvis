"""Persistence boundary for authoritative financial events."""

from typing import Protocol

from .enums import RecordSource
from .models import FinancialEvent


class FinancialEventRepository(Protocol):
    """Append-only storage contract; implementations are deliberately deferred."""

    def append(self, event: FinancialEvent) -> None:
        """Persist a new event without mutating an existing event."""

    def get(self, event_id: str) -> FinancialEvent | None:
        """Return an event by its stable ledger identifier."""

    def find_by_external_id(
        self,
        source: RecordSource,
        provider: str | None,
        external_id: str,
    ) -> FinancialEvent | None:
        """Find previously imported data so callers can detect duplicates."""

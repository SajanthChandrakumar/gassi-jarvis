"""Immutable, auditable financial-event records without portfolio calculations."""

from dataclasses import dataclass
from datetime import datetime, timezone

from .enums import FinancialEventType, RecordSource
from .types import Quantity


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _utc_timestamp(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Traceability data captured when an event is accepted into the ledger."""

    source: RecordSource
    imported_at: datetime
    provider: str | None = None
    external_id: str | None = None
    import_batch_id: str | None = None
    source_timestamp: datetime | None = None
    source_timestamp_raw: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, RecordSource):
            raise TypeError("source must be a RecordSource")
        object.__setattr__(self, "imported_at", _utc_timestamp(self.imported_at, "imported_at"))
        if self.source_timestamp is not None:
            object.__setattr__(
                self,
                "source_timestamp",
                _utc_timestamp(self.source_timestamp, "source_timestamp"),
            )
        for field_name in ("provider", "external_id", "import_batch_id", "source_timestamp_raw"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _identifier(value, field_name))


@dataclass(frozen=True, slots=True)
class FinancialLeg:
    """One signed asset movement in a tracked account.

    Positive quantities enter the account; negative quantities leave it.
    Fees are separate legs so they cannot disappear inside a trade price.
    """

    account_id: str
    quantity: Quantity
    is_fee: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_id", _identifier(self.account_id, "account_id"))
        if not isinstance(self.quantity, Quantity):
            raise TypeError("quantity must be a Quantity")
        if self.quantity.amount == 0:
            raise ValueError("financial leg quantity must not be zero")
        if not isinstance(self.is_fee, bool):
            raise TypeError("is_fee must be a bool")


@dataclass(frozen=True, slots=True)
class FinancialEvent:
    """An immutable event from which future portfolio state is derived.

    This is an event envelope, not a stored position. Repositories append it;
    corrections are represented as new CORRECTION events linked to their target.
    """

    event_id: str
    event_type: FinancialEventType
    occurred_at: datetime
    recorded_at: datetime
    provenance: Provenance
    movements: tuple[FinancialLeg, ...]
    fees: tuple[FinancialLeg, ...] = ()
    corrects_event_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _identifier(self.event_id, "event_id"))
        if not isinstance(self.event_type, FinancialEventType):
            raise TypeError("event_type must be a FinancialEventType")
        object.__setattr__(self, "occurred_at", _utc_timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "recorded_at", _utc_timestamp(self.recorded_at, "recorded_at"))
        if not isinstance(self.provenance, Provenance):
            raise TypeError("provenance must be Provenance")

        movements = tuple(self.movements)
        fees = tuple(self.fees)
        if not movements:
            raise ValueError("financial event must contain at least one movement")
        if any(not isinstance(leg, FinancialLeg) for leg in (*movements, *fees)):
            raise TypeError("movements and fees must contain FinancialLeg values")
        if any(leg.is_fee for leg in movements):
            raise ValueError("fee legs must be recorded in fees, not movements")
        if any(not leg.is_fee for leg in fees):
            raise ValueError("all fee legs must set is_fee=True")
        object.__setattr__(self, "movements", movements)
        object.__setattr__(self, "fees", fees)

        correction_target = self.corrects_event_id
        if self.event_type is FinancialEventType.CORRECTION:
            if correction_target is None:
                raise ValueError("correction events must identify the event they correct")
            correction_target = _identifier(correction_target, "corrects_event_id")
            if correction_target == self.event_id:
                raise ValueError("an event cannot correct itself")
        elif correction_target is not None:
            raise ValueError("only correction events may identify corrects_event_id")
        object.__setattr__(self, "corrects_event_id", correction_target)

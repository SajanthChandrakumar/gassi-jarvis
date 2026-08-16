from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.trading.domain import (
    FinancialEvent,
    FinancialEventType,
    FinancialLeg,
    Money,
    Provenance,
    Quantity,
    RecordSource,
)


UTC_NOW = datetime(2026, 8, 16, 10, 30, tzinfo=timezone.utc)


def _provenance() -> Provenance:
    return Provenance(source=RecordSource.MANUAL, imported_at=UTC_NOW)


def _movement() -> FinancialLeg:
    return FinancialLeg("brokerage", Quantity(Decimal("0.200000000000000001"), "btc"))


def test_money_and_quantity_preserve_decimal_precision_and_normalize_asset_codes():
    money = Money(Decimal("0.100000000000000001"), "usd")
    quantity = _movement().quantity

    assert money.amount == Decimal("0.100000000000000001")
    assert str(money.currency) == "USD"
    assert quantity.amount == Decimal("0.200000000000000001")
    assert str(quantity.asset) == "BTC"


def test_binary_float_is_rejected_for_authoritative_amounts():
    with pytest.raises(TypeError, match="decimal.Decimal"):
        Money(0.1, "USD")  # type: ignore[arg-type]


def test_naive_financial_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        FinancialEvent(
            event_id="manual-1",
            event_type=FinancialEventType.DEPOSIT,
            occurred_at=datetime(2026, 8, 16, 10, 30),
            recorded_at=UTC_NOW,
            provenance=_provenance(),
            movements=(_movement(),),
        )


def test_event_normalizes_persisted_timestamps_to_utc_and_keeps_fee_separate():
    event = FinancialEvent(
        event_id="trade-1",
        event_type=FinancialEventType.TRADE,
        occurred_at=datetime(2026, 8, 16, 12, 30, tzinfo=timezone.utc),
        recorded_at=UTC_NOW,
        provenance=_provenance(),
        movements=(_movement(),),
        fees=(FinancialLeg("brokerage", Quantity(Decimal("-1.25"), "USD"), is_fee=True),),
    )

    assert event.occurred_at.tzinfo == timezone.utc
    assert event.fees[0].is_fee is True


def test_corrections_are_new_events_that_must_reference_an_original_event():
    with pytest.raises(ValueError, match="must identify"):
        FinancialEvent(
            event_id="correction-1",
            event_type=FinancialEventType.CORRECTION,
            occurred_at=UTC_NOW,
            recorded_at=UTC_NOW,
            provenance=_provenance(),
            movements=(_movement(),),
        )

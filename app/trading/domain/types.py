"""Exact value objects used by authoritative financial events."""

from dataclasses import dataclass
from decimal import Decimal
import re

_ASSET_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,19}$")


def _require_decimal(value: Decimal, field_name: str) -> Decimal:
    """Reject float values before they can introduce binary rounding errors."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a decimal.Decimal, not {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


@dataclass(frozen=True, slots=True)
class AssetCode:
    """Normalized asset or currency identifier, independent of an exchange."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("asset code must be a string")
        normalized = self.value.strip().upper()
        if not _ASSET_CODE.fullmatch(normalized):
            raise ValueError("asset code must contain 2-20 uppercase letters, digits, '.', '_' or '-'")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Money:
    """An exact monetary amount in one currency; no display rounding is applied."""

    amount: Decimal
    currency: AssetCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _require_decimal(self.amount, "money amount"))
        if isinstance(self.currency, str):
            object.__setattr__(self, "currency", AssetCode(self.currency))
        if not isinstance(self.currency, AssetCode):
            raise TypeError("currency must be an AssetCode")


@dataclass(frozen=True, slots=True)
class Quantity:
    """An exact quantity of one asset; precision is preserved as supplied."""

    amount: Decimal
    asset: AssetCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _require_decimal(self.amount, "quantity amount"))
        if isinstance(self.asset, str):
            object.__setattr__(self, "asset", AssetCode(self.asset))
        if not isinstance(self.asset, AssetCode):
            raise TypeError("asset must be an AssetCode")

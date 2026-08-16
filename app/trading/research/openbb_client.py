"""Small Jarvis-facing adapter around the official OpenBB Python interface.

OpenBB-specific routes and response objects are intentionally contained here.
The adapter returns structured raw data and never calls Gemini or interprets
the financial meaning of a result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from typing import Any, Literal


AssetType = Literal["equity", "crypto", "macro"]


@dataclass(frozen=True, slots=True)
class ResearchProviderSettings:
    """Optional default OpenBB providers, configurable without code changes."""

    equity: str | None = None
    crypto: str | None = None
    macro: str | None = None

    @classmethod
    def from_environment(cls) -> "ResearchProviderSettings":
        return cls(
            equity=os.getenv("JARVIS_OPENBB_EQUITY_PROVIDER") or "yfinance",
            crypto=os.getenv("JARVIS_OPENBB_CRYPTO_PROVIDER") or "yfinance",
            macro=os.getenv("JARVIS_OPENBB_MACRO_PROVIDER") or "econdb",
        )


@dataclass(frozen=True, slots=True)
class ResearchData:
    """Raw data with request, provider, and retrieval provenance."""

    symbol: str
    asset_type: AssetType
    category: str
    provider: str | None
    retrieved_at: datetime
    data: tuple[dict[str, Any], ...]
    start_date: str | None = None
    end_date: str | None = None
    warnings: tuple[str, ...] = ()


class ResearchError(RuntimeError):
    """Base error for a debuggable failure at the research-data boundary."""

    code = "research_error"

    def __init__(self, message: str, *, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class ResearchConfigurationError(ResearchError):
    code = "configuration_error"


class ResearchMissingCredentialError(ResearchError):
    code = "missing_credential"


class ResearchUnsupportedEndpointError(ResearchError):
    code = "unsupported_endpoint"


class ResearchRateLimitError(ResearchError):
    code = "rate_limited"


class ResearchNoDataError(ResearchError):
    code = "no_data"


class ResearchInvalidSymbolError(ResearchError):
    code = "invalid_symbol"


class ResearchProviderError(ResearchError):
    code = "provider_error"


def _date_value(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _json_value(value: Any) -> Any:
    """Convert OpenBB/Pydantic result values into structured JSON-safe values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "model_dump"):
        return _json_value(row.model_dump(mode="json"))
    if isinstance(row, Mapping):
        return _json_value(dict(row))
    raise ResearchProviderError(
        f"OpenBB returned an unsupported row type: {type(row).__name__}"
    )


class OpenBBResearchClient:
    """Expose a deliberately small research-facing interface over OpenBB."""

    def __init__(
        self,
        openbb_client: Any | None = None,
        provider_settings: ResearchProviderSettings | None = None,
    ) -> None:
        self._openbb_client = openbb_client
        self._provider_settings = provider_settings or ResearchProviderSettings.from_environment()

    @property
    def _obb(self) -> Any:
        if self._openbb_client is None:
            try:
                from openbb import obb
            except ImportError as exc:
                raise ResearchConfigurationError(
                    "OpenBB is not installed. Install the project's research dependencies."
                ) from exc
            self._openbb_client = obb
        return self._openbb_client

    def get_price_history(
        self,
        symbol: str,
        *,
        asset_type: Literal["equity", "crypto"] = "equity",
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        interval: str | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return raw OHLCV history for an equity/ETF or crypto pair."""
        if asset_type not in {"equity", "crypto"}:
            raise ResearchConfigurationError(f"Unsupported price asset type: {asset_type}")

        selected_provider = provider or getattr(self._provider_settings, asset_type)
        endpoint = (
            self._obb.equity.price.historical
            if asset_type == "equity"
            else self._obb.crypto.price.historical
        )
        params: dict[str, Any] = {
            "symbol": symbol,
            "start_date": _date_value(start_date),
            "end_date": _date_value(end_date),
        }
        if interval is not None:
            params["interval"] = interval
        if selected_provider is not None:
            params["provider"] = selected_provider
        return self._execute(
            lambda: endpoint(**params),
            symbol=symbol,
            asset_type=asset_type,
            category="price_history",
            start_date=params["start_date"],
            end_date=params["end_date"],
            requested_provider=selected_provider,
        )

    def get_company_profile(
        self, symbol: str, *, provider: str | None = None
    ) -> ResearchData:
        """Return raw company profile data for an equity or ETF where supported."""
        selected_provider = provider or self._provider_settings.equity
        params: dict[str, Any] = {"symbol": symbol}
        if selected_provider is not None:
            params["provider"] = selected_provider
        return self._execute(
            lambda: self._obb.equity.profile(**params),
            symbol=symbol,
            asset_type="equity",
            category="company_profile",
            requested_provider=selected_provider,
        )

    def get_financial_statements(
        self,
        symbol: str,
        *,
        statement: Literal["income", "balance", "cash_flow"] = "income",
        limit: int | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return raw income, balance-sheet, or cash-flow statements."""
        endpoints = {
            "income": self._obb.equity.fundamental.income,
            "balance": self._obb.equity.fundamental.balance,
            "cash_flow": self._obb.equity.fundamental.cash,
        }
        try:
            endpoint = endpoints[statement]
        except KeyError as exc:
            raise ResearchConfigurationError(f"Unsupported statement type: {statement}") from exc
        selected_provider = provider or self._provider_settings.equity
        params: dict[str, Any] = {"symbol": symbol}
        if limit is not None:
            params["limit"] = limit
        if selected_provider is not None:
            params["provider"] = selected_provider
        return self._execute(
            lambda: endpoint(**params),
            symbol=symbol,
            asset_type="equity",
            category=f"{statement}_statement",
            requested_provider=selected_provider,
        )

    def get_earnings_calendar(
        self,
        *,
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return raw equity earnings-calendar records when a provider supports it."""
        # OpenBB's current earnings-calendar endpoint is not supplied by the
        # credentials-free default provider. Let OpenBB select an installed
        # provider unless the caller explicitly requests one.
        selected_provider = provider
        params: dict[str, Any] = {
            "start_date": _date_value(start_date),
            "end_date": _date_value(end_date),
        }
        if selected_provider is not None:
            params["provider"] = selected_provider
        return self._execute(
            lambda: self._obb.equity.calendar.earnings(**params),
            symbol="",
            asset_type="equity",
            category="earnings_calendar",
            start_date=params["start_date"],
            end_date=params["end_date"],
            requested_provider=selected_provider,
        )

    def get_macro_series(
        self,
        indicator: str,
        *,
        country: str = "united_states",
        frequency: Literal["annual", "quarter", "month"] = "month",
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return a raw OpenBB macroeconomic indicator series."""
        selected_provider = provider or self._provider_settings.macro
        params: dict[str, Any] = {
            "symbol": indicator,
            "country": country,
            "frequency": frequency,
            "start_date": _date_value(start_date),
            "end_date": _date_value(end_date),
        }
        if selected_provider is not None:
            params["provider"] = selected_provider
        return self._execute(
            lambda: self._obb.economy.indicators(**params),
            symbol=indicator,
            asset_type="macro",
            category="macro_series",
            start_date=params["start_date"],
            end_date=params["end_date"],
            requested_provider=selected_provider,
        )

    def _execute(
        self,
        call: Callable[[], Any],
        *,
        symbol: str,
        asset_type: AssetType,
        category: str,
        requested_provider: str | None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> ResearchData:
        try:
            result = call()
        except ResearchError:
            raise
        except Exception as exc:
            raise self._map_openbb_error(exc, requested_provider) from exc

        rows = getattr(result, "results", None)
        if not rows:
            raise ResearchNoDataError(
                f"OpenBB returned no {category} data for {symbol or 'the requested range'}.",
                provider=getattr(result, "provider", None) or requested_provider,
            )

        warnings = tuple(
            getattr(warning, "message", str(warning))
            for warning in (getattr(result, "warnings", None) or [])
        )
        return ResearchData(
            symbol=symbol,
            asset_type=asset_type,
            category=category,
            provider=getattr(result, "provider", None) or requested_provider,
            retrieved_at=datetime.now(timezone.utc),
            data=tuple(_row_to_dict(row) for row in rows),
            start_date=start_date,
            end_date=end_date,
            warnings=warnings,
        )

    @staticmethod
    def _map_openbb_error(exc: Exception, provider: str | None) -> ResearchError:
        message = str(exc).strip() or exc.__class__.__name__
        normalized = message.lower()
        if "api key" in normalized or "credential" in normalized or "not authorized" in normalized:
            return ResearchMissingCredentialError(message, provider=provider)
        if "rate limit" in normalized or "too many requests" in normalized or "429" in normalized:
            return ResearchRateLimitError(message, provider=provider)
        if "not installed" in normalized or "unsupported" in normalized or "not available" in normalized:
            return ResearchUnsupportedEndpointError(message, provider=provider)
        if "invalid symbol" in normalized or "symbol not found" in normalized:
            return ResearchInvalidSymbolError(message, provider=provider)
        if "no data" in normalized or "no results" in normalized:
            return ResearchNoDataError(message, provider=provider)
        return ResearchProviderError(message, provider=provider)

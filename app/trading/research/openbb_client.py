"""Small Jarvis-facing adapter around the official OpenBB Python interface.

OpenBB-specific routes and response objects are intentionally contained here.
The adapter returns structured raw data and never calls Gemini or interprets
the financial meaning of a result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from typing import Any, Literal

from .canonical import ProviderAttempt


AssetType = Literal["equity", "crypto", "macro"]


def _configure_tls_ca_bundle() -> None:
    """Use the environment's trusted CA bundle when macOS Python has none."""
    if os.getenv("SSL_CERT_FILE", "").strip():
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


@dataclass(frozen=True, slots=True)
class ResearchProviderSettings:
    """Optional default OpenBB providers, configurable without code changes."""

    price: tuple[str, ...] = ("yfinance",)
    quote: tuple[str, ...] = ("yfinance",)
    profile: tuple[str, ...] = ("yfinance",)
    statements: tuple[str, ...] = ("yfinance",)
    metrics: tuple[str, ...] = ("yfinance",)
    news: tuple[str, ...] = ("yfinance",)
    estimates: tuple[str, ...] = ("yfinance",)
    earnings: tuple[str, ...] = ()
    filings: tuple[str, ...] = ("sec",)
    crypto: tuple[str, ...] = ("yfinance",)
    macro: tuple[str, ...] = ("econdb",)

    @classmethod
    def from_environment(cls) -> "ResearchProviderSettings":
        has_fmp = bool(os.getenv("FMP_API_KEY", "").strip())
        has_tiingo = bool(os.getenv("TIINGO_TOKEN", "").strip())
        has_fred = bool(os.getenv("FRED_API_KEY", "").strip())
        return cls(
            price=("yfinance",) + (("tiingo",) if has_tiingo else ()) + (("fmp",) if has_fmp else ()),
            quote=("yfinance",) + (("fmp",) if has_fmp else ()),
            profile=(("fmp",) if has_fmp else ()) + ("yfinance",),
            statements=("sec",) + (("fmp",) if has_fmp else ()) + ("yfinance",),
            metrics=(("fmp",) if has_fmp else ()) + ("yfinance",),
            news=("yfinance",),
            estimates=(("fmp",) if has_fmp else ()) + ("yfinance",),
            earnings=(("fmp",) if has_fmp else ()),
            filings=("sec",),
            crypto=("yfinance",),
            macro=(("fred",) if has_fred else ()) + ("econdb",),
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
    attempts: tuple[ProviderAttempt, ...] = ()
    request_parameters: tuple[tuple[str, str], ...] = ()


class ResearchError(RuntimeError):
    """Base error for a debuggable failure at the research-data boundary."""

    code = "research_error"

    def __init__(self, message: str, *, provider: str | None = None, public_message: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.public_message = public_message or "Research data is currently unavailable."


class ResearchConfigurationError(ResearchError):
    code = "configuration_error"


def _public_provider_warning(message: str) -> str:
    """Reduce provider-authored warning text to stable, non-actionable wording."""
    normalized = str(message).lower()
    if any(token in normalized for token in ("http://", "https://", "402", "premium", "subscription", "upgrade", "restricted")):
        return "Provider returned a restricted-data warning."
    return "Provider returned a data-quality warning."


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


class ResearchEntitlementError(ResearchError):
    code = "entitlement_required"


def _first_available(
    providers: tuple[str, ...],
    request: Callable[[str], ResearchData],
) -> ResearchData:
    attempts: list[ProviderAttempt] = []
    last_error: ResearchError | None = None
    for provider in providers:
        try:
            result = request(provider)
        except ResearchError as exc:
            attempts.append(ProviderAttempt(provider, "failure", exc.code))
            last_error = exc
            continue
        attempts.append(ProviderAttempt(provider, "success"))
        return replace(result, attempts=tuple(attempts))
    if last_error is not None:
        raise last_error
    raise ResearchConfigurationError(
        "No provider is configured for this route.",
        public_message="No provider is configured for this research section.",
    )


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
            _configure_tls_ca_bundle()
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

        endpoint = (
            self._obb.equity.price.historical
            if asset_type == "equity"
            else self._obb.crypto.price.historical
        )
        # Jarvis resolves crypto assets to a canonical base symbol (BTC, ETH)
        # while the yfinance OpenBB route expects an explicit quote pair.
        # Keep the canonical identity at the caller boundary and adapt only
        # the provider request symbol here.
        providers = (provider,) if provider else (
            self._provider_settings.price if asset_type == "equity" else self._provider_settings.crypto
        )

        def request(selected_provider: str) -> ResearchData:
            request_symbol = symbol
            if asset_type == "crypto" and selected_provider == "yfinance" and "-" not in symbol:
                request_symbol = f"{symbol.upper()}-USD"
            params: dict[str, Any] = {
                "symbol": request_symbol,
                "start_date": _date_value(start_date),
                "end_date": _date_value(end_date),
                "provider": selected_provider,
            }
            if interval is not None:
                params["interval"] = interval
            return self._execute(
                lambda: endpoint(**params),
                symbol=symbol,
                asset_type=asset_type,
                category="price_history",
                start_date=params["start_date"],
                end_date=params["end_date"],
                requested_provider=selected_provider,
            )

        return _first_available(providers, request)

    def get_company_profile(
        self, symbol: str, *, provider: str | None = None
    ) -> ResearchData:
        """Return raw company profile data for an equity or ETF where supported."""
        providers = (provider,) if provider else self._provider_settings.profile
        return _first_available(providers, lambda selected: self._execute(
            lambda: self._obb.equity.profile(symbol=symbol, provider=selected),
            symbol=symbol,
            asset_type="equity",
            category="company_profile",
            requested_provider=selected,
        ))

    def get_equity_quote(
        self, symbol: str, *, provider: str | None = None
    ) -> ResearchData:
        """Return a bounded observed equity quote."""
        providers = (provider,) if provider else self._provider_settings.quote
        return _first_available(providers, lambda selected: self._execute(
            lambda: self._obb.equity.price.quote(symbol=symbol, provider=selected),
            symbol=symbol,
            asset_type="equity",
            category="equity_quote",
            requested_provider=selected,
        ))

    def get_fundamental_metrics(
        self, symbol: str, *, provider: str | None = None
    ) -> ResearchData:
        """Return observed provider valuation and operating metrics."""
        providers = (provider,) if provider else self._provider_settings.metrics
        return _first_available(providers, lambda selected: self._execute(
            lambda: self._obb.equity.fundamental.metrics(symbol=symbol, provider=selected),
            symbol=symbol,
            asset_type="equity",
            category="fundamental_metrics",
            requested_provider=selected,
        ))

    def get_company_filings(
        self,
        symbol: str,
        *,
        limit: int = 12,
        provider: str | None = None,
    ) -> ResearchData:
        """Return a bounded set of official company-filing metadata."""
        if not 1 <= limit <= 100:
            raise ResearchConfigurationError("Company-filings limit must be between 1 and 100")
        providers = (provider,) if provider else self._provider_settings.filings
        return _first_available(providers, lambda selected: self._execute(
            lambda: self._obb.equity.fundamental.filings(
                symbol=symbol, limit=limit, provider=selected,
            ),
            symbol=symbol,
            asset_type="equity",
            category="company_filings",
            requested_provider=selected,
        ))

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
        providers = (provider,) if provider else self._provider_settings.statements

        def request(selected_provider: str) -> ResearchData:
            params: dict[str, Any] = {"symbol": symbol, "provider": selected_provider}
            if limit is not None:
                params["limit"] = limit
            return self._execute(
                lambda: endpoint(**params),
                symbol=symbol,
                asset_type="equity",
                category=f"{statement}_statement",
                requested_provider=selected_provider,
            )

        return _first_available(providers, request)

    def get_earnings_calendar(
        self,
        symbol: str,
        *,
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return raw equity earnings-calendar records when a provider supports it."""
        # OpenBB's current earnings-calendar endpoint is not supplied by the
        # credentials-free default provider. Let OpenBB select an installed
        # provider unless the caller explicitly requests one.
        providers = (provider,) if provider else self._provider_settings.earnings

        def request(selected_provider: str) -> ResearchData:
            params: dict[str, Any] = {
                "start_date": _date_value(start_date),
                "end_date": _date_value(end_date),
                "provider": selected_provider,
            }
            result = self._execute(
                lambda: self._obb.equity.calendar.earnings(**params),
                symbol=symbol,
                asset_type="equity",
                category="earnings_calendar",
                start_date=params["start_date"],
                end_date=params["end_date"],
                requested_provider=selected_provider,
            )
            matches = tuple(
                row for row in result.data
                if str(row.get("symbol") or "").upper() == symbol.upper()
            )
            return replace(
                result,
                data=matches,
                warnings=result.warnings + (() if matches else (
                    "No earnings event was found in the current 44-day window.",
                )),
            )

        return _first_available(providers, request)

    def get_company_news(
        self,
        symbol: str,
        *,
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        limit: int = 8,
        provider: str | None = None,
    ) -> ResearchData:
        """Return bounded company-news records without interpreting headlines."""
        if not 1 <= limit <= 100:
            raise ResearchConfigurationError("Company-news limit must be between 1 and 100")
        providers = (provider,) if provider else self._provider_settings.news

        def request(selected_provider: str) -> ResearchData:
            params: dict[str, Any] = {
                "symbol": symbol,
                "start_date": _date_value(start_date),
                "end_date": _date_value(end_date),
                "limit": limit,
                "provider": selected_provider,
            }
            return self._execute(
                lambda: self._obb.news.company(**params),
                symbol=symbol,
                asset_type="equity",
                category="company_news",
                start_date=params["start_date"],
                end_date=params["end_date"],
                requested_provider=selected_provider,
            )

        return _first_available(providers, request)

    def get_estimates_consensus(
        self,
        symbol: str,
        *,
        provider: str | None = None,
    ) -> ResearchData:
        """Return observed analyst-consensus fields without producing advice."""
        providers = (provider,) if provider else self._provider_settings.estimates

        def request(selected_provider: str) -> ResearchData:
            return self._execute(
                lambda: self._obb.equity.estimates.consensus(symbol=symbol, provider=selected_provider),
                symbol=symbol,
                asset_type="equity",
                category="estimates_consensus",
                requested_provider=selected_provider,
            )

        return _first_available(providers, request)

    def get_macro_series(
        self,
        indicator: str,
        *,
        series_id: str | None = None,
        transform: str | None = None,
        unit: str | None = None,
        country: str = "united_states",
        frequency: Literal["annual", "quarter", "month"] = "month",
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
        provider: str | None = None,
    ) -> ResearchData:
        """Return a raw OpenBB macroeconomic indicator series."""
        providers = (provider,) if provider else self._provider_settings.macro
        fred_series = series_id or {
            "CPI": "CPIAUCSL", "GDP": "GDPC1", "UNEMPLOYMENT": "UNRATE",
        }.get(indicator.upper(), indicator)
        econdb_equivalents = {
            "inflation": ("INFLATION", "month", "% YoY"),
            "unemployment": ("UNEMPLOYMENT", "month", "%"),
            "policy_rate": ("INTEREST_RATE", "month", "%"),
        }

        def request(selected_provider: str) -> ResearchData:
            if selected_provider == "fred":
                params: dict[str, Any] = {"symbol": fred_series, "provider": "fred"}
                if transform:
                    params["transform"] = transform
                if start_date is not None:
                    params["start_date"] = _date_value(start_date)
                if end_date is not None:
                    params["end_date"] = _date_value(end_date)
                endpoint = self._obb.economy.fred_series
                output_series = fred_series
            else:
                if selected_provider == "econdb":
                    equivalent = econdb_equivalents.get(indicator)
                    if equivalent is None:
                        raise ResearchUnsupportedEndpointError(
                            f"No semantically equivalent EconDB series for {indicator}.",
                            provider="econdb",
                            public_message="EconDB does not expose an equivalent series for this indicator.",
                        )
                    output_series, selected_frequency, _ = equivalent
                else:
                    output_series, selected_frequency = indicator, frequency
                params = {
                    "symbol": output_series,
                    "country": country,
                    "frequency": selected_frequency,
                    "provider": selected_provider,
                }
                if start_date is not None:
                    params["start_date"] = _date_value(start_date)
                if end_date is not None:
                    params["end_date"] = _date_value(end_date)
                endpoint = self._obb.economy.indicators

            result = self._execute(
                lambda: endpoint(**params),
                symbol=indicator,
                asset_type="macro",
                category="macro_series",
                start_date=_date_value(start_date),
                end_date=_date_value(end_date),
                requested_provider=selected_provider,
                request_parameters=tuple(
                    (key, value) for key, value in (
                        ("series_id", str(output_series)),
                        ("transform", transform),
                        ("unit", unit),
                    ) if value is not None
                ),
            )
            return replace(
                result,
                data=tuple({
                    **row,
                    "value": row.get("value", row.get(str(output_series))),
                    "unit": unit or row.get("unit"),
                } for row in result.data),
            )

        return _first_available(providers, request)

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
        request_parameters: tuple[tuple[str, str], ...] = (),
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
            _public_provider_warning(getattr(warning, "message", str(warning)))
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
            request_parameters=request_parameters,
        )

    @staticmethod
    def _map_openbb_error(exc: Exception, provider: str | None) -> ResearchError:
        message = str(exc).strip() or exc.__class__.__name__
        normalized = message.lower()
        provider_label = (provider or "provider").upper()
        if "402" in normalized or "premium" in normalized or "subscription" in normalized or "restricted endpoint" in normalized:
            return ResearchEntitlementError(
                message,
                provider=provider,
                public_message=f"This data is not included in the configured {provider_label} tier.",
            )
        if "api key" in normalized or "credential" in normalized or "not authorized" in normalized:
            return ResearchMissingCredentialError(
                message,
                provider=provider,
                public_message=f"The optional {provider_label} credential is not configured or accepted.",
            )
        if "rate limit" in normalized or "too many requests" in normalized or "429" in normalized:
            return ResearchRateLimitError(
                message,
                provider=provider,
                public_message=f"{provider_label} is temporarily rate limited.",
            )
        if "not installed" in normalized or "unsupported" in normalized or "not available" in normalized:
            return ResearchUnsupportedEndpointError(
                message,
                provider=provider,
                public_message=f"{provider_label} does not support this research section.",
            )
        if "invalid symbol" in normalized or "symbol not found" in normalized:
            return ResearchInvalidSymbolError(
                message,
                provider=provider,
                public_message="The requested asset symbol was not recognized.",
            )
        if "no data" in normalized or "no results" in normalized:
            return ResearchNoDataError(
                message,
                provider=provider,
                public_message="No data was returned for this research scope.",
            )
        return ResearchProviderError(
            message,
            provider=provider,
            public_message=f"{provider_label} could not return this research section.",
        )

"""Safe, deterministic status metadata for Jarvis OpenBB provider integrations.

This module reports only configuration and integration coverage.  It never
reads, serializes, or validates credential values, and it does not perform
network calls.  A configured key therefore means a provider is ready to use,
not that an upstream request has succeeded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Non-secret provider configuration and Jarvis integration state."""

    provider: str
    credential_configured: bool
    configuration_state: str
    current_coverage: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ProviderSpec:
    provider: str
    credential_name: str | None
    current_coverage: tuple[str, ...]


_PROVIDER_SPECS = (
    _ProviderSpec("yfinance", None, ("price history", "quote", "company profile", "financial statements", "valuation metrics", "analyst estimates", "company news")),
    _ProviderSpec("sec", None, ("financial statements", "company filings")),
    _ProviderSpec("econdb", None, ("macro series",)),
    _ProviderSpec("fmp", "FMP_API_KEY", ("price fallback", "company profile", "financial statements", "valuation metrics", "analyst estimates", "earnings calendar")),
    _ProviderSpec("fred", "FRED_API_KEY", ("US macro context",)),
)


def provider_statuses(environ: Mapping[str, str] | None = None) -> tuple[ProviderStatus, ...]:
    """Return provider readiness without exposing credentials or making requests."""
    environment = os.environ if environ is None else environ
    statuses: list[ProviderStatus] = []
    for spec in _PROVIDER_SPECS:
        configured = spec.credential_name is None or bool(environment.get(spec.credential_name, "").strip())
        configuration_state = "built_in" if spec.credential_name is None else "configured" if configured else "not_configured"
        statuses.append(
            ProviderStatus(
                provider=spec.provider,
                credential_configured=configured,
                configuration_state=configuration_state,
                current_coverage=spec.current_coverage,
            )
        )
    return tuple(statuses)


def provider_status_payload(environ: Mapping[str, str] | None = None) -> dict[str, list[dict[str, object]]]:
    """Return a JSON-safe status envelope for the authenticated local UI."""
    return {"providers": [asdict(status) for status in provider_statuses(environ)]}

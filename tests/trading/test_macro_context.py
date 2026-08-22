from datetime import datetime, timezone
from decimal import Decimal

from app.trading.research import jarvis_tools
from app.trading.research.canonical import (
    AssetIdentity,
    CanonicalAssetType,
    DataQuality,
    FreshnessStatus,
    MacroObservation,
    MacroSeries,
    QualityStatus,
    ResearchProvenance,
)
from app.trading.research.openbb_client import ResearchProviderError


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


class FakeMacroService:
    def __init__(self):
        self.calls = []

    def get_macro_series(self, indicator, *, series_id, transform, unit, **_):
        self.calls.append((indicator, series_id, transform, unit))
        if indicator == "real_gdp_growth":
            raise ResearchProviderError(
                "GDP provider unavailable at https://provider.invalid/plan",
                provider="fred",
                public_message="FRED could not return this research section.",
            )
        asset = AssetIdentity(indicator, CanonicalAssetType.MACRO_SERIES)
        return MacroSeries(
            asset,
            (
                MacroObservation(datetime(2026, 7, 20, tzinfo=timezone.utc), Decimal("2.5")),
                MacroObservation(NOW, Decimal("2.7")),
            ),
            unit,
            "month",
            ResearchProvenance("fred", "macro_series", NOW),
            NOW,
            FreshnessStatus.FRESH,
            DataQuality(QualityStatus.COMPLETE),
        )


def test_macro_context_keeps_successes_and_reports_provider_failures():
    service = FakeMacroService()
    payload = jarvis_tools.macro_context_payload(service)

    assert sorted(service.calls) == sorted([
        ("inflation", "CPIAUCSL", "pc1", "% YoY"),
        ("unemployment", "UNRATE", None, "%"),
        ("policy_rate", "FEDFUNDS", None, "%"),
        ("treasury_10y", "DGS10", None, "%"),
        ("real_gdp_growth", "GDPC1", "pc1", "% YoY"),
    ])
    assert [item["asset"]["symbol"] for item in payload["series"]] == [
        "INFLATION", "UNEMPLOYMENT", "POLICY_RATE", "TREASURY_10Y",
    ]
    assert payload["series"][0]["observations"][-1]["value"] == "2.7"
    assert len(payload["series"][0]["observations"]) == 1
    assert payload["failures"] == [{
        "indicator": "real_gdp_growth",
        "code": "provider_error",
        "message": "FRED could not return this research section.",
        "provider": "fred",
    }]

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

    def get_macro_series(self, indicator, *, series_id, transform, unit, country, provider=None, **_):
        self.calls.append((country, indicator, series_id, transform, unit, provider))
        if country == "united_states" and indicator == "real_gdp_growth":
            raise ResearchProviderError(
                "Provider unavailable at https://provider.invalid/plan",
                provider=provider or "fred",
                public_message="Provider could not return this research section.",
            )
        asset = AssetIdentity(indicator, CanonicalAssetType.MACRO_SERIES)
        return MacroSeries(
            asset,
            (
                MacroObservation(datetime(2026, 7, 20, tzinfo=timezone.utc), Decimal("2.5")),
                MacroObservation(NOW, Decimal("2.8" if country == "switzerland" else "2.7")),
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

    assert len(service.calls) == 10
    assert {(country, provider) for country, *_, provider in service.calls} == {
        ("switzerland", "fred"),
        ("united_states", None),
    }
    assert {(indicator, series_id, transform, unit) for country, indicator, series_id, transform, unit, _ in service.calls if country == "switzerland"} == {
        ("inflation", "CP0000CHM086NEST", "pc1", "% YoY"),
        ("unemployment", "LRUNTTTTCHQ156S", None, "%"),
        ("policy_rate", "IRSTCI01CHM156N", None, "%"),
        ("treasury_10y", "IRLTLT01CHM156N", None, "%"),
        ("real_gdp_growth", "CLVMNACSAB1GQCH", "pc1", "% YoY"),
    }
    assert [country["code"] for country in payload["countries"]] == ["CH", "US"]
    assert [country["label"] for country in payload["countries"]] == ["Switzerland", "United States"]
    swiss, united_states = payload["countries"]
    assert swiss["series"][0]["observations"][-1]["value"] == "2.8"
    assert swiss["failures"] == []
    assert [item["asset"]["symbol"] for item in payload["series"]] == [
        "INFLATION", "UNEMPLOYMENT", "POLICY_RATE", "TREASURY_10Y",
    ]
    assert payload["series"] == united_states["series"]
    assert payload["failures"] == united_states["failures"]
    assert payload["series"][0]["observations"][-1]["value"] == "2.7"
    assert len(payload["series"][0]["observations"]) == 1
    assert payload["failures"] == [{
        "indicator": "real_gdp_growth",
        "code": "provider_error",
        "message": "Provider could not return this research section.",
        "provider": "fred",
    }]

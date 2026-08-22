from app.trading.research.provider_status import provider_status_payload, provider_statuses


def test_provider_statuses_report_configuration_not_unverified_liveness() -> None:
    statuses = {status.provider: status for status in provider_statuses({
        "FMP_API_KEY": "configured",
        "BENZINGA_API_KEY": "configured",
        "FRED_API_KEY": "configured",
        "TIINGO_TOKEN": "configured",
    })}

    assert statuses["yfinance"].configuration_state == "built_in"
    assert statuses["sec"].configuration_state == "built_in"
    assert statuses["fmp"].configuration_state == "configured"
    assert statuses["benzinga"].configuration_state == "configured"
    assert statuses["fred"].configuration_state == "configured"
    assert statuses["tiingo"].configuration_state == "configured"
    assert not hasattr(statuses["fmp"], "availability")


def test_provider_payload_does_not_include_credential_values() -> None:
    payload = provider_status_payload({"FMP_API_KEY": "secret-value"})

    assert payload["providers"]
    assert "secret-value" not in repr(payload)
    fmp = next(item for item in payload["providers"] if item["provider"] == "fmp")
    assert fmp["credential_configured"] is True
    assert fmp["configuration_state"] == "configured"

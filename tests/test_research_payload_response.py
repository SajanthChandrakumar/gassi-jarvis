"""API-contract coverage for structured, read-only Phase-7 responses."""

import asyncio

import app.main as main_module


def test_build_response_preserves_optional_research_payload(monkeypatch) -> None:
    async def no_audio(_: str) -> str:
        return ""

    monkeypatch.setattr(main_module, "_generate_tts_audio", no_audio)
    payload = {
        "status": "success",
        "reports": [{"asset": {"symbol": "NVDA"}, "key_findings": []}],
        "warnings": [],
    }

    response = asyncio.run(
        main_module._build_response(
            "Research report created.",
            action="finance_research:research_asset",
            research_payload=payload,
        )
    )

    assert response["research_payload"] == payload
    assert response["action_taken"] == "finance_research:research_asset"


def test_build_response_keeps_non_research_payload_empty(monkeypatch) -> None:
    async def no_audio(_: str) -> str:
        return ""

    monkeypatch.setattr(main_module, "_generate_tts_audio", no_audio)

    response = asyncio.run(main_module._build_response("Hello", generate_audio=False))

    assert response["research_payload"] is None

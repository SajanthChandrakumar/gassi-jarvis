"""Regression coverage for explicit task requests when Gemini returns empty."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.main as main
from app.models import ChatRequest, MessagePayload


@pytest.fixture(autouse=True)
def isolated_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(main.inbox, "INBOX_FILE", tmp_path / "inbox.md")
    monkeypatch.setattr(main, "get_session", lambda _session_id: {"history": []})
    monkeypatch.setattr(main, "get_pending_command", lambda _session_id: None)
    monkeypatch.setattr(main, "record_turn", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "crypto_asset_from_research_question", lambda _text: None)
    monkeypatch.setattr(
        main,
        "get_gemini_response",
        lambda *_args, **_kwargs: SimpleNamespace(candidates=[], text=""),
    )

    async def build_response(text, action="none", **kwargs):
        return {"text": text, "action": action, **kwargs}

    monkeypatch.setattr(main, "_build_response", build_response)


def request(content: str) -> ChatRequest:
    return ChatRequest(
        session_id="task-fallback-test",
        timestamp=datetime.now(timezone.utc),
        payload=MessagePayload(type="text", content=content),
    )


def send(content: str) -> dict:
    return asyncio.run(main.chat_with_jarvis.__wrapped__(None, request(content)))


def test_empty_model_response_lists_tasks_for_explicit_english_request():
    main.inbox.add_task("Browser-Endpunkte prüfen")

    result = send("List my open tasks.")

    assert result["action"] == "task_list"
    assert "Browser-Endpunkte prüfen" in result["text"]


def test_empty_model_response_captures_explicit_german_task():
    result = send("Merke als Aufgabe: Browser-Endpunkte prüfen")

    assert result["action"] == "task_captured"
    assert main.inbox.get_open_tasks() == ["Browser-Endpunkte prüfen"]


def test_empty_model_response_runs_explicit_german_web_search(monkeypatch):
    calls = []
    recorded_turns = []
    monkeypatch.setattr(
        main,
        "get_session",
        lambda _session_id: {
            "history": [{"role": "user", "text": "Notiere eine Aufgabe."}]
        },
    )
    monkeypatch.setattr(
        main,
        "search_web",
        lambda query, history=None: calls.append((query, history)) or "Python gefunden.",
    )
    monkeypatch.setattr(
        main,
        "record_turn",
        lambda *args, **kwargs: recorded_turns.append((args, kwargs)),
    )

    result = send("Suche im Web nach der offiziellen Python-Webseite.")

    assert result["action"] == "web_search: der offiziellen Python-Webseite"
    assert result["text"] == "Python gefunden."
    assert calls == [("der offiziellen Python-Webseite", None)]
    assert recorded_turns[-1][1]["tainted"] is True


def test_empty_model_response_runs_tool_named_web_search(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main,
        "search_web",
        lambda query, history=None: calls.append(query) or "Python gefunden.",
    )

    result = send(
        "Benutze ausdrücklich das Werkzeug web_search und suche nach der offiziellen Python-Webseite."
    )

    assert result["action"] == "web_search: der offiziellen Python-Webseite"
    assert calls == ["der offiziellen Python-Webseite"]


def test_empty_model_response_keeps_generic_fallback_for_unrelated_chat():
    result = send("Erzähl mir etwas Interessantes.")

    assert result["action"] == "text_response"
    assert result["text"] == "Ich konnte leider keine Antwort generieren."

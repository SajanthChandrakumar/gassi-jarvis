"""Task routing persists real inbox records independently of Gemini replies."""

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


@pytest.mark.parametrize("model_outcome", ["text", "tool", "quota", "error"])
def test_explicit_task_is_saved_once_before_model_routing(monkeypatch, model_outcome):
    def model_response(*_args, **_kwargs):
        if model_outcome == "quota":
            raise RuntimeError("429 quota exceeded")
        if model_outcome == "error":
            raise RuntimeError("upstream failed")
        if model_outcome == "tool":
            return SimpleNamespace(
                candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                    SimpleNamespace(function_call=SimpleNamespace(
                        name="capture_task", args={"task": "Falsche Modell-Aufgabe"}
                    ))
                ]))],
                text="",
            )
        return SimpleNamespace(candidates=[], text="Notiert")

    monkeypatch.setattr(main, "get_gemini_response", model_response)

    result = send("Notiere als Aufgabe: Auth-Bug fixen")

    assert result["action"] == "task_captured"
    assert main.inbox.get_open_tasks() == ["Auth-Bug fixen"]
    assert len(main.inbox.INBOX_FILE.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("utterance", [
    "Jarvis, notier: Tests ausführen",
    "Notiere eine Aufgabe: Tests ausführen",
    "Füge Tests ausführen zu meiner Aufgabenliste hinzu",
    "Add a task: Tests ausführen",
    "Bitte notiere als Aufgabe: Tests ausführen",
])
def test_bounded_capture_forms_store_the_task(utterance):
    result = send(utterance)

    assert result["action"] == "task_captured"
    assert main.inbox.get_open_tasks() == ["Tests ausführen"]


@pytest.mark.parametrize("utterance", [
    "Zeig mir meine Aufgaben",
    "Welche Aufgaben habe ich?",
    "Jarvis, zeige mir meine offenen Aufgaben.",
    "List my open tasks",
])
def test_bounded_list_forms_read_real_tasks_without_model(monkeypatch, utterance):
    main.inbox.add_task("Tests ausführen")

    def unavailable_model(*_args, **_kwargs):
        raise RuntimeError("429 quota exceeded")

    monkeypatch.setattr(main, "get_gemini_response", unavailable_model)

    result = send(utterance)

    assert result["action"] == "task_list"
    assert "Tests ausführen" in result["text"]
    assert main.inbox.get_open_tasks() == ["Tests ausführen"]


@pytest.mark.parametrize("utterance", [
    "Notiere als Aufgabe:",
    "Notiere eine Aufgabe",
    "Jarvis, notier: ",
    "Add a task:",
    "Füge zu meiner Aufgabenliste hinzu",
])
def test_empty_task_prompts_for_content_without_writing(utterance):
    result = send(utterance)

    assert result["action"] == "task_incomplete"
    assert result["text"]
    assert not main.inbox.INBOX_FILE.exists()


@pytest.mark.parametrize("utterance", [
    "Notiere keine Aufgabe: Tests ausführen",
    "Notiere nicht als Aufgabe: Tests ausführen",
    "Don't add a task: Tests ausführen",
    '"Notiere als Aufgabe: Tests ausführen"',
    "Wenn ich sage Notiere als Aufgabe: Tests ausführen, was passiert?",
    "Wie kann ich eine Aufgabe notieren?",
    "Merke dir, dass ich Kaffee mag",
    "Notiere meine Vorliebe für Kaffee in deinem Gedächtnis",
    "Notiere einen Termin morgen um 10 Uhr",
    "Jarvis, notier: Ich mag Kaffee",
    "Jarvis, notier: I like coffee",
    "Jarvis, notier: Mein Geburtstag ist am 4. Oktober",
    "Jarvis, notier: Termin morgen um 10 Uhr",
    "Jarvis, notier: Erinnere mich morgen um 10 Uhr",
    "Jarvis, notier: Morgen ist mein Geburtstag",
    "Jarvis, notier: Am Freitag um 10 Uhr Meeting mit Anna",
    "Zeig mir meinen Kalender",
    "Notiere als Aufgabe: Tests ausführen, oder vielleicht lieber nicht?",
    "Notiere als Aufgabe: Tests ausführen, aber bitte nicht speichern.",
    "Add a task: Run tests, but don't save it.",
    "List my open tasks if I ask you tomorrow",
])
def test_ambiguous_or_non_task_requests_keep_normal_chat(monkeypatch, utterance):
    monkeypatch.setattr(
        main, "get_gemini_response",
        lambda *_args, **_kwargs: SimpleNamespace(candidates=[], text="Normale Antwort"),
    )

    result = send(utterance)

    assert result["action"] == "text_response"
    assert result["text"] == "Normale Antwort"
    assert not main.inbox.INBOX_FILE.exists()


def test_short_note_with_calendar_related_task_is_still_a_task():
    result = send("Jarvis, notier: Termin vereinbaren")
    assert result["action"] == "task_captured"
    assert main.inbox.get_open_tasks() == ["Termin vereinbaren"]


def test_pending_approval_takes_priority_over_task_capture(monkeypatch):
    monkeypatch.setattr(main, "get_pending_command", lambda _session_id: "pending action")
    monkeypatch.setattr(main, "get_pending_action_type", lambda _session_id: "shell_command")
    monkeypatch.setattr(main, "analyze_user_intent", lambda *_args: "UNCLEAR")

    result = send("Notiere als Aufgabe: Tests ausführen")

    assert result["action"] == "hitl_unclear"
    assert not main.inbox.INBOX_FILE.exists()


def test_task_capture_precedes_crypto_research(monkeypatch):
    monkeypatch.setattr(main, "crypto_asset_from_research_question", lambda _text: "BTC-USD")

    def unexpected_research(**_kwargs):
        raise AssertionError("Task capture must precede crypto research")

    monkeypatch.setattr(main.research_tools, "research_asset", unexpected_research)

    result = send("Notiere als Aufgabe: BTC Performance prüfen")

    assert result["action"] == "task_captured"
    assert main.inbox.get_open_tasks() == ["BTC Performance prüfen"]


def test_failed_task_write_does_not_report_capture_success(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "existing-file"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(main.inbox, "INBOX_FILE", blocked_parent / "inbox.md")

    result = send("Notiere als Aufgabe: Tests ausführen")

    assert result["action"] == "task_capture_failed"
    assert "nicht speichern" in result["text"]
    assert blocked_parent.read_text(encoding="utf-8") == "not a directory"


def test_tool_capture_failure_does_not_report_success(tmp_path, monkeypatch):
    blocked_parent = tmp_path / "existing-file"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(main.inbox, "INBOX_FILE", blocked_parent / "inbox.md")
    monkeypatch.setattr(main, "get_gemini_response", lambda *_args, **_kwargs: SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(function_call=SimpleNamespace(
                name="capture_task", args={"task": "Tests ausführen"}
            ))
        ]))],
        text="",
    ))

    result = send("Bitte verwende das Werkzeug capture_task")

    assert result["action"] == "task_capture_failed"
    assert "nicht speichern" in result["text"]


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

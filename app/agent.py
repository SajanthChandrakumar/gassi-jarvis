"""
Gassi-Jarvis — Gemini LLM Agent (Layer 3: Orchestrator + Layer 4: Brain)

Handles all communication with the Google Gemini API:
    - Tool declarations for macOS control (open_app, shell_command).
    - Gemini response generation with function calling enabled.
    - NLP-based intent analysis for HitL approval/denial classification.
"""

import logging
import os

from google import genai
from google.genai import types
from dotenv import load_dotenv
from datetime import datetime

log = logging.getLogger(__name__)

# ─── Initialization ───────────────────────────────────────────────────────────

load_dotenv()

_api_key = os.getenv("GOOGLE_API_KEY")
if not _api_key:
    raise ValueError("Kein GOOGLE_API_KEY in der .env gefunden!")

client = genai.Client(api_key=_api_key)

MODEL_NAME ='gemini-2.5-flash'

# ─── Tool Declarations for macOS Control ──────────────────────────────────────

mac_controller_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="execute_mac_command",
            description=(
                "Führt eine lokale Aktion auf dem macOS-System des Users aus. "
                "Nutze dieses Tool AUSSCHLIESSLICH, wenn der User explizit eine "
                "App öffnen oder einen Terminalbefehl ausführen möchte. "
                "Für normale Fragen oder Gespräche: Antworte DIREKT als Text."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "action_type": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Die Art der auszuführenden Aktion. "
                            "'open_app' = eine macOS-Anwendung öffnen. "
                            "'shell_command' = einen Terminal-Befehl ausführen."
                        ),
                        enum=["open_app", "shell_command"],
                    ),
                    "payload": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Bei 'open_app': Der exakte Name der App (z.B. 'Safari', 'Notability'). "
                            "Bei 'shell_command': Der vollständige Shell-Befehl (z.B. 'ls -la ~/Desktop')."
                        ),
                    ),
                },
                required=["action_type", "payload"],
            ),
        )
    ]
)

take_screenshot_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="take_screenshot",
            description=(
                "Macht einen Screenshot vom aktuellen Bildschirm des Users. "
                "Nutze dies IMMER, wenn der User dich bittet, sich etwas auf seinem "
                "Bildschirm anzusehen, Code zu prüfen oder visuelle Fragen zu beantworten."
            )
        )
    ]
)

web_search_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="web_search",
            description=(
                "Durchsucht das Internet nach AKTUELLEN oder faktischen Informationen. "
                "Nutze dies IMMER, wenn die Antwort von Echtzeit-Daten abhängt, die du "
                "nicht sicher aus deinem Training kennst: aktuelle Ereignisse, Nachrichten, "
                "Wetter, Preise, Sportergebnisse, kürzlich Veröffentlichtes, oder wann immer "
                "der User explizit nachschlagen/googeln möchte. Erfinde keine Fakten — such nach."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Die Suchanfrage in natürlicher Sprache.",
                    ),
                },
                required=["query"],
            ),
        )
    ]
)


def _build_system_prompt() -> str:
    """Build the Jarvis system instruction with current date/time."""
    now = datetime.now()
    aktuelles_datum = now.strftime("%A, der %d. %B %Y")
    aktuelle_uhrzeit = now.strftime("%H:%M Uhr")

    return (
        f"Du bist Jarvis, der persönliche KI-Assistent, Senior-Developer und "
        f"Sparringspartner des Users. "
        f"HEUTE IST: {aktuelles_datum}, es ist {aktuelle_uhrzeit}, was die Gegenwart ist. "
        "DEINE PERSÖNLICHKEIT: Du bist brillant, direkt, loyal und hast einen "
        "subtilen, trockenen Humor. Du redest nicht um den heißen Brei herum. "
        "DEINE DIREKTIVEN FÜR WERKZEUGE: "
        "1. MAC-STEUERUNG: Wenn der User eine App öffnen oder einen Terminal-Befehl "
        "ausführen will, nutze IMMER das Tool 'execute_mac_command'. "
        "2. PROAKTIVES GEDÄCHTNIS (WICHTIG!): Wenn der User dir beiläufig Vorlieben, "
        "Pläne, Frust oder Fakten über sein Leben erzählt, nutze SOFORT im Hintergrund "
        "'save_memory'. Sag ihm danach in deiner Antwort beiläufig, dass du dir das gemerkt hast! "
        "3. VERGANGENHEIT NUTZEN: Bevor du Fragen zum User beantwortest, nutze IMMER 'recall_memory'. "
        "4. KEIN MARKDOWN IN DER SPRACHE: Vermeide zwingend Sternchen (*) oder Hashtags (#) "
        "in deiner Textantwort, da diese vom Audio-System (TTS) sonst laut vorgelesen werden. "
        "Sei ein mitdenkender Assistent, kein dummer Chatbot. Biete Lösungen an, bevor der User danach fragt."
    )


# ─── Gemini Response Generation ──────────────────────────────────────────────

# Import the memory tools so they can be registered as callable functions
from app.memory import save_memory, recall_memory, get_memory_stats


def _history_to_contents(history: list[dict]) -> list[types.Content]:
    """Convert session history dicts ({'role', 'text'}) into Gemini Content turns."""
    return [
        types.Content(
            role=turn["role"],
            parts=[types.Part.from_text(text=turn["text"])],
        )
        for turn in history
        if turn.get("text")
    ]


def get_gemini_response(
    user_text: str,
    history: list[dict] | None = None,
) -> types.GenerateContentResponse:
    """
    Send user text to Gemini with all tools enabled and return the raw response.

    The model can choose to:
        a) Return a text response directly.
        b) Call the execute_mac_command tool (function call).
        c) Call memory tools (save_memory, recall_memory, get_memory_stats).

    Args:
        user_text: The user's message text.
        history: Prior conversation turns as dicts with 'role' ('user' | 'model')
                 and 'text' keys. Gives the model multi-turn context.

    Returns:
        The raw Gemini GenerateContentResponse (caller inspects .text or .function_calls).
    """
    contents: list[types.Content] = _history_to_contents(history or [])
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            tools=[mac_controller_tool, take_screenshot_tool, web_search_tool, save_memory, recall_memory, get_memory_stats],
            temperature=0.1,
        ),
    )
    return response


# ─── Web Search (Google Search Grounding) ─────────────────────────────────────
#
# google_search grounding cannot share a request with FunctionDeclarations, so
# `web_search` is declared as a normal function tool the model can pick, and we
# fulfil it here with a separate grounding-only call. Read-only by design: the
# model reads search results and answers; it never gains a way to act on the web.


def search_web(query: str, history: list[dict] | None = None) -> str:
    """
    Answer a query with live Google Search grounding.

    Args:
        query: Natural-language search query the model requested.
        history: Prior conversation turns, so follow-ups like "und morgen?"
                 keep the context of the previous search.

    Returns:
        Gemini's grounded, natural-language answer (with current web data).
    """
    log.info("Web-Suche: %s", query)
    contents: list[types.Content] = _history_to_contents(history or [])
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=query)])
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        ),
    )
    return response.text or ""


# ─── Memory Tool Dispatch ─────────────────────────────────────────────────────
#
# Automatic Function Calling (AFC) is disabled by the SDK whenever the tool list
# mixes manual FunctionDeclarations (mac_controller_tool, take_screenshot_tool)
# with Python callables. The mac tools MUST stay manual so every shell command
# is gated through security.py — so we run the memory callables ourselves and
# feed the result back to the model for a natural-language reply.

_MEMORY_TOOLS = {
    "save_memory": save_memory,
    "recall_memory": recall_memory,
    "get_memory_stats": get_memory_stats,
}


def is_memory_tool(name: str) -> bool:
    """True if `name` is one of the locally-dispatched memory tools."""
    return name in _MEMORY_TOOLS


def handle_memory_tool(
    function_call: types.FunctionCall,
    user_text: str,
    history: list[dict] | None = None,
) -> str:
    """
    Execute a memory tool the model requested, then ask the model to phrase the
    final answer given the tool's result.

    Args:
        function_call: The FunctionCall Gemini emitted (name + args).
        user_text: The original user message that triggered the call.
        history: Prior conversation turns for context.

    Returns:
        Gemini's natural-language reply after seeing the tool result.
    """
    fn = _MEMORY_TOOLS[function_call.name]
    args = dict(function_call.args or {})
    tool_result = fn(**args)
    log.info("Memory-Tool ausgeführt: %s(%s)", function_call.name, args)

    # Rebuild the conversation: user turn → model's function_call turn →
    # our function_response turn, then let the model answer in words.
    contents: list[types.Content] = _history_to_contents(history or [])
    contents.append(
        types.Content(role="user", parts=[types.Part.from_text(text=user_text)])
    )
    contents.append(
        types.Content(role="model", parts=[types.Part(function_call=function_call)])
    )
    contents.append(
        types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name=function_call.name,
                    response={"result": tool_result},
                )
            ],
        )
    )

    # No tools on the follow-up call → force a plain-text answer.
    followup = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            temperature=0.1,
        ),
    )
    return followup.text or tool_result


def get_vision_response(user_text: str, image_bytes: bytes) -> str:
    """
    Analyze a screenshot with Gemini Vision, keeping the Jarvis persona.

    Args:
        user_text: The user's question about the screen.
        image_bytes: JPEG-compressed screenshot bytes.

    Returns:
        The model's text answer (empty string if the model returned none).
    """
    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[user_text, image_part],
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            temperature=0.1,
        ),
    )
    return response.text or ""


# ─── NLP Intent Analyzer for HitL Flow ───────────────────────────────────────

_HITL_CLASSIFIER_PROMPT = """Du bist ein strikter Intent-Classifier. 
Der User wurde gefragt, ob ein gefährlicher Befehl auf seinem Mac ausgeführt werden darf.
Deine EINZIGE Aufgabe: Klassifiziere die Antwort des Users.

REGELN:
- Antworte AUSSCHLIESSLICH mit einem der drei Wörter: APPROVE, DENY, UNCLEAR
- APPROVE = Der User stimmt zu (z.B. "Ja", "Mach das", "Klar", "Go", "Okay", "Alles klar")
- DENY = Der User lehnt ab (z.B. "Nein", "Stopp", "Abbrechen", "Lass das", "Vergiss es")  
- UNCLEAR = Die Antwort ist unklar oder hat nichts mit der Bestätigung zu tun

Der ausstehende Befehl war: "{command}"
Die Antwort des Users: "{user_text}"

Deine Klassifikation:"""


def analyze_user_intent(user_text: str, command: str) -> str:
    """
    Use Gemini as an NLP classifier to determine if the user approves
    or denies a pending dangerous command.

    Args:
        user_text: The user's voice/text response.
        command: The shell command that is awaiting approval.

    Returns:
        Exactly one of: "APPROVE", "DENY", or "UNCLEAR".
    """
    prompt = _HITL_CLASSIFIER_PROMPT.format(
        command=command,
        user_text=user_text,
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
            ),
        )

        raw_intent = (response.text or "").strip().upper()

        # Fail closed: if the classifier output mentions both tokens,
        # denial wins — never execute on an ambiguous answer.
        if "DENY" in raw_intent:
            return "DENY"
        elif "APPROVE" in raw_intent:
            return "APPROVE"
        else:
            return "UNCLEAR"

    except Exception as e:
        log.error("Intent-Analyse fehlgeschlagen: %s", e)
        return "UNCLEAR"

"""
Gassi-Jarvis — Gemini LLM Agent (Layer 3: Orchestrator + Layer 4: Brain)

Handles all communication with the Google Gemini API:
    - Tool declarations for macOS control (open_app, shell_command).
    - Gemini response generation with function calling enabled.
    - NLP-based intent analysis for HitL approval/denial classification.
"""

import os

from google import genai
from google.genai import types
from dotenv import load_dotenv
from datetime import datetime

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
            tools=[mac_controller_tool, take_screenshot_tool, save_memory, recall_memory, get_memory_stats],
            temperature=0.1,
        ),
    )
    return response


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
        print(f"[AGENT] Intent-Analyse fehlgeschlagen: {e}")
        return "UNCLEAR"

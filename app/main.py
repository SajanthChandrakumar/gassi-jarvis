"""
Gassi-Jarvis — FastAPI Gateway (Layer 2: Route Controller)

This is the single entry point for all client requests.
It orchestrates the full request lifecycle:

    1. HitL Interceptor — Check for pending dangerous commands awaiting approval.
    2. LLM Call         — Send user text to Gemini via the agent module.
    3. Tool Executor    — Handle function calls (open_app / shell_command).
    4. Text Passthrough — Return plain LLM responses when no tools are triggered.

All business logic is delegated to the respective microservice modules:
    - models.py   → Pydantic validation
    - memory.py   → Session state + ChromaDB
    - agent.py    → Gemini LLM + tool declarations
    - security.py → Command threat classification + subprocess execution
"""

import base64
import json
import logging
import os
import re
import secrets
import subprocess

import edge_tts
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.logging_config import setup_logging
from app.models import ChatRequest, ChatResponse
from app.memory import (
    get_session,
    clear_pending_command,
    set_pending_command,
    get_pending_command,
    get_pending_action_type,
    record_turn,
    last_reply_tainted,
)
from app import gcal
from app.agent import (
    get_gemini_response,
    get_vision_response,
    analyze_user_intent,
    is_memory_tool,
    handle_memory_tool,
    search_web,
)
from app.security import evaluate_security_level, execute_shell_command
from app.vision import capture_and_compress_screen

setup_logging()
log = logging.getLogger(__name__)

# ─── Server Setup ─────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title="Gassi-Jarvis Gateway",
    description="Voice-controlled AI Assistant & LAM — FastAPI Backend",
    version="2.0.0",
)

# ─── Rate limiting ────────────────────────────────────────────────────────────
# Caps brute-force token guessing on /api/chat.
#
# Behind a tunnel (ngrok/Tailscale) the TCP peer is always 127.0.0.1, so keying
# on the raw remote address would lump every phone and every attacker into one
# global bucket — the legit user could self-lock, and per-client limiting would
# be meaningless. Prefer the originating client from X-Forwarded-For instead.
#
# Caveat: X-Forwarded-For is client-spoofable, so this is not a hard
# anti-brute-force guarantee — the bearer token remains the real wall. It does
# stop the shared-bucket problem and raises the bar for casual abuse. Run uvicorn
# with --forwarded-allow-ips so the header is trusted from the tunnel.
def _client_key(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        # Leftmost entry is the original client the tunnel saw.
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins for the PWA frontend.
# Defaults to localhost only — set JARVIS_ALLOWED_ORIGINS to your phone/PWA URL.
_origins_env = os.environ.get("JARVIS_ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _origins_env.split(",") if o.strip()] or [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ─── Static assets (PWA manifest, icons, service worker) ──────────────────────
# Serves the contents of app/static at /static — used by the PWA manifest and
# its icons. index.html itself is served from "/" (see get_index below).
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static",
)

TTS_VOICE = "de-DE-KillianNeural"

# App names passed to AppleScript may only contain these characters.
# Blocks quote/backslash breakouts into arbitrary AppleScript.
_SAFE_APP_NAME = re.compile(r"^[A-Za-z0-9 ._\-]{1,64}$")

# Markdown links [text](url) → keep just the visible text.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
# Bare URLs the model may cite (grounding answers love these); TTS would spell
# them out letter by letter, so replace with a short spoken placeholder.
_BARE_URL = re.compile(r"\b(?:https?://|www\.)\S+")


def _clean_for_tts(text: str) -> str:
    """Strip Markdown artifacts and URLs so Edge-TTS doesn't read them aloud."""
    text = _MD_LINK.sub(r"\1", text)
    text = _BARE_URL.sub("(Link)", text)
    text = text.replace("*", "").replace("#", "").replace("- ", " ")
    # Collapse whitespace left behind by removals.
    return re.sub(r"[ \t]{2,}", " ", text).strip()


# ─── Auth ─────────────────────────────────────────────────────────────────────

API_TOKEN = os.environ.get("JARVIS_API_TOKEN", "")

_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}

if not API_TOKEN:
    log.warning(
        "JARVIS_API_TOKEN ist nicht gesetzt. "
        "/api/chat akzeptiert nur Requests von localhost. "
        "Für Zugriff vom Handy: Token in .env setzen."
    )


async def verify_token(request: Request) -> None:
    """
    Gate /api/chat behind a bearer token.

    If JARVIS_API_TOKEN is unset, only localhost may connect (safe local dev).
    If set, every request must carry 'Authorization: Bearer <token>'.
    """
    if not API_TOKEN:
        client_host = request.client.host if request.client else ""
        if client_host not in _LOCALHOST_ADDRS:
            raise HTTPException(
                status_code=401,
                detail="Remote-Zugriff erfordert JARVIS_API_TOKEN auf dem Server.",
            )
        return

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, API_TOKEN):
        raise HTTPException(status_code=401, detail="Ungültiger oder fehlender API-Token.")


# ─── Helper: Text-to-Speech ──────────────────────────────────────────────────


async def _generate_tts_audio(text: str) -> str:
    """
    Generate base64-encoded MP3 audio from text using Edge-TTS.

    Args:
        text: The text to synthesize (Markdown artifacts are stripped).

    Returns:
        Base64-encoded audio string, or empty string on failure.
    """
    # Strip Markdown artifacts and URLs that TTS would otherwise read aloud.
    clean_text = _clean_for_tts(text)

    try:
        communicate = edge_tts.Communicate(clean_text, TTS_VOICE)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        return base64.b64encode(audio_data).decode("utf-8")

    except Exception as e:
        log.error("TTS Audio-Generierung fehlgeschlagen: %s", e)
        return ""


# ─── Helper: Build JSON Response ─────────────────────────────────────────────


async def _build_response(
    text: str,
    action: str = "none",
    generate_audio: bool = True,
) -> dict:
    """
    Build the standard JSON response dict with optional TTS audio.

    Args:
        text: Jarvis' text response.
        action: Description of the action taken.
        generate_audio: Whether to generate TTS audio.

    Returns:
        Dict matching the API response contract.
    """
    audio_b64 = await _generate_tts_audio(text) if generate_audio else ""

    return {
        "status": "success",
        "jarvis_response": text,
        "audio_base64": audio_b64,
        "action_taken": action,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.get("/")
async def get_index():
    """Serve the frontend PWA."""
    index_path = os.path.join(BASE_DIR, "static", "index.html")
    if not os.path.exists(index_path):
        return {"error": "index.html nicht im Ordner app/static gefunden!"}
    return FileResponse(index_path)


@app.get("/sw.js")
async def get_service_worker():
    """
    Serve the service worker from the site root.

    A service worker can only control pages within its own URL scope, so the
    file must be served from "/" (not "/static/") for it to control the PWA.
    'no-cache' lets the browser pick up a new worker on each visit.
    """
    sw_path = os.path.join(BASE_DIR, "static", "sw.js")
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/chat", response_model=ChatResponse, dependencies=[Depends(verify_token)])
@limiter.limit("20/minute")
async def chat_with_jarvis(request: Request, chat: ChatRequest):
    """
    Main chat endpoint implementing the full Jarvis request lifecycle.

    Flow:
        Step 1 — HitL Interceptor: If a dangerous command is pending,
                 classify user intent (APPROVE / DENY / UNCLEAR).
        Step 2 — LLM Call: Send user text to Gemini (with session history).
        Step 3 — Tool Executor: Handle function_calls from Gemini.
        Step 4 — Text Passthrough: Return plain text if no tools fired.
    """
    user_text = chat.payload.content.strip()
    session_id = chat.session_id
    session = get_session(session_id)

    async def respond(text: str, action: str = "none", tainted: bool = False) -> dict:
        """Record the exchange in session history, then build the response.

        `tainted` marks replies built from externally-sourced content (screen
        capture, web search, recalled memory) so a follow-up shell command is
        forced through HitL — see last_reply_tainted.
        """
        record_turn(session_id, user_text, text, tainted=tainted)
        return await _build_response(text=text, action=action)

    try:
        # ──────────────────────────────────────────────────────────────────
        # STEP 1: HitL Interceptor — Check for pending dangerous commands
        # ──────────────────────────────────────────────────────────────────
        pending_cmd = get_pending_command(session_id)
        if pending_cmd is not None:
            pending_type = get_pending_action_type(session_id)

            # Human-readable form for the intent classifier and re-prompts —
            # calendar payloads are JSON and would be ugly to read aloud.
            if pending_type == "calendar_create":
                try:
                    pending_display = gcal.describe_event(json.loads(pending_cmd))
                except (json.JSONDecodeError, TypeError):
                    pending_display = pending_cmd
            else:
                pending_display = pending_cmd

            log.info("HitL ausstehend (%s): %r — analysiere Antwort", pending_type, pending_display)

            intent = analyze_user_intent(user_text, pending_display)
            log.info("HitL Intent-Klassifikation: %s", intent)

            if intent == "APPROVE":
                clear_pending_command(session_id)

                if pending_type == "calendar_create":
                    try:
                        result_text = gcal.create_event(pending_cmd)
                    except gcal.CalendarNotConfigured as e:
                        return await respond(text=str(e), action="calendar_not_configured")
                    except Exception as e:
                        log.error("Kalender-Eintrag fehlgeschlagen: %s", e)
                        return await respond(
                            text="Der Termin konnte leider nicht eingetragen werden.",
                            action="calendar_error",
                        )
                    return await respond(
                        text=result_text,
                        action=f"calendar_event_created: {pending_display}",
                    )

                # Default: approved shell command → execute with force=True.
                output = execute_shell_command(pending_cmd, force=True)
                response_text = (
                    f"Verstanden. Befehl wird ausgeführt.\n\n"
                    f"Ergebnis:\n{output}"
                )
                return await respond(
                    text=response_text,
                    action=f"hitl_approved: {pending_cmd}",
                )

            elif intent == "DENY":
                # User hat abgelehnt → Aktion verwerfen
                clear_pending_command(session_id)
                return await respond(
                    text="Alles klar. Wurde abgebrochen. Ich führe nichts aus.",
                    action="hitl_denied",
                )

            else:
                # Intent unklar → nochmal nachfragen
                return await respond(
                    text=(
                        f"Ich konnte deine Antwort nicht eindeutig zuordnen. "
                        f"Die ausstehende Aktion ist: '{pending_display}'. "
                        f"Sag bitte klar 'Ja, mach das' oder 'Nein, abbrechen'."
                    ),
                    action="hitl_unclear",
                )

        # ──────────────────────────────────────────────────────────────────
        # STEP 2: LLM Call — Send to Gemini
        # ──────────────────────────────────────────────────────────────────
        log.debug("User-Input an Gemini: %r", user_text)

        try:
            response = get_gemini_response(user_text, history=session["history"])
        except Exception as e:
            error_str = str(e)
            log.error("Gemini API-Fehler: %s", error_str)

            # Treat any 5xx / 429 / quota / overload signal as a transient
            # upstream issue and degrade gracefully instead of 500ing the client.
            status_code = getattr(e, "status_code", None) or getattr(e, "code", None)
            transient = (
                status_code in {429, 500, 502, 503, 504}
                or "quota" in error_str.lower()
                or "rate" in error_str.lower()
                or "overload" in error_str.lower()
                or "unavailable" in error_str.lower()
            )
            if transient:
                fallback_text = (
                    "Meine Serververbindung zu Google ist gerade überlastet. "
                    "Lass uns kurz eine Minute warten."
                )
                return await respond(
                    text=fallback_text,
                    action="api_rate_limit_handled",
                )

            # Don't leak internal exception text to the client.
            raise HTTPException(
                status_code=500,
                detail="Brain connection lost.",
            )

        # ──────────────────────────────────────────────────────────────────
        # STEP 3: Tool Executor — Handle function calls from Gemini
        # ──────────────────────────────────────────────────────────────────
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    log.info("Tool Function Call: %s → %s", fc.name, fc.args)

                    if fc.name == "execute_mac_command":
                        action_type = fc.args.get("action_type", "")
                        payload = fc.args.get("payload", "")

                        # ── 3a: open_app → Direct execution via osascript ──
                        if action_type == "open_app":
                            # Strict allowlist on the app name: anything with
                            # quotes/backslashes could break out of the
                            # AppleScript string and run arbitrary script,
                            # bypassing the security router entirely.
                            if not _SAFE_APP_NAME.match(payload):
                                return await respond(
                                    text=(
                                        f"Den App-Namen '{payload}' habe ich "
                                        f"abgelehnt — er enthält unzulässige Zeichen."
                                    ),
                                    action="open_app_rejected",
                                )
                            try:
                                subprocess.run(
                                    [
                                        "osascript",
                                        "-e",
                                        f'tell application "{payload}" to activate',
                                    ],
                                    capture_output=True,
                                    text=True,
                                    timeout=10,
                                )
                                response_text = f"Erledigt. {payload} wurde geöffnet."
                                return await respond(
                                    text=response_text,
                                    action=f"open_app: {payload}",
                                )
                            except subprocess.TimeoutExpired:
                                return await respond(
                                    text=f"Timeout beim Öffnen von {payload}.",
                                    action="open_app_timeout",
                                )
                            except OSError as e:
                                return await respond(
                                    text=f"Fehler beim Öffnen von {payload}: {e}",
                                    action="open_app_error",
                                )

                        # ── 3b: shell_command → Security router ────────────
                        elif action_type == "shell_command":
                            threat_level = evaluate_security_level(payload)

                            # Indirect-injection guard: if the previous reply
                            # came from a screenshot / web search / recalled
                            # memory, a shell command proposed now may have been
                            # planted by injected text — force HitL regardless
                            # of the command's own threat level.
                            tainted_context = last_reply_tainted(session_id)
                            log.info(
                                "Security: cmd=%r → threat_level=%s tainted_ctx=%s",
                                payload, threat_level, tainted_context,
                            )

                            if threat_level >= 2 or tainted_context:
                                # DANGEROUS (or injection-suspect): ask first.
                                set_pending_command(session_id, payload)

                                if tainted_context and threat_level < 2:
                                    warning_text = (
                                        f"Sicherheitshinweis: Der Befehl '{payload}' "
                                        f"folgt direkt auf extern gelesene Inhalte "
                                        f"(Screenshot/Web/Gedächtnis). Zur Sicherheit "
                                        f"frage ich nach — soll ich ihn ausführen? "
                                        f"Bestätige mit 'Ja' oder sage 'Nein'."
                                    )
                                else:
                                    warning_text = (
                                        f"Achtung! Der Befehl '{payload}' wurde als "
                                        f"potenziell gefährlich eingestuft (Stufe {threat_level}). "
                                        f"Soll ich ihn trotzdem ausführen? "
                                        f"Bestätige mit 'Ja' oder sage 'Nein' zum Abbrechen."
                                    )
                                return await respond(
                                    text=warning_text,
                                    action=f"hitl_pending: {payload}",
                                )
                            else:
                                # SAFE: Execute immediately
                                output = execute_shell_command(payload)
                                response_text = (
                                    f"Befehl ausgeführt.\n\nErgebnis:\n{output}"
                                )
                                return await respond(
                                    text=response_text,
                                    action=f"shell_executed: {payload}",
                                )

                        else:
                            return await respond(
                                text=f"Unbekannter Aktionstyp: {action_type}",
                                action="unknown_action_type",
                            )

                    elif fc.name == "take_screenshot":
                        log.info("Vision: nehme Screenshot auf")
                        try:
                            image_bytes = capture_and_compress_screen()
                        except (PermissionError, FileNotFoundError) as e:
                            return await respond(
                                text=str(e),
                                action="screenshot_failed",
                            )
                        except Exception as e:
                            return await respond(
                                text=f"Unerwarteter Fehler beim Screenshot: {e}",
                                action="screenshot_error",
                            )

                        log.info("Vision: Screenshot erstellt, sende an Gemini Vision")

                        try:
                            vision_text = get_vision_response(user_text, image_bytes)
                            if not vision_text:
                                vision_text = "Ich konnte das Bild leider nicht auswerten."
                            return await respond(
                                text=vision_text,
                                action="vision_screenshot_analyzed",
                                tainted=True,  # screen content may carry injected text
                            )
                        except Exception as e:
                            log.error("Vision Bildanalyse fehlgeschlagen: %s", e)
                            return await respond(
                                text="Die Bildanalyse ist leider fehlgeschlagen.",
                                action="vision_analysis_error",
                            )

                    # ── Web search (Google Search grounding) ────────────────
                    elif fc.name == "web_search":
                        query = fc.args.get("query", "").strip()
                        log.info("Web-Suche angefordert: %r", query)
                        try:
                            search_text = search_web(query, history=session["history"])
                            if not search_text:
                                search_text = (
                                    "Ich habe dazu online leider nichts Brauchbares gefunden."
                                )
                            return await respond(
                                text=search_text,
                                action=f"web_search: {query}",
                                tainted=True,  # web results may carry injected text
                            )
                        except Exception as e:
                            log.error("Web-Suche fehlgeschlagen: %s", e)
                            return await respond(
                                text="Die Websuche ist gerade fehlgeschlagen.",
                                action="web_search_error",
                            )

                    # ── Calendar: read events ───────────────────────────────
                    elif fc.name == "get_calendar_events":
                        try:
                            cal_text = gcal.list_events(
                                date=str(fc.args.get("date", "") or ""),
                                days=int(fc.args.get("days", 1) or 1),
                            )
                            return await respond(
                                text=cal_text,
                                action="calendar_read",
                                # Event titles can come from other people's
                                # invitations — treat as external content.
                                tainted=True,
                            )
                        except gcal.CalendarNotConfigured as e:
                            return await respond(text=str(e), action="calendar_not_configured")
                        except Exception as e:
                            log.error("Kalender-Abruf fehlgeschlagen: %s", e)
                            return await respond(
                                text="Ich komme gerade nicht an deinen Kalender heran.",
                                action="calendar_error",
                            )

                    # ── Calendar: create event (HitL-gated) ─────────────────
                    elif fc.name == "create_calendar_event":
                        summary = str(fc.args.get("summary", "") or "").strip()
                        start = str(fc.args.get("start", "") or "").strip()
                        if not summary or not start:
                            return await respond(
                                text="Mir fehlt noch Titel oder Startzeit für den Termin.",
                                action="calendar_event_incomplete",
                            )
                        event = {
                            "summary": summary,
                            "start": start,
                            "end": str(fc.args.get("end", "") or ""),
                            "description": str(fc.args.get("description", "") or ""),
                        }
                        try:
                            display = gcal.describe_event(event)
                        except Exception:
                            display = summary
                        set_pending_command(
                            session_id, json.dumps(event, ensure_ascii=False),
                            action_type="calendar_create",
                        )
                        return await respond(
                            text=(
                                f"Ich würde eintragen: {display}. "
                                f"Soll ich das machen? Bestätige mit 'Ja' oder sage 'Nein'."
                            ),
                            action=f"hitl_pending: {display}",
                        )

                    # ── Memory tools (save/recall/stats) ────────────────────
                    # AFC is off (mixed tool list), so we dispatch these
                    # ourselves and let Gemini phrase the final answer.
                    elif is_memory_tool(fc.name):
                        try:
                            memory_text = handle_memory_tool(
                                fc, user_text, history=session["history"]
                            )
                            return await respond(
                                text=memory_text,
                                action=f"memory:{fc.name}",
                                # recalled memory may carry injected text; save/
                                # stats are self-generated and stay untainted.
                                tainted=(fc.name == "recall_memory"),
                            )
                        except Exception as e:
                            log.error("Memory-Tool %s fehlgeschlagen: %s", fc.name, e)
                            return await respond(
                                text="Beim Zugriff auf mein Gedächtnis ist etwas schiefgelaufen.",
                                action="memory_error",
                            )

        # ──────────────────────────────────────────────────────────────────
        # STEP 4: Text Passthrough — No function calls, return LLM text
        # ──────────────────────────────────────────────────────────────────
        response_text = response.text if response.text else "Ich konnte leider keine Antwort generieren."
        return await respond(
            text=response_text,
            action="text_response",
        )

    except HTTPException:
        # Re-raise FastAPI HTTP exceptions as-is
        raise
    except Exception as e:
        log.exception("Unbehandelter Fehler im Chat-Endpoint: %s", e)
        # Avoid surfacing internal exception details over the wire.
        raise HTTPException(
            status_code=500,
            detail="Interner Serverfehler.",
        )
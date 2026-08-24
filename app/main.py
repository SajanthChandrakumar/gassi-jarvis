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
    - device/    → Local Mac capability boundary
"""

import base64
import json
import logging
import os
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

# aiohttp/OpenBB can create its shared TLS context while importing other
# integrations. Configure the virtual environment CA bundle before those
# imports so macOS framework Python validates provider certificates correctly.
try:
    import certifi
except ImportError:  # pragma: no cover - requirements pin certifi in production
    certifi = None
if certifi is not None:
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import edge_tts
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.logging_config import setup_logging
from app.models import ChatRequest, ChatResponse, RecentMemoriesResponse, ResearchRunRequest
from app.memory import (
    get_session,
    clear_pending_command,
    set_pending_command,
    get_pending_command,
    get_pending_action_type,
    record_turn,
    last_reply_tainted,
    get_recent_memories,
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
from app.device.cloud import DeviceGateway
from app.device.models import DeviceUnavailable
from app.device.routes import router as device_router, validate_token_configuration
from app.trading.research.jarvis_tools import (
    JarvisResearchTools,
    crypto_asset_from_research_question,
    macro_context_payload,
    render_research_response,
    response_payload,
)
from app.trading.research.provider_status import provider_status_payload

setup_logging()
log = logging.getLogger(__name__)

# The OpenBB client behind this adapter is lazy; construction itself performs
# neither network access nor financial calculations.
research_tools = JarvisResearchTools()

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

# The cloud process owns only the durable device-intent queue.  The Mac agent
# is the sole process that imports local security, AppleScript, shell, or
# screenshot implementations.
device_gateway = DeviceGateway(
    vision_analyzer=lambda prompt, image: get_vision_response(prompt, image),
)
app.state.device_gateway = device_gateway
app.state.jarvis_api_token = lambda: API_TOKEN
app.state.jarvis_device_token = lambda: os.environ.get("JARVIS_DEVICE_TOKEN", "")
# Fail during configuration rather than allowing one secret to cross the
# browser/device trust boundary.  Route-level checks remain as a fail-closed
# guard for applications that mount the router independently.
validate_token_configuration(API_TOKEN, os.environ.get("JARVIS_DEVICE_TOKEN", ""))
app.include_router(device_router)

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
        auth_header = request.headers.get("Authorization", "")
        if auth_header.removeprefix("Bearer ").strip():
            raise HTTPException(
                status_code=401,
                detail="Bearer token requires JARVIS_API_TOKEN on the server.",
            )
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
    research_payload: dict | None = None,
    device_action: dict | None = None,
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
        "research_payload": research_payload,
        "device_action": device_action,
    }


def _device_json(value: object) -> dict | None:
    """Serialize a cloud device contract without leaking opaque internals."""

    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value if isinstance(value, dict) else None


async def _dispatch_device_action(
    *,
    action_type: str,
    payload: str,
    tainted: bool = False,
    requires_approval: bool = False,
) -> tuple[str, str, dict | None]:
    """Queue one local capability and wait only a bounded amount of time.

    The cloud never executes the payload.  If the agent is offline this returns
    a structured unavailable result immediately; otherwise the short wait lets
    a connected agent complete safe actions without making research/chat
    availability depend on a Mac heartbeat.
    """

    queued = device_gateway.queue_action(
        action_type,
        payload,
        tainted=tainted,
        requires_approval=requires_approval,
    )
    if isinstance(queued, DeviceUnavailable):
        return (
            "Der Mac-Agent ist gerade nicht verfügbar. Die Aktion wurde nicht ausgeführt.",
            "device_unavailable",
            _device_json(queued),
        )

    lifecycle = device_gateway.wait_for_result(queued.action_id, timeout=0.25)
    if lifecycle is None:
        return (
            "Die Aktion wurde an den Mac-Agenten übergeben und wartet auf seinen Status.",
            "device_queued",
            _device_json(queued),
        )
    if lifecycle.unavailable is not None:
        return (
            "Der Mac-Agent ist gerade nicht verfügbar. Die Aktion wurde nicht ausgeführt.",
            "device_unavailable",
            _device_json(lifecycle),
        )
    if lifecycle.result is not None:
        if lifecycle.analysis:
            return lifecycle.analysis, "vision_screenshot_analyzed", _device_json(lifecycle)
        result = lifecycle.result
        if result.status == "succeeded":
            return result.output or "Die Aktion wurde ausgeführt.", result.action or "device_action_succeeded", _device_json(lifecycle)
        return result.error or "Die Aktion konnte nicht ausgeführt werden.", "device_action_failed", _device_json(lifecycle)
    if lifecycle.status == "awaiting_approval":
        return (
            "Der Mac-Agent benötigt eine Bestätigung für diese Aktion.",
            "device_approval_required",
            _device_json(lifecycle),
        )
    return (
        "Die Aktion wurde an den Mac-Agenten übergeben und wartet auf seinen Status.",
        "device_queued",
        _device_json(lifecycle),
    )


# ─── Routes ───────────────────────────────────────────────────────────────────


@app.get("/")
async def get_index():
    """Serve the frontend PWA."""
    index_path = os.path.join(BASE_DIR, "static", "index.html")
    if not os.path.exists(index_path):
        return {"error": "index.html nicht im Ordner app/static gefunden!"}
    return FileResponse(index_path)


@app.get("/config.js")
async def get_frontend_config():
    """Serve the runtime API origin without allowing browser caching."""
    configured = os.environ.get("JARVIS_FRONTEND_API_BASE_URL", "").strip()
    api_base_url = ""
    if configured:
        try:
            if any(char.isspace() or ord(char) < 0x20 for char in configured):
                raise ValueError("whitespace")
            parsed = urlsplit(configured)
            if (
                parsed.scheme.lower() not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or "?" in configured
                or "#" in configured
                or not parsed.hostname
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("invalid URL form")
            parsed.port  # Trigger validation for malformed ports.
            api_base_url = urlunsplit(
                (parsed.scheme.lower(), parsed.netloc, "", "", "")
            )
        except (TypeError, ValueError):
            log.warning(
                "Invalid JARVIS_FRONTEND_API_BASE_URL; using same-origin frontend API requests"
            )
    script = "window.JARVIS_CONFIG = { apiBaseUrl: " + json.dumps(api_base_url) + " };"
    return Response(
        content=script,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


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


@app.get(
    "/api/memories/recent",
    response_model=RecentMemoriesResponse,
    dependencies=[Depends(verify_token)],
)
@limiter.limit("10/minute")
async def recent_memories(request: Request) -> RecentMemoriesResponse:
    """
    Zuletzt gemerkte Fakten, LLM-frei — für externe Dashboards (z.B. Homepage
    Custom-API-Widget). Reiner ChromaDB-Read, kein Gemini-Call, keine
    Session-/HitL-Beteiligung.
    """
    return RecentMemoriesResponse(memories=get_recent_memories(n=5))


@app.get("/api/research/providers", dependencies=[Depends(verify_token)])
@limiter.limit("20/minute")
async def research_provider_status(request: Request) -> dict[str, list[dict[str, object]]]:
    """Expose non-secret OpenBB provider readiness for the local research UI."""
    return provider_status_payload()


@app.get("/api/research/macro", dependencies=[Depends(verify_token)])
@limiter.limit("20/minute")
async def research_macro_context(request: Request) -> dict[str, list[dict]]:
    """Return a compact canonical macro context without invoking Gemini."""
    return macro_context_payload(research_tools.orchestrator.canonical_service)


@app.post("/api/research/run", response_model=ChatResponse, dependencies=[Depends(verify_token)])
@limiter.limit("20/minute")
async def run_research_workflow(request: Request, research: ResearchRunRequest) -> dict:
    """Run a validated read-only research workflow without relying on LLM routing."""
    if research.mode == "asset":
        name, arguments = "research_asset", {"asset": research.asset, "timeframe": research.timeframe}
    elif research.mode == "compare":
        name, arguments = "compare_assets", {"left_asset": research.asset, "right_asset": research.benchmark, "timeframe": research.timeframe}
    elif research.mode == "history":
        name, arguments = "research_history", {"asset": research.asset, "timeframe": research.timeframe}
    else:
        name, arguments = "analyze_relationship", {"asset": research.asset, "benchmark": research.benchmark, "timeframe": research.timeframe, "analysis": research.analysis}
    response = research_tools.dispatch(name, arguments)
    return await _build_response(
        render_research_response(response),
        action=f"finance_research:{name}",
        research_payload=response_payload(response),
        generate_audio=False,
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

    async def respond(
        text: str,
        action: str = "none",
        tainted: bool = False,
        research_payload: dict | None = None,
        device_action: dict | None = None,
    ) -> dict:
        """Record the exchange in session history, then build the response.

        `tainted` marks replies built from externally-sourced content (screen
        capture, web search, recalled memory) so a follow-up shell command is
        forced through HitL — see last_reply_tainted.
        """
        record_turn(session_id, user_text, text, tainted=tainted)
        return await _build_response(
            text=text,
            action=action,
            research_payload=research_payload,
            device_action=device_action,
        )

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

                # Legacy pending shell commands are no longer executed in the
                # cloud.  New device approvals arrive through the explicit
                # action-id API; this branch only handles a pending id that a
                # prior compatible session stored.
                if pending_type and pending_type.startswith("device:"):
                    action_id = pending_type.split(":", 1)[1]
                    try:
                        lifecycle = device_gateway.decide(action_id, approved=True)
                    except (KeyError, ValueError) as exc:
                        return await respond(
                            text="Die ausstehende Geräteaktion ist nicht mehr verfügbar.",
                            action="device_action_unavailable",
                        )
                    return await respond(
                        text="Verstanden. Der Mac-Agent erhält die bestätigte Aktion.",
                        action="device_approval_accepted",
                        device_action=_device_json(lifecycle),
                    )
                return await respond(
                    text="Diese lokale Aktion stammt noch aus dem alten Sitzungsformat. Bitte erneut anfordern.",
                    action="device_legacy_pending",
                )

            elif intent == "DENY":
                # User hat abgelehnt → Aktion verwerfen
                clear_pending_command(session_id)
                if pending_type and pending_type.startswith("device:"):
                    action_id = pending_type.split(":", 1)[1]
                    try:
                        lifecycle = device_gateway.decide(action_id, approved=False, reason="user denied")
                    except (KeyError, ValueError):
                        lifecycle = None
                    return await respond(
                        text="Alles klar. Wurde abgebrochen. Ich führe nichts aus.",
                        action="device_approval_denied",
                        device_action=_device_json(lifecycle),
                    )
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
        # Explicit BTC/ETH performance requests are a bounded read-only
        # research workflow. Route them deterministically so the chat model
        # cannot incorrectly claim that crypto research is unavailable.
        crypto_asset = crypto_asset_from_research_question(user_text)
        if crypto_asset:
            try:
                research_response = research_tools.research_asset(asset=crypto_asset)
                return await respond(
                    text=render_research_response(research_response),
                    action="finance_research:research_asset",
                    tainted=False,
                    research_payload=response_payload(research_response),
                )
            except Exception as e:
                log.error("Krypto-Finanzrecherche %s fehlgeschlagen: %s", crypto_asset, e)
                return await respond(
                    text="Die Krypto-Finanzrecherche ist gerade nicht verfügbar.",
                    action="finance_research_error",
                )

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
                        if action_type not in {"open_app", "shell_command"}:
                            return await respond(
                                text=f"Unbekannter Aktionstyp: {action_type}",
                                action="unknown_action_type",
                            )
                        # Threat classification remains on the Mac agent.  A
                        # tainted cloud context is carried as a force-approval
                        # hint; the agent independently reclassifies every
                        # shell command before execution.
                        tainted_context = last_reply_tainted(session_id)
                        text, action, device_action = await _dispatch_device_action(
                            action_type=action_type,
                            payload=str(payload),
                            tainted=tainted_context,
                            requires_approval=tainted_context,
                        )
                        return await respond(
                            text=text,
                            action=action,
                            device_action=device_action,
                        )

                    elif fc.name == "take_screenshot":
                        text, action, device_action = await _dispatch_device_action(
                            action_type="take_screenshot",
                            payload=user_text,
                        )
                        return await respond(
                            text=text,
                            action=action,
                            tainted=(action == "vision_screenshot_analyzed"),
                            device_action=device_action,
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

                    # ── Finance research (strictly read-only, Phase 7) ─────
                    elif fc.name in {"research_asset", "compare_assets", "research_history", "analyze_relationship"}:
                        try:
                            research_response = research_tools.dispatch(fc.name, dict(fc.args or {}))
                            return await respond(
                                text=render_research_response(research_response),
                                action=f"finance_research:{fc.name}",
                                # Provider-returned text is retained as data in the
                                # structured result and never re-enters the prompt.
                                tainted=False,
                                research_payload=response_payload(research_response),
                            )
                        except (TypeError, ValueError) as e:
                            log.info("Ungültige Finanzrecherche-Anfrage %s: %s", fc.name, e)
                            return await respond(
                                text="Die Finanzrecherche-Anfrage ist unvollständig oder ungültig.",
                                action="finance_research_invalid",
                            )
                        except Exception as e:
                            log.error("Finanzrecherche %s fehlgeschlagen: %s", fc.name, e)
                            return await respond(
                                text="Die Finanzrecherche ist gerade nicht verfügbar.",
                                action="finance_research_error",
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

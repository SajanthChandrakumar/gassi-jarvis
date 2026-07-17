"""
Gassi-Jarvis — Session & State Management

Manages in-memory conversation sessions with support for the
Human-in-the-Loop (HitL) pending command flow.

Each session stores:
    - history:              Conversation turn history (list of dicts).
    - pending_command:      A shell command awaiting user approval (or None).

Also wraps the ChromaDB vector store for persistent long-term memory (RAG).
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import chromadb

log = logging.getLogger(__name__)

# ─── ChromaDB Long-Term Memory (Persistent) ───────────────────────────────────

# Anchored to the project root (not the process CWD) so the same brain is
# loaded no matter where uvicorn is launched from. Override via JARVIS_BRAIN_DIR.
_DEFAULT_BRAIN_DIR = Path(__file__).resolve().parent.parent / "jarvis_brain"
BRAIN_DIR = os.environ.get("JARVIS_BRAIN_DIR", str(_DEFAULT_BRAIN_DIR))

chroma_client = chromadb.PersistentClient(path=BRAIN_DIR)
collection = chroma_client.get_or_create_collection(name="long_term_memory")


def save_memory(text: str) -> str:
    """Speichert einen neuen Fakt oder eine Beobachtung im Langzeitgedächtnis."""
    doc_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    collection.add(
        documents=[text],
        metadatas=[{"timestamp": datetime.now().isoformat()}],
        ids=[doc_id],
    )
    log.info("Memory gespeichert: %s", text)
    return "Erinnerung erfolgreich im Langzeitgedächtnis verankert."


def recall_memory(query: str, n_results: int = 5) -> str:
    """Sucht nach Erinnerungen und filtert irrelevante Treffer via Distanz-Schwelle."""
    log.info("Memory Suche: %s", query)

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )

    if not results["documents"] or not results["documents"][0]:
        return "Ich habe dazu absolut keine passenden Erinnerungen gefunden."

    formatted_memories: list[str] = []

    for i in range(len(results["documents"][0])):
        text = results["documents"][0][i]
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i]

        # Distanz-Filter: Alles über 1.2 ist semantisch zu weit entfernt
        if distance < 1.2:
            timestamp_short = meta.get("timestamp", "")[:10]
            formatted_memories.append(
                f"- [{timestamp_short}] {text} (Relevanz-Score: {round(distance, 2)})"
            )
        else:
            log.debug(
                "Memory-Filter: ignoriere irrelevante Erinnerung "
                "(Distanz %.2f): %s",
                distance, text,
            )

    if not formatted_memories:
        return (
            "Ich habe mein Gedächtnis durchsucht, aber keine "
            "wirklich relevanten Informationen dazu gefunden."
        )

    memory_block = "\n".join(formatted_memories)
    return f"Gefundene hochrelevante Erinnerungen:\n{memory_block}"


def get_memory_stats() -> str:
    """Gibt die Anzahl der gespeicherten Fragmente im Langzeitgedächtnis zurück."""
    count = collection.count()
    return f"Mein Langzeitgedächtnis umfasst aktuell {count} gespeicherte Wissensfragmente."


def get_recent_memories(n: int = 5) -> list[dict]:
    """
    Die n zuletzt gespeicherten Fakten, neueste zuerst.

    Reine lokale ChromaDB-Abfrage (kein Gemini-Call) — gedacht für externe
    Dashboards (z.B. Homepage Custom-API-Widget), die nur einen Blick auf
    zuletzt Gemerktes werfen wollen, ohne eine LLM-Anfrage auszulösen.
    """
    data = collection.get(include=["documents", "metadatas"])
    paired = sorted(
        zip(data["documents"], data["metadatas"]),
        key=lambda p: p[1].get("timestamp", ""),
        reverse=True,
    )
    return [
        {"text": doc, "timestamp": meta.get("timestamp", "")}
        for doc, meta in paired[:n]
    ]


# ─── Session State Management (disk-backed, HitL-aware) ───────────────────────
#
# Sessions persist to a JSON file so a server restart doesn't drop the
# conversation history — or, more importantly, a pending HitL command that is
# still awaiting the user's approval. Anchored next to the brain dir; override
# via JARVIS_SESSIONS_FILE.

_DEFAULT_SESSIONS_FILE = Path(BRAIN_DIR).parent / "jarvis_sessions.json"
SESSIONS_FILE = Path(os.environ.get("JARVIS_SESSIONS_FILE", str(_DEFAULT_SESSIONS_FILE)))


def _load_sessions() -> dict[str, dict[str, Any]]:
    """Load persisted sessions from disk; return empty on missing/corrupt file."""
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Sessions-Datei unlesbar (%s) — starte mit leerem State.", e)
    return {}


_active_sessions: dict[str, dict[str, Any]] = _load_sessions()


def _persist_sessions() -> None:
    """Write the session store to disk atomically (temp file + rename)."""
    try:
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SESSIONS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_active_sessions, f, ensure_ascii=False)
        os.replace(tmp, SESSIONS_FILE)
    except OSError as e:
        # Persistence is best-effort — never break a live request over it.
        log.warning("Sessions konnten nicht gespeichert werden: %s", e)


def get_session(session_id: str) -> dict[str, Any]:
    """
    Retrieve or create a session for the given ID.

    Returns a dict with:
        - history: list[dict]           — Conversation turns.
        - pending_command: str | None   — Shell command awaiting HitL approval.
        - pending_command_ts: float|None — Epoch seconds when it was queued.
    """
    if session_id not in _active_sessions:
        log.info("Neue Session erstellt: %s", session_id)
        _active_sessions[session_id] = {
            "history": [],
            "pending_command": None,
            "pending_command_ts": None,
            "pending_action_type": None,
        }

    return _active_sessions[session_id]


# Cap stored turns so the Gemini context can't grow without bound.
MAX_HISTORY_ENTRIES: int = 20

# A queued HitL command expires after this many seconds. Prevents a stale
# "yes" (or one meant for something else) from firing a command the user
# proposed long ago — especially now that pending state survives restarts.
PENDING_COMMAND_TTL_SECONDS: int = 300


def set_pending_command(session_id: str, command: str, action_type: str = "shell") -> None:
    """
    Queue an action for HitL approval, timestamped for expiry.

    Args:
        command: The payload — a shell command string, or a JSON-encoded
                 payload for non-shell actions (e.g. a calendar event).
        action_type: What to do on approval: 'shell' | 'calendar_create'.
    """
    session = get_session(session_id)
    session["pending_command"] = command
    session["pending_command_ts"] = time.time()
    session["pending_action_type"] = action_type
    _persist_sessions()


def get_pending_action_type(session_id: str) -> str:
    """Action type of the queued HitL payload ('shell' if unset, for
    backward compatibility with sessions persisted before this field)."""
    return get_session(session_id).get("pending_action_type") or "shell"


def get_pending_command(session_id: str) -> str | None:
    """
    Return the queued command awaiting approval, or None if there is none or
    it has expired. Expired commands are cleared as a side effect.
    """
    session = get_session(session_id)
    cmd = session.get("pending_command")
    if cmd is None:
        return None

    ts = session.get("pending_command_ts")
    if ts is None or (time.time() - ts) > PENDING_COMMAND_TTL_SECONDS:
        log.info("Pending-Befehl abgelaufen/ungültig, verworfen: %r", cmd)
        clear_pending_command(session_id)
        return None

    return cmd


def record_turn(
    session_id: str,
    user_text: str,
    model_text: str,
    tainted: bool = False,
) -> None:
    """
    Append a completed user/model exchange to the session history.

    Keeps only the most recent MAX_HISTORY_ENTRIES entries so long walks
    don't blow up the prompt size. Persists the session to disk — this also
    captures any pending_command set just before the reply was built.

    Args:
        tainted: True if the model's reply carries externally-sourced content
                 (screen capture, recalled memory) that could contain injected
                 instructions. Used to force HitL on a follow-up shell command.
    """
    session = get_session(session_id)
    session["history"].append({"role": "user", "text": user_text})
    session["history"].append({"role": "model", "text": model_text, "tainted": tainted})

    if len(session["history"]) > MAX_HISTORY_ENTRIES:
        session["history"] = session["history"][-MAX_HISTORY_ENTRIES:]

    _persist_sessions()


def last_reply_tainted(session_id: str) -> bool:
    """
    True if the most recent model turn carried externally-sourced content.

    Mitigation for indirect prompt injection: if the previous reply came from a
    screenshot or recalled memory, any shell command the model proposes on the
    next turn is treated as dangerous (forced through HitL), since the command
    may have been planted by injected text the model just read.
    """
    session = get_session(session_id)
    for turn in reversed(session["history"]):
        if turn.get("role") == "model":
            return bool(turn.get("tainted"))
    return False


def clear_pending_command(session_id: str) -> None:
    """
    Reset the pending command state for a session.

    Called after the user approves or denies a dangerous command,
    so the HitL interceptor no longer triggers on the next message.
    """
    session = get_session(session_id)
    session["pending_command"] = None
    session["pending_command_ts"] = None
    session["pending_action_type"] = None
    _persist_sessions()
    log.info("Pending-Command gelöscht für: %s", session_id)
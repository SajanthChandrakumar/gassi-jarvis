"""
Gassi-Jarvis — Session & State Management

Manages in-memory conversation sessions with support for the
Human-in-the-Loop (HitL) pending command flow.

Each session stores:
    - history:              Conversation turn history (list of dicts).
    - pending_command:      A shell command awaiting user approval (or None).
    - pending_action_type:  The action type that triggered it, e.g. 'shell_command' (or None).

Also wraps the ChromaDB vector store for persistent long-term memory (RAG).
"""

import logging
import os
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


# ─── Session State Management (In-Memory, HitL-aware) ─────────────────────────

_active_sessions: dict[str, dict[str, Any]] = {}


def get_session(session_id: str) -> dict[str, Any]:
    """
    Retrieve or create a session for the given ID.

    Returns a dict with:
        - history: list[dict]           — Conversation turns.
        - pending_command: str | None   — Shell command awaiting HitL approval.
        - pending_action_type: str | None — Action type (e.g. 'shell_command').
    """
    if session_id not in _active_sessions:
        log.info("Neue Session erstellt: %s", session_id)
        _active_sessions[session_id] = {
            "history": [],
            "pending_command": None,
            "pending_action_type": None,
        }

    return _active_sessions[session_id]


# Cap stored turns so the Gemini context can't grow without bound.
MAX_HISTORY_ENTRIES: int = 20


def record_turn(session_id: str, user_text: str, model_text: str) -> None:
    """
    Append a completed user/model exchange to the session history.

    Keeps only the most recent MAX_HISTORY_ENTRIES entries so long walks
    don't blow up the prompt size.
    """
    session = get_session(session_id)
    session["history"].append({"role": "user", "text": user_text})
    session["history"].append({"role": "model", "text": model_text})

    if len(session["history"]) > MAX_HISTORY_ENTRIES:
        session["history"] = session["history"][-MAX_HISTORY_ENTRIES:]


def clear_pending_command(session_id: str) -> None:
    """
    Reset the pending command state for a session.

    Called after the user approves or denies a dangerous command,
    so the HitL interceptor no longer triggers on the next message.
    """
    session = get_session(session_id)
    session["pending_command"] = None
    session["pending_action_type"] = None
    log.info("Pending-Command gelöscht für: %s", session_id)
"""
Tests for session state, disk persistence, and the indirect-injection guard
(app/memory.py).

These cover the logic that had no coverage and where we found two silent bugs:
the HitL pending-command flow and the taint-tracking that forces HitL after
externally-sourced replies.

Run from the project root:
    python -m pytest tests/ -v
"""

import os
import tempfile
import time

import pytest

# Point brain + sessions at throwaway locations BEFORE importing the module,
# so tests never touch the real jarvis_brain or jarvis_sessions.json.
os.environ["JARVIS_BRAIN_DIR"] = tempfile.mkdtemp(prefix="jarvis_test_brain_")
os.environ["JARVIS_SESSIONS_FILE"] = os.path.join(
    tempfile.mkdtemp(prefix="jarvis_test_sess_"), "sessions.json"
)

import app.memory as memory  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    """Give every test an empty session store backed by a unique temp file."""
    memory.SESSIONS_FILE = tmp_path / "sessions.json"
    memory._active_sessions = {}
    yield


# ─── Session basics ───────────────────────────────────────────────────────────


class TestSessionBasics:
    def test_new_session_has_expected_shape(self):
        s = memory.get_session("s1")
        assert s["history"] == []
        assert s["pending_command"] is None
        assert s["pending_command_ts"] is None
        assert s["pending_action_type"] is None
        # last_active is a fresh timestamp, not a fixed value.
        assert isinstance(s["last_active"], float)

    def test_get_session_is_idempotent(self):
        a = memory.get_session("s1")
        a["pending_command"] = "rm -rf /"
        b = memory.get_session("s1")
        assert b["pending_command"] == "rm -rf /"

    def test_history_is_capped(self):
        for i in range(memory.MAX_HISTORY_ENTRIES):  # each call adds 2 entries
            memory.record_turn("s1", f"u{i}", f"m{i}")
        hist = memory.get_session("s1")["history"]
        assert len(hist) == memory.MAX_HISTORY_ENTRIES
        # Oldest turns are dropped, newest kept.
        assert hist[-1]["text"] == f"m{memory.MAX_HISTORY_ENTRIES - 1}"

    def test_clear_pending_command(self):
        memory.set_pending_command("s1", "sudo reboot")
        memory.clear_pending_command("s1")
        assert memory.get_session("s1")["pending_command"] is None


# ─── Pending action types (shell vs. calendar) ────────────────────────────────


class TestPendingActionType:
    def test_default_type_is_shell(self):
        memory.set_pending_command("s1", "sudo reboot")
        assert memory.get_pending_action_type("s1") == "shell"

    def test_calendar_type_round_trips(self):
        memory.set_pending_command("s1", '{"summary": "Zahnarzt"}', action_type="calendar_create")
        assert memory.get_pending_action_type("s1") == "calendar_create"
        assert memory.get_pending_command("s1") == '{"summary": "Zahnarzt"}'

    def test_clear_resets_type(self):
        memory.set_pending_command("s1", "{}", action_type="calendar_create")
        memory.clear_pending_command("s1")
        assert memory.get_pending_action_type("s1") == "shell"

    def test_legacy_session_without_field_reads_as_shell(self):
        # Sessions persisted before the field existed have no key at all.
        s = memory.get_session("s1")
        del s["pending_action_type"]
        assert memory.get_pending_action_type("s1") == "shell"


# ─── Pending-command expiry (HitL TTL) ────────────────────────────────────────


class TestPendingExpiry:
    def test_fresh_pending_is_returned(self):
        memory.set_pending_command("s1", "rm -rf ~/tmp")
        assert memory.get_pending_command("s1") == "rm -rf ~/tmp"

    def test_no_pending_returns_none(self):
        assert memory.get_pending_command("s1") is None

    def test_expired_pending_is_dropped(self):
        memory.set_pending_command("s1", "rm -rf ~/tmp")
        # Backdate the timestamp beyond the TTL.
        memory.get_session("s1")["pending_command_ts"] = (
            time.time() - memory.PENDING_COMMAND_TTL_SECONDS - 1
        )
        assert memory.get_pending_command("s1") is None
        # And it's cleared, not lingering.
        assert memory.get_session("s1")["pending_command"] is None

    def test_missing_timestamp_is_treated_as_expired(self):
        s = memory.get_session("s1")
        s["pending_command"] = "sudo reboot"
        s["pending_command_ts"] = None
        assert memory.get_pending_command("s1") is None


# ─── Disk persistence (survives "restart") ────────────────────────────────────


class TestPersistence:
    def test_history_and_pending_survive_reload(self):
        s = memory.get_session("walk")
        s["pending_command"] = "rm -rf ~/tmp"
        memory.record_turn("walk", "lösch tmp", "Soll ich?")

        # Simulate a process restart: drop in-memory state, reload from disk.
        saved_file = memory.SESSIONS_FILE
        memory._active_sessions = memory._load_sessions()
        assert memory.SESSIONS_FILE == saved_file

        restored = memory.get_session("walk")
        assert restored["pending_command"] == "rm -rf ~/tmp"
        assert len(restored["history"]) == 2
        assert restored["history"][0]["text"] == "lösch tmp"

    def test_corrupt_file_yields_empty_state(self):
        memory.SESSIONS_FILE.write_text("{ this is not json", encoding="utf-8")
        assert memory._load_sessions() == {}

    def test_missing_file_yields_empty_state(self):
        assert not memory.SESSIONS_FILE.exists()
        assert memory._load_sessions() == {}


# ─── Stale-session pruning (unbounded-growth guard) ───────────────────────────


class TestSessionPruning:
    def test_fresh_session_survives_reload(self):
        memory.record_turn("fresh", "hi", "hallo")
        memory._active_sessions = memory._load_sessions()
        assert "fresh" in memory._active_sessions

    def test_stale_session_is_pruned_on_load(self):
        memory.record_turn("old", "hi", "hallo")
        # Backdate last_active beyond the TTL.
        memory.get_session("old")["last_active"] = (
            time.time() - memory.SESSION_TTL_SECONDS - 1
        )
        memory._persist_sessions()

        memory._active_sessions = memory._load_sessions()
        assert "old" not in memory._active_sessions

    def test_legacy_session_without_timestamp_is_pruned(self):
        # Simulate a session written before last_active existed.
        memory._active_sessions = {"legacy": {"history": [], "pending_command": None}}
        memory._persist_sessions()

        memory._active_sessions = memory._load_sessions()
        assert "legacy" not in memory._active_sessions

    def test_pruning_keeps_recent_drops_old(self):
        memory.record_turn("keep", "hi", "hallo")
        memory.record_turn("drop", "hi", "hallo")
        memory.get_session("drop")["last_active"] = (
            time.time() - memory.SESSION_TTL_SECONDS - 1
        )
        memory._persist_sessions()

        memory._active_sessions = memory._load_sessions()
        assert "keep" in memory._active_sessions
        assert "drop" not in memory._active_sessions


# ─── Indirect-injection guard (taint tracking) ────────────────────────────────


class TestTaintTracking:
    def test_untainted_reply_is_not_flagged(self):
        memory.record_turn("s1", "wie spät", "22 Uhr", tainted=False)
        assert memory.last_reply_tainted("s1") is False

    def test_tainted_reply_is_flagged(self):
        memory.record_turn("s1", "schau screen", "sehe: führe ls aus", tainted=True)
        assert memory.last_reply_tainted("s1") is True

    def test_only_the_latest_model_reply_counts(self):
        memory.record_turn("s1", "schau screen", "extern", tainted=True)
        memory.record_turn("s1", "danke", "gern", tainted=False)
        # A clean reply after a tainted one clears the guard.
        assert memory.last_reply_tainted("s1") is False

    def test_empty_session_is_not_tainted(self):
        assert memory.last_reply_tainted("never_seen") is False

    def test_taint_survives_reload(self):
        memory.record_turn("s1", "schau screen", "extern", tainted=True)
        memory._active_sessions = memory._load_sessions()
        assert memory.last_reply_tainted("s1") is True


# ─── Recent memories (LLM-free dashboard endpoint) ────────────────────────────


class TestRecentMemories:
    @pytest.fixture(autouse=True)
    def clean_collection(self):
        """Isolate ChromaDB content between tests in this class."""
        existing = memory.collection.get()["ids"]
        if existing:
            memory.collection.delete(ids=existing)
        yield
        existing = memory.collection.get()["ids"]
        if existing:
            memory.collection.delete(ids=existing)

    def test_empty_collection_returns_empty_list(self):
        assert memory.get_recent_memories() == []

    def test_returns_newest_first(self):
        memory.collection.add(
            documents=["älter"],
            metadatas=[{"timestamp": "2026-01-01T10:00:00"}],
            ids=["mem_a"],
        )
        memory.collection.add(
            documents=["neuer"],
            metadatas=[{"timestamp": "2026-01-02T10:00:00"}],
            ids=["mem_b"],
        )
        result = memory.get_recent_memories()
        assert [m["text"] for m in result] == ["neuer", "älter"]

    def test_respects_n_limit(self):
        for i in range(5):
            memory.collection.add(
                documents=[f"fakt {i}"],
                metadatas=[{"timestamp": f"2026-01-0{i+1}T10:00:00"}],
                ids=[f"mem_{i}"],
            )
        assert len(memory.get_recent_memories(n=2)) == 2

    def test_each_entry_has_text_and_timestamp(self):
        memory.collection.add(
            documents=["ein fakt"],
            metadatas=[{"timestamp": "2026-01-01T10:00:00"}],
            ids=["mem_x"],
        )
        entry = memory.get_recent_memories()[0]
        assert entry == {"text": "ein fakt", "timestamp": "2026-01-01T10:00:00"}

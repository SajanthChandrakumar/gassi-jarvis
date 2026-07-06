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
        assert s == {
            "history": [],
            "pending_command": None,
            "pending_command_ts": None,
        }

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

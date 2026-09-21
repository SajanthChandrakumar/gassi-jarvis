"""
Tests for the task inbox (app/inbox.py).

Pure file-backed logic — capture appends a Markdown checkbox, open-task
parsing ignores completed (`- [x]`) lines, and the spoken summary reads back
what's open.

Run from the project root:
    python -m pytest tests/ -v
"""

import importlib

import pytest

import app.inbox as inbox


@pytest.fixture(autouse=True)
def temp_inbox(tmp_path, monkeypatch):
    """Point the inbox at a throwaway file per test."""
    monkeypatch.setattr(inbox, "INBOX_FILE", tmp_path / "inbox.md")
    yield


class TestAddTask:
    def test_capture_writes_open_checkbox(self):
        inbox.add_task("Auth-Bug fixen")
        content = inbox.INBOX_FILE.read_text(encoding="utf-8")
        assert "- [ ] Auth-Bug fixen" in content
        assert "_(erfasst" in content

    def test_capture_confirms_with_task_text(self):
        assert "Auth-Bug" in inbox.add_task("Auth-Bug fixen")

    def test_blank_task_is_rejected(self):
        inbox.add_task("   ")
        assert not inbox.INBOX_FILE.exists()

    def test_multiple_tasks_append(self):
        inbox.add_task("erste")
        inbox.add_task("zweite")
        assert inbox.INBOX_FILE.read_text(encoding="utf-8").count("- [ ]") == 2

    def test_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "sub" / "dir" / "inbox.md"
        inbox.INBOX_FILE = nested
        inbox.add_task("test")
        assert nested.exists()


class TestOpenTasks:
    def test_empty_when_no_file(self):
        assert inbox.get_open_tasks() == []

    def test_returns_clean_task_text_without_stamp(self):
        inbox.add_task("Milch kaufen")
        assert inbox.get_open_tasks() == ["Milch kaufen"]

    def test_completed_tasks_are_excluded(self):
        inbox.add_task("offen")
        inbox.INBOX_FILE.write_text(
            "- [x] erledigt  _(erfasst 2026-07-10 09:00)_\n"
            "- [ ] offen  _(erfasst 2026-07-11 10:00)_\n",
            encoding="utf-8",
        )
        assert inbox.get_open_tasks() == ["offen"]

    def test_ignores_non_task_lines(self):
        inbox.INBOX_FILE.write_text(
            "# Meine Inbox\n\n- [ ] echte Aufgabe\nirgendein Text\n",
            encoding="utf-8",
        )
        assert inbox.get_open_tasks() == ["echte Aufgabe"]


class TestListTasks:
    def test_empty_list_message(self):
        assert "leer" in inbox.list_tasks().lower()

    def test_singular_phrasing(self):
        inbox.add_task("einzige")
        out = inbox.list_tasks()
        assert "eine offene Aufgabe" in out
        assert "- einzige" in out

    def test_plural_phrasing(self):
        inbox.add_task("a")
        inbox.add_task("b")
        assert "2 offene Aufgaben" in inbox.list_tasks()


def test_env_var_overrides_path(monkeypatch, tmp_path):
    """JARVIS_INBOX_FILE should redirect where tasks are stored."""
    target = tmp_path / "obsidian" / "tasks.md"
    monkeypatch.setenv("JARVIS_INBOX_FILE", str(target))
    reloaded = importlib.reload(inbox)
    assert reloaded.INBOX_FILE == target
    # Reload again with the env cleared so we don't leak module state.
    monkeypatch.delenv("JARVIS_INBOX_FILE")
    importlib.reload(inbox)

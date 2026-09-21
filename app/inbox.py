"""
Gassi-Jarvis — Task-Inbox (Voice Capture)

A dead-simple capture inbox: the user dictates a task on the go ("Jarvis,
notier: Auth-Bug fixen") and it lands as a Markdown checkbox in a plain text
file. No external service, no auth — just a portable Markdown file you can also
edit by hand or point at an Obsidian vault via JARVIS_INBOX_FILE.

File format (one task per line):
    - [ ] Auth-Bug fixen  _(erfasst 2026-07-11 22:15)_
    - [x] Milch kaufen  _(erfasst 2026-07-10 09:02)_

Open tasks are the unchecked (`- [ ]`) lines; tick a box to `- [x]` in any
editor to mark it done.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_INBOX = Path(__file__).resolve().parent.parent / "jarvis_inbox.md"
INBOX_FILE = Path(os.environ.get("JARVIS_INBOX_FILE", str(_DEFAULT_INBOX)))

# Matches an open task line and captures the task text (without the checkbox
# prefix and the trailing "_(erfasst ...)_" stamp).
_OPEN_TASK = re.compile(r"^-\s*\[\s*\]\s*(.*?)(?:\s*_\(erfasst\s.*\)_)?\s*$")


def add_task(task: str) -> str:
    """
    Append a task to the inbox. Returns a spoken-friendly confirmation.

    Best-effort: a filesystem error is reported to the user rather than raised,
    so a capture failure never 500s the chat turn.
    """
    task = (task or "").strip()
    if not task:
        return "Ich habe leider keinen Text für die Notiz verstanden."

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- [ ] {task}  _(erfasst {stamp})_\n"
    try:
        INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(INBOX_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        log.error("Task konnte nicht gespeichert werden: %s", e)
        return "Ich konnte die Notiz gerade nicht speichern."

    log.info("Task erfasst: %s", task)
    return f"Notiert: {task}"


def get_open_tasks() -> list[str]:
    """Return the text of all open (unchecked) tasks, oldest first."""
    if not INBOX_FILE.exists():
        return []
    tasks: list[str] = []
    for raw in INBOX_FILE.read_text(encoding="utf-8").splitlines():
        m = _OPEN_TASK.match(raw.strip())
        if m and m.group(1).strip():
            tasks.append(m.group(1).strip())
    return tasks


def list_tasks() -> str:
    """Spoken-friendly summary of open tasks for the voice UI."""
    tasks = get_open_tasks()
    if not tasks:
        return "Deine Aufgabenliste ist leer."
    body = "\n".join(f"- {t}" for t in tasks)
    count = "eine offene Aufgabe" if len(tasks) == 1 else f"{len(tasks)} offene Aufgaben"
    return f"Du hast {count}:\n{body}"

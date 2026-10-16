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

_TASK_PREFIX = r"(?:jarvis\b[,\s]*)?(?:(?:bitte|please)\s+)?"
_TASK_LIST_REQUEST = re.compile(
    _TASK_PREFIX + r"(?:"
    r"(?:list|show)(?:\s+me)?\s+(?:my\s+)?(?:open\s+)?(?:tasks|to-?dos)"
    r"|zeig(?:e)?(?:\s+mir)?\s+(?:meine|die)\s+(?:offenen\s+)?(?:aufgaben|to-?dos|aufgabenliste)"
    r"|welche\s+(?:offenen\s+)?(?:aufgaben|to-?dos)\s+habe\s+ich"
    r")\s*[.!?]*",
    re.IGNORECASE,
)
_TASK_CAPTURE_REQUESTS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    _TASK_PREFIX + r"(?:merke|notier(?:e)?)(?:\s+mir)?\s+(?:(?:als|eine)\s+)?"
    r"(?:aufgabe|to-?do)\s*(?::\s*(?P<task>.*))?[.!?]*",
    _TASK_PREFIX + r"add\s+(?:a\s+)?(?:task|to-?do)\s*(?::\s*(?P<task>.*))?[.!?]*",
    _TASK_PREFIX + r"füge(?:\s+(?P<task>.*?))?\s+zu\s+meiner\s+aufgabenliste\s+hinzu[.!?]*",
    r"(?P<short>jarvis\b[,\s]*(?:bitte\s+)?notier(?:e)?\s*:\s*)(?P<task>.*)",
))
_AMBIGUOUS_SHORT_NOTE = re.compile(
    r"^(?:ich|i|my|mein(?:e|en|er|em|es)?|erinnere|remember|"
    r"morgen|heute|übermorgen|am|tomorrow|today|on)\b"
    r"|^(?:termin|meeting|kalendereintrag)\b"
    r"(?!\s+(?:vereinbaren|planen|absagen|vorbereiten|organisieren|schedule|prepare|cancel)\b)",
    re.IGNORECASE,
)
_UNCERTAIN_TASK_END = re.compile(
    r"\b(?:oder\s+(?:vielleicht\s+)?lieber\s+nicht|or\s+(?:maybe\s+)?not|"
    r"(?:aber|doch)(?:\s+bitte)?\s+nicht\s+(?:speichern|notieren)|"
    r"but\s+don['’]t\s+(?:save|store)(?:\s+it)?)\s*[.!?]*$",
    re.IGNORECASE,
)


def parse_task_request(user_text: str) -> tuple[str, str] | None:
    """Recognize bounded inbox commands, leaving other requests to normal chat."""
    text = " ".join((user_text or "").split())
    if _TASK_LIST_REQUEST.fullmatch(text):
        return "list_tasks", ""
    for pattern in _TASK_CAPTURE_REQUESTS:
        if match := pattern.fullmatch(text):
            task = (match.group("task") or "").strip()
            if _UNCERTAIN_TASK_END.search(task):
                return None
            if match.groupdict().get("short") and _AMBIGUOUS_SHORT_NOTE.search(task):
                return None
            return "capture_task", task
    return None


def add_task(task: str) -> str:
    """Append a task and return its spoken-friendly result."""
    return capture_task(task)[1]


def capture_task(task: str) -> tuple[str, str]:
    """
    Append one record and return its action and spoken-friendly result.

    Best-effort: a filesystem error is reported to the user rather than raised,
    so a capture failure never 500s the chat turn.
    """
    task = " ".join((task or "").split())
    if not task:
        return "task_incomplete", "Welche Aufgabe soll ich notieren? Mir fehlt noch der Aufgabentext."

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- [ ] {task}  _(erfasst {stamp})_\n"
    try:
        INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(INBOX_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        log.error("Task konnte nicht gespeichert werden: %s", e)
        return "task_capture_failed", "Ich konnte die Notiz gerade nicht speichern."

    log.info("Task erfasst: %s", task)
    return "task_captured", f"Notiert: {task}"


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

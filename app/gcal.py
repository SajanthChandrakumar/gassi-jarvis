"""
Gassi-Jarvis — Google Calendar Integration

Reads events and creates new ones via the Google Calendar API (primary
calendar). Event creation is HitL-gated in main.py — the model can only
*propose* an event; it is inserted after the user confirms.

One-time setup (see README):
    1. Google Cloud Console → APIs aktivieren: "Google Calendar API".
    2. OAuth-Client-ID vom Typ "Desktop-App" anlegen, JSON herunterladen
       und als gcal_credentials.json ins Projektverzeichnis legen.
    3. Einmalig ausführen:  python -m app.gcal
       → Browser-Login, das Token landet in gcal_token.json.

Both files are gitignored; paths are overridable via JARVIS_GCAL_CREDENTIALS
and JARVIS_GCAL_TOKEN.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

# calendar.events covers reading and writing events, but not calendar
# management (sharing, deletion of whole calendars) — least privilege.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = Path(
    os.environ.get("JARVIS_GCAL_CREDENTIALS", str(_PROJECT_ROOT / "gcal_credentials.json"))
)
TOKEN_FILE = Path(
    os.environ.get("JARVIS_GCAL_TOKEN", str(_PROJECT_ROOT / "gcal_token.json"))
)

DEFAULT_EVENT_MINUTES = 60
MAX_LOOKAHEAD_DAYS = 14

_WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


class CalendarNotConfigured(Exception):
    """Raised when the OAuth token is missing — carries a spoken-friendly hint."""

    def __init__(self) -> None:
        super().__init__(
            "Mein Kalender-Zugang ist noch nicht eingerichtet. "
            "Führe dafür einmalig 'python -m app.gcal' auf dem Mac aus."
        )


# ─── Auth ─────────────────────────────────────────────────────────────────────


def _load_credentials() -> Credentials:
    """Load stored user credentials, refreshing them if expired."""
    if not TOKEN_FILE.exists():
        raise CalendarNotConfigured()

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    if not creds.valid:
        raise CalendarNotConfigured()
    return creds


def authorize() -> None:
    """Interactive one-time OAuth flow (opens a browser). Run: python -m app.gcal"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS_FILE.exists():
        raise SystemExit(
            f"OAuth-Client-Datei fehlt: {CREDENTIALS_FILE}\n"
            "→ Google Cloud Console → Anmeldedaten → OAuth-Client-ID (Desktop-App) "
            "→ JSON herunterladen und dort ablegen."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"OK — Token gespeichert in {TOKEN_FILE}. Jarvis hat jetzt Kalender-Zugriff.")


def _service():
    """Build a Calendar API service client with stored credentials."""
    return build("calendar", "v3", credentials=_load_credentials(), cache_discovery=False)


# ─── Date helpers (pure — unit-tested) ────────────────────────────────────────


def parse_day(date_str: str) -> datetime:
    """
    Parse a YYYY-MM-DD string into local midnight of that day.
    Empty/invalid input falls back to today — for a voice assistant a
    best-effort answer beats a hard error.
    """
    date_str = (date_str or "").strip()
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        day = datetime.now()
    return day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone()


def _parse_dt(value: str) -> datetime:
    """Parse an ISO datetime; naive values get the local timezone attached."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def format_dt_de(dt: datetime) -> str:
    """'Freitag, 10. Juli, 15:00 Uhr' — locale-independent German."""
    return (
        f"{_WEEKDAYS_DE[dt.weekday()]}, {dt.day}. {_MONTHS_DE[dt.month - 1]}, "
        f"{dt.strftime('%H:%M')} Uhr"
    )


def describe_event(event: dict) -> str:
    """Human-readable German one-liner for a proposed event (HitL prompt)."""
    try:
        start = _parse_dt(event["start"])
        end = _parse_dt(event["end"]) if event.get("end") else start + timedelta(
            minutes=DEFAULT_EVENT_MINUTES
        )
        return (
            f"'{event.get('summary', 'Termin')}' am {format_dt_de(start)} "
            f"bis {end.strftime('%H:%M')} Uhr"
        )
    except (KeyError, ValueError, TypeError):
        return json.dumps(event, ensure_ascii=False)


# ─── Tools ────────────────────────────────────────────────────────────────────


def list_events(date: str = "", days: int = 1) -> str:
    """
    List events on the primary calendar, starting at `date` (YYYY-MM-DD,
    default today) for `days` days. Returns a spoken-friendly German summary.
    """
    days = max(1, min(int(days or 1), MAX_LOOKAHEAD_DAYS))
    start = parse_day(date)
    end = start + timedelta(days=days)

    result = (
        _service()
        .events()
        .list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )
    items = result.get("items", [])

    span = "heute" if days == 1 and start.date() == datetime.now().date() else (
        f"am {_WEEKDAYS_DE[start.weekday()]}, {start.day}. {_MONTHS_DE[start.month - 1]}"
        + (f" und die {days - 1} Tage danach" if days > 1 else "")
    )
    if not items:
        return f"Du hast {span} keine Termine im Kalender."

    lines: list[str] = []
    for ev in items:
        summary = ev.get("summary", "(ohne Titel)")
        location = f", in {ev['location']}" if ev.get("location") else ""
        if "dateTime" in ev.get("start", {}):
            dt = _parse_dt(ev["start"]["dateTime"]).astimezone()
            lines.append(f"- {format_dt_de(dt)}: {summary}{location}")
        else:
            # All-day event: start.date is YYYY-MM-DD.
            day = parse_day(ev.get("start", {}).get("date", ""))
            lines.append(
                f"- {_WEEKDAYS_DE[day.weekday()]}, {day.day}. "
                f"{_MONTHS_DE[day.month - 1]} (ganztägig): {summary}{location}"
            )

    return f"Deine Termine {span}:\n" + "\n".join(lines)


def create_event(event_json: str) -> str:
    """
    Insert a previously HitL-approved event into the primary calendar.

    Args:
        event_json: JSON dict with 'summary', ISO 'start', optional ISO 'end'
                    and optional 'description' — exactly what was queued as
                    the pending HitL action.
    """
    event = json.loads(event_json)
    start = _parse_dt(event["start"])
    end = (
        _parse_dt(event["end"])
        if event.get("end")
        else start + timedelta(minutes=DEFAULT_EVENT_MINUTES)
    )

    body = {
        "summary": event.get("summary", "Termin"),
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if event.get("description"):
        body["description"] = event["description"]

    created = _service().events().insert(calendarId="primary", body=body).execute()
    log.info("Kalender-Event angelegt: %s", created.get("id"))
    return f"Erledigt. {describe_event(event)} steht im Kalender."


if __name__ == "__main__":
    authorize()

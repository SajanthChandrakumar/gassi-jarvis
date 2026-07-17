"""
Tests for the pure date/format helpers in app/gcal.py.

Network-facing functions (list_events, create_event) talk to the Google API
and are not covered here; these tests pin down the parsing and German
formatting the HitL flow depends on.

Run from the project root:
    python -m pytest tests/ -v
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_gcal_brain_"))
os.environ.setdefault(
    "JARVIS_SESSIONS_FILE",
    os.path.join(tempfile.mkdtemp(prefix="jarvis_gcal_sess_"), "sessions.json"),
)

from app import gcal  # noqa: E402


class TestParseDay:
    def test_valid_date_parses_to_local_midnight(self):
        day = gcal.parse_day("2026-07-10")
        assert (day.year, day.month, day.day) == (2026, 7, 10)
        assert (day.hour, day.minute) == (0, 0)
        assert day.tzinfo is not None

    def test_empty_falls_back_to_today(self):
        assert gcal.parse_day("").date() == datetime.now().date()

    def test_garbage_falls_back_to_today(self):
        assert gcal.parse_day("morgen um drei").date() == datetime.now().date()

    def test_fallback_is_also_timezone_aware(self):
        # Even the today-fallback must be tz-aware, else timeMin/timeMax in
        # list_events would mix naive/aware datetimes and the Google API rejects it.
        assert gcal.parse_day("kaputt").tzinfo is not None


class TestParseDt:
    def test_naive_iso_gets_local_timezone(self):
        # Google all-day/naive values must not stay naive — they'd break
        # comparisons and .isoformat() sent to the API.
        dt = gcal._parse_dt("2026-07-10T15:00:00")
        assert dt.tzinfo is not None

    def test_aware_iso_preserves_offset(self):
        dt = gcal._parse_dt("2026-07-10T15:00:00+02:00")
        assert dt.utcoffset() == timedelta(hours=2)

    def test_aware_utc_is_preserved(self):
        dt = gcal._parse_dt("2026-07-10T13:00:00+00:00")
        assert dt.utcoffset() == timedelta(0)
        # Same instant as 15:00 in +02:00.
        assert dt == datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc)


class TestGermanFormatting:
    def test_format_dt_de(self):
        # 2026-07-10 is a Friday.
        out = gcal.format_dt_de(datetime(2026, 7, 10, 15, 0).astimezone())
        assert out == "Freitag, 10. Juli, 15:00 Uhr"

    def test_describe_event_with_end(self):
        out = gcal.describe_event(
            {"summary": "Zahnarzt", "start": "2026-07-10T15:00:00", "end": "2026-07-10T16:30:00"}
        )
        assert "'Zahnarzt'" in out
        assert "Freitag, 10. Juli, 15:00 Uhr" in out
        assert "16:30" in out

    def test_describe_event_defaults_to_one_hour(self):
        out = gcal.describe_event({"summary": "Call", "start": "2026-07-10T15:00:00"})
        assert "16:00" in out

    def test_describe_event_survives_malformed_payload(self):
        # Falls back to raw JSON instead of raising — HitL prompt must never 500.
        out = gcal.describe_event({"summary": "kaputt", "start": "not-a-date"})
        assert "kaputt" in out

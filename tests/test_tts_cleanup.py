"""
Tests for the TTS text cleaner (app/main._clean_for_tts).

Ensures URLs and Markdown artifacts are stripped so Edge-TTS doesn't spell out
"h-t-t-p-s-colon-slash-slash..." when reading grounded web answers aloud.

Run from the project root:
    python -m pytest tests/ -v
"""

import os
import tempfile

# Isolate brain/sessions before importing app.main (it initialises ChromaDB and
# loads the session store at import time).
os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_tts_brain_"))
os.environ.setdefault(
    "JARVIS_SESSIONS_FILE",
    os.path.join(tempfile.mkdtemp(prefix="jarvis_tts_sess_"), "sessions.json"),
)

from app.main import _clean_for_tts  # noqa: E402


class TestCleanForTTS:
    def test_bare_url_becomes_placeholder(self):
        out = _clean_for_tts("Mehr dazu unter https://example.com/news heute.")
        assert "https" not in out
        assert "(Link)" in out

    def test_www_url_is_stripped(self):
        out = _clean_for_tts("Siehe www.tagesschau.de für Details.")
        assert "www." not in out
        assert "(Link)" in out

    def test_markdown_link_keeps_text_drops_url(self):
        out = _clean_for_tts("Quelle: [Tagesschau](https://tagesschau.de) berichtet.")
        assert "Tagesschau" in out
        assert "https" not in out
        assert "(" not in out.replace("(Link)", "")  # no leftover paren clutter

    def test_markdown_artifacts_removed(self):
        out = _clean_for_tts("**Wichtig** und # Titel und - Punkt")
        assert "*" not in out
        assert "#" not in out

    def test_plain_text_unchanged(self):
        assert _clean_for_tts("Es ist 22 Uhr in Zürich.") == "Es ist 22 Uhr in Zürich."

    def test_whitespace_collapsed(self):
        out = _clean_for_tts("Zwei    Leerzeichen.")
        assert "  " not in out

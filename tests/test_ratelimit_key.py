"""
Tests for the rate-limit client key (app/main._client_key).

Behind a tunnel the TCP peer is always 127.0.0.1, so the key must fall back to
the originating client in X-Forwarded-For — otherwise every client shares one
rate bucket.

Run from the project root:
    python -m pytest tests/ -v
"""

import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("JARVIS_BRAIN_DIR", tempfile.mkdtemp(prefix="jarvis_rl_brain_"))
os.environ.setdefault(
    "JARVIS_SESSIONS_FILE",
    os.path.join(tempfile.mkdtemp(prefix="jarvis_rl_sess_"), "sessions.json"),
)

from app.main import _client_key  # noqa: E402


def _fake_request(headers: dict, peer: str = "127.0.0.1"):
    """Minimal stand-in exposing the bits _client_key / get_remote_address read."""
    return SimpleNamespace(
        headers={k.lower(): v for k, v in headers.items()} | headers,
        client=SimpleNamespace(host=peer),
    )


class TestClientKey:
    def test_uses_forwarded_client_over_tunnel_peer(self):
        req = _fake_request({"X-Forwarded-For": "203.0.113.7"}, peer="127.0.0.1")
        assert _client_key(req) == "203.0.113.7"

    def test_takes_leftmost_of_forwarded_chain(self):
        req = _fake_request({"X-Forwarded-For": "203.0.113.7, 10.0.0.1, 127.0.0.1"})
        assert _client_key(req) == "203.0.113.7"

    def test_strips_whitespace(self):
        req = _fake_request({"X-Forwarded-For": "  203.0.113.7  "})
        assert _client_key(req) == "203.0.113.7"

    def test_falls_back_to_peer_without_header(self):
        req = _fake_request({}, peer="192.0.2.55")
        assert _client_key(req) == "192.0.2.55"

    def test_two_clients_get_distinct_keys(self):
        a = _fake_request({"X-Forwarded-For": "203.0.113.7"})
        b = _fake_request({"X-Forwarded-For": "203.0.113.8"})
        assert _client_key(a) != _client_key(b)

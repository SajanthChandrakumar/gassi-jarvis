"""Runtime API-origin configuration contracts for the PWA."""

import pytest
from fastapi.testclient import TestClient


def test_config_js_defaults_to_same_origin_and_is_not_cached(monkeypatch):
    import app.main as main_module

    monkeypatch.delenv("JARVIS_FRONTEND_API_BASE_URL", raising=False)
    response = TestClient(main_module.app).get("/config.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "window.JARVIS_CONFIG" in response.text
    assert "apiBaseUrl: \"\"" in response.text


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("https://jarvis.example.test/", "https://jarvis.example.test"),
        ("https://jarvis.example.test/api///", "https://jarvis.example.test/api"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("//jarvis.example.test", ""),
        ("ftp://jarvis.example.test", ""),
        ("https://user:pass@jarvis.example.test", ""),
        ("https://jarvis.example.test?token=secret", ""),
        ("https://jarvis.example.test/#fragment", ""),
    ],
)
def test_config_js_validates_and_normalizes_api_origin(monkeypatch, configured, expected):
    import app.main as main_module

    monkeypatch.setenv("JARVIS_FRONTEND_API_BASE_URL", configured)
    response = TestClient(main_module.app).get("/config.js")

    assert response.status_code == 200
    assert f'apiBaseUrl: "{expected}"' in response.text


def test_invalid_config_is_logged_without_echoing_the_configured_value(monkeypatch, caplog):
    import app.main as main_module

    configured = "https://user:secret@jarvis.example.test?token=secret"
    monkeypatch.setenv("JARVIS_FRONTEND_API_BASE_URL", configured)
    response = TestClient(main_module.app).get("/config.js")

    assert 'apiBaseUrl: ""' in response.text
    assert "Invalid JARVIS_FRONTEND_API_BASE_URL" in caplog.text
    assert configured not in caplog.text

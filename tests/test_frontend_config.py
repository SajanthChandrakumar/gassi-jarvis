"""Runtime API-origin configuration contracts for the PWA."""

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


def test_config_js_exposes_configured_cloud_api_origin(monkeypatch):
    import app.main as main_module

    monkeypatch.setenv("JARVIS_FRONTEND_API_BASE_URL", "https://jarvis.example.test/")
    response = TestClient(main_module.app).get("/config.js")

    assert response.status_code == 200
    assert 'apiBaseUrl: "https://jarvis.example.test/"' in response.text

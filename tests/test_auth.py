"""Auth dual en /connect: MCP_API_KEY estático debe pasar aunque OAuth esté ON.

Reproduce el 401 invalid_token que reportó la primera app consumidora: con
AuthKit configurado, FastMCP era el único guardián de /connect y rechazaba la
key estática — el uso servidor-a-servidor quedaba imposible.
"""

from __future__ import annotations

import importlib

import pytest

KEY = "llave-de-prueba-123"


@pytest.fixture
def app_oauth(monkeypatch):
    """App con OAuth ON + MCP_API_KEY, reconstruida desde cero."""
    monkeypatch.setenv("MCP_API_KEY", KEY)
    monkeypatch.setenv("AUTHKIT_DOMAIN", "https://fake.authkit.app")
    monkeypatch.setenv("BASE_URL", "http://testserver")
    monkeypatch.setenv("FETCH_ON_STARTUP", "false")

    import repse.config
    import repse.server
    import repse.web

    importlib.reload(repse.config)
    importlib.reload(repse.server)
    importlib.reload(repse.web)
    yield repse.web.create_app()
    # restaurar módulos con el entorno real para no contaminar otros tests
    monkeypatch.delenv("MCP_API_KEY")
    monkeypatch.delenv("AUTHKIT_DOMAIN")
    monkeypatch.delenv("BASE_URL")
    importlib.reload(repse.config)
    importlib.reload(repse.server)
    importlib.reload(repse.web)


def _initialize(client, headers):
    return client.post(
        "/connect",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream", **headers},
    )


def test_bearer_estatico_pasa_con_oauth_on(app_oauth):
    from starlette.testclient import TestClient

    with TestClient(app_oauth) as client:
        r = _initialize(client, {"Authorization": f"Bearer {KEY}"})
        assert r.status_code == 200, r.text


def test_token_basura_sigue_rechazado(app_oauth):
    from starlette.testclient import TestClient

    with TestClient(app_oauth) as client:
        assert _initialize(client, {"Authorization": "Bearer nope"}).status_code == 401
        assert _initialize(client, {}).status_code == 401

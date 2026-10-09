"""Ruta REST /verificar: la misma consulta que la tool, sin hablar MCP.

Nace de MATERIA (WE-514): un backend que sólo quiere saber si un RFC tiene REPSE
vigente no debería montar un handshake de sesión MCP para preguntarlo.

Lo que se fija aquí: que siga cerrada con bearer, que devuelva textualmente lo
que devuelve `consultar` (si las dos se desincronizan, la tool y el backend
opinan distinto del mismo proveedor), y que un portal caído se distinga de un
proveedor sin registro — 502, no un `encontrado: false` que se leería como
"no tiene REPSE".
"""

from __future__ import annotations

import importlib

import pytest
from starlette.testclient import TestClient

KEY = "llave-rest-123"

RESPUESTA = {
    "consulta": "ASE100712TT2",
    "encontrado": True,
    "estado": "VIGENTE",
    "vigente": True,
    "veredicto": "Registro vigente.",
}


def _app(monkeypatch, *, oauth: bool):
    monkeypatch.setenv("MCP_API_KEY", KEY)
    monkeypatch.setenv("FETCH_ON_STARTUP", "false")
    if oauth:
        monkeypatch.setenv("AUTHKIT_DOMAIN", "https://fake.authkit.app")
        monkeypatch.setenv("BASE_URL", "http://testserver")
    else:
        monkeypatch.delenv("AUTHKIT_DOMAIN", raising=False)

    import repse.config
    import repse.server
    import repse.web

    importlib.reload(repse.config)
    importlib.reload(repse.server)
    importlib.reload(repse.web)
    yield repse.web.create_app()

    monkeypatch.delenv("MCP_API_KEY")
    monkeypatch.delenv("AUTHKIT_DOMAIN", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    importlib.reload(repse.config)
    importlib.reload(repse.server)
    importlib.reload(repse.web)


@pytest.fixture
def app(monkeypatch):
    yield from _app(monkeypatch, oauth=False)


@pytest.fixture
def app_oauth(monkeypatch):
    """Con OAuth ENCENDIDO, que es como corre en producción.

    Importa la distinción: `/verificar` es un `Route` explícito, no cae en el
    `Mount` de FastMCP, así que si el middleware no lo exige el bearer, nadie más
    lo hace. Y `_needs_static_bearer` devuelve `not oauth_enabled` por defecto —
    o sea que con OAuth ON la ruta quedaría ABIERTA salvo por su línea explícita.
    Probar esto con OAuth apagado pasa por la razón equivocada (lo comprobamos
    saboteando la línea: la suite seguía verde).
    """
    yield from _app(monkeypatch, oauth=True)


def _auth() -> dict:
    return {"Authorization": f"Bearer {KEY}"}


def _get(client, params="?rfc=ASE100712TT2", headers=None):
    return client.get(f"/verificar{params}", headers=headers or {})


def test_sin_bearer_no_pasa(app_oauth):
    with TestClient(app_oauth) as client:
        assert _get(client).status_code == 401
        assert _get(client, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_devuelve_lo_mismo_que_consultar(app, monkeypatch):
    import repse.consulta

    monkeypatch.setattr(repse.consulta, "consultar", lambda termino: {**RESPUESTA, "eco": termino})
    with TestClient(app) as client:
        r = _get(client, headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 200, r.text
    assert r.json() == {**RESPUESTA, "eco": "ASE100712TT2"}


def test_sin_rfc_es_400(app):
    with TestClient(app) as client:
        r = _get(client, params="", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 400


def test_portal_caido_es_502_no_un_falso_sin_registro(app, monkeypatch):
    """La distinción que importa: "no pude verificar" no es "no tiene REPSE".
    Si esto devolviera 200 con `vigente: false`, MATERIA guardaría un hallazgo
    falso en el expediente de defensa de un cliente."""
    import repse.consulta
    from repse.client import RepseError

    def _revienta(termino):
        raise RepseError("Búsqueda en REPSE falló: timeout")

    monkeypatch.setattr(repse.consulta, "consultar", _revienta)
    with TestClient(app) as client:
        r = _get(client, headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 502
    assert "REPSE" in r.json()["error"]


# --- Lote ---


def _lote(client, rfcs, headers=None):
    return client.post("/verificar-lote", json={"rfcs": rfcs}, headers=headers or _auth())


def test_el_lote_devuelve_TODOS_no_solo_los_no_vigentes(app, monkeypatch):
    """Al revés que la tool `verificar_lote` del MCP, que devuelve sólo los que
    requieren acción. Aquí "lo verifiqué el día D y estaba vigente" ES la evidencia
    de diligencia: omitir los vigentes es omitir la mitad de la prueba."""
    import repse.consulta

    monkeypatch.setattr(
        repse.consulta,
        "consultar",
        lambda t: {"consulta": t, "vigente": not t.startswith("SIN"), "estado": "VIGENTE"},
    )
    with TestClient(app) as client:
        r = _lote(client, ["ASE100712TT2", "SIN010101AAA", "OTR020202BBB"])
    assert r.status_code == 200, r.text
    res = r.json()["resultados"]
    assert set(res) == {"ASE100712TT2", "SIN010101AAA", "OTR020202BBB"}
    assert res["ASE100712TT2"]["vigente"] is True, "el vigente tiene que venir"
    assert res["SIN010101AAA"]["vigente"] is False


def test_un_termino_que_truena_no_tumba_el_lote(app, monkeypatch):
    """El portal de la STPS falla seguido. Si un término revienta, los otros 99 no
    se pierden — y el que falló se marca `fuente_caida`, que NO es "no tiene REPSE".
    Esa distinción es la misma que defiende la ruta individual con su 502."""
    import repse.consulta
    from repse.client import RepseError

    def _a_veces(t):
        if t == "MAL010101AAA":
            raise RepseError("Búsqueda en REPSE falló: timeout")
        return {"consulta": t, "vigente": True, "estado": "VIGENTE"}

    monkeypatch.setattr(repse.consulta, "consultar", _a_veces)
    with TestClient(app) as client:
        b = _lote(client, ["BIEN010101AAA", "MAL010101AAA", "BIEN020202BBB"]).json()
    assert b["fuente_caida"] == 1
    assert b["resultados"]["MAL010101AAA"]["fuente_caida"] is True
    assert "vigente" not in b["resultados"]["MAL010101AAA"], "no puede parecer un veredicto"
    assert b["resultados"]["BIEN010101AAA"]["vigente"] is True


def test_el_lote_respeta_el_tope(app):
    """100, no 500 como sat69: cada término abre el portal de la STPS en vivo."""
    with TestClient(app) as client:
        r = _lote(client, [f"RFC{i:09d}" for i in range(101)])
    assert r.status_code == 400
    assert "100" in r.json()["error"]


def test_el_lote_sin_bearer_no_pasa(app_oauth):
    with TestClient(app_oauth) as client:
        assert client.post("/verificar-lote", json={"rfcs": ["ASE100712TT2"]}).status_code == 401


def test_el_lote_pide_la_lista(app):
    with TestClient(app) as client:
        assert client.post("/verificar-lote", json={}, headers=_auth()).status_code == 400
        assert client.post("/verificar-lote", json={"rfcs": []}, headers=_auth()).status_code == 400

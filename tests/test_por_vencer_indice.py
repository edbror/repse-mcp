"""`por_vencer` frente a un índice que todavía no existe (WE-880).

El índice vive en /tmp y Render recicla la instancia: tras un arranque en frío
tarda ~2 min en reconstruirse. Durante esa ventana la tool devolvía `total: 0`
sin decir por qué, y un cero callado se lee igual que "no hay nada por vencer"
— exactamente lo contrario de la verdad. Se fija que los dos casos (índice
vacío vs. índice listo sin coincidencias) sean distinguibles en un booleano.
"""

from __future__ import annotations

from repse import padron, server

VACIO = {"filas": 0, "ultima_importacion": None, "max_vigencia": None}
LLENO = {
    "filas": 158870,
    "ultima_importacion": "2026-09-27T05:25:03+00:00",
    "max_vigencia": "2029-01-01",
}


def test_indice_vacio_no_se_lee_como_sin_vencimientos(monkeypatch):
    monkeypatch.setattr(padron, "estado", lambda: VACIO)
    monkeypatch.setattr(
        padron, "por_vencer", lambda **kw: (_ for _ in ()).throw(AssertionError("no consultar"))
    )

    r = server.por_vencer(dias=30)

    assert r["indice_listo"] is False
    assert r["total"] == 0 and r["resultados"] == []
    assert "reconstruy" in r["nota"]


def test_indice_listo_sin_coincidencias_es_un_cero_honesto(monkeypatch):
    monkeypatch.setattr(padron, "estado", lambda: LLENO)
    monkeypatch.setattr(padron, "por_vencer", lambda **kw: [])

    r = server.por_vencer(dias=30)

    assert r["indice_listo"] is True
    assert r["total"] == 0


def test_indice_listo_con_filas(monkeypatch):
    fila = {"folio": 1, "razon_social": "X", "vigencia": "2026-10-01"}
    monkeypatch.setattr(padron, "estado", lambda: LLENO)
    monkeypatch.setattr(padron, "por_vencer", lambda **kw: [fila])

    r = server.por_vencer()

    assert r["indice_listo"] is True
    assert r["total"] == 1 and r["resultados"] == [fila]

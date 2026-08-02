"""Resolución término → registro, con un cliente falso (sin tocar la STPS)."""

from __future__ import annotations

import pytest

from repse.consulta import consultar
from repse.risk import SIN_REGISTRO


class FakeClient:
    """Imita RepseClient: `buscar` por substring, `detalle` por id."""

    def __init__(self, registros: dict[int, dict]):
        self.registros = registros
        self.detalles_pedidos: list[int] = []

    def buscar(self, termino: str) -> list[dict]:
        t = termino.upper()
        out = []
        for rid, payload in self.registros.items():
            data = payload["data"]
            if t in data["razon_social"].upper() or t == data["rfc"] or t == str(data["folio"]):
                out.append({"id": rid, "text": data["razon_social"]})
        return out

    def detalle(self, registro_id):
        self.detalles_pedidos.append(int(registro_id))
        return self.registros[int(registro_id)]


def _reg(rfc: str, razon: str, folio: int, vence: str = "2027-01-15 00:00:00") -> dict:
    return {
        "registro": 1,
        "data": {
            "rfc": rfc,
            "razon_social": razon,
            "folio": folio,
            "entidad": "México",
            "municipio": "Tlalnepantla",
            "fecha_vencimiento_registro": vence,
        },
        "actividades": [{"descripcion": "LIMPIEZA INDUSTRIAL"}],
    }


@pytest.fixture
def client():
    return FakeClient(
        {
            10: _reg("AAA010101AA1", "SERVICIOS ALFA SA DE CV", 111),
            20: _reg("BBB020202BB2", "SERVICIOS BETA SA DE CV", 222),
        }
    )


def test_rfc_elige_el_registro_correcto_no_el_primero(client):
    # El typeahead regresa ambos "SERVICIOS…"; con RFC debe abrir detalles hasta
    # dar con el que coincide, no quedarse con el primero.
    r = consultar("BBB020202BB2", client=client)
    assert r["encontrado"] is True
    assert r["rfc"] == "BBB020202BB2"
    assert r["razon_social"] == "SERVICIOS BETA SA DE CV"


def test_rfc_inexistente_no_devuelve_un_homonimo(client):
    # Búsqueda que sí trae texto pero ningún RFC coincide → SIN_REGISTRO,
    # nunca el vecino de al lado.
    client.registros[30] = _reg("CCC030303CC3", "CCC030303CC9 SERVICIOS", 333)
    r = consultar("CCC030303CC9", client=client)
    assert r["encontrado"] is False
    assert r["estado"] == SIN_REGISTRO
    assert r["vigente"] is False


def test_texto_libre_toma_el_primero_y_no_abre_de_mas(client):
    r = consultar("SERVICIOS", client=client)
    assert r["encontrado"] is True
    assert len(client.detalles_pedidos) == 1  # un solo detalle, no N
    assert r["candidatos"]  # avisa que hubo ambigüedad


def test_busqueda_por_folio(client):
    r = consultar("222", client=client)
    assert r["encontrado"] is True
    assert r["folio"] == 222


def test_sin_resultados_y_vacio(client):
    assert consultar("NOEXISTE SA", client=client)["estado"] == SIN_REGISTRO
    assert consultar("  ", client=client)["estado"] == SIN_REGISTRO

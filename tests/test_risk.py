"""Veredicto de vigencia — la aritmética que decide si se paga o no se paga."""

from __future__ import annotations

from datetime import date

from repse.risk import (
    INDETERMINADO,
    POR_VENCER,
    SIN_REGISTRO,
    VENCIDO,
    VIGENTE,
    evaluar,
    normalizar,
    normalizar_rfc,
    parse_fecha,
    rfc_valido,
)

HOY = date(2026, 8, 1)


def _payload(vence: str | None, registro: int = 1) -> dict:
    return {
        "registro": registro,
        "data": {
            "rfc": "ASE100712TT2",
            "razon_social": "ANDACOM SERVICIOS SA DE CV",
            "folio": 97261,
            "entidad": "México",
            "municipio": "Tlalnepantla de Baz",
            "fecha_vencimiento_registro": vence,
        },
        "actividades": [{"descripcion": "IMPLEMENTAR SISTEMAS DE COMPUTO "}],
    }


def test_rfc():
    assert normalizar_rfc(" ase100712tt2 ") == "ASE100712TT2"
    assert normalizar_rfc("ASE-100712-TT2") == "ASE100712TT2"
    assert rfc_valido("ASE100712TT2")  # moral, 12
    assert rfc_valido("OIRE900101HN4")  # física, 13
    assert not rfc_valido("NOPE")


def test_parse_fecha():
    assert parse_fecha("2024-09-10 00:00:00") == date(2024, 9, 10)
    assert parse_fecha("2024-09-10") == date(2024, 9, 10)
    assert parse_fecha(None) is None
    assert parse_fecha("basura") is None


def test_vencido_aunque_registro_sea_1():
    # El caso real que rompe a quien lee `registro` como vigencia: la STPS
    # devuelve registro=1 para un registro vencido en 2024.
    r = evaluar(_payload("2024-09-10 00:00:00"), hoy=HOY)
    assert r["estado"] == VENCIDO
    assert r["vigente"] is False
    assert r["dias_restantes"] < 0


def test_vigente():
    r = evaluar(_payload("2027-01-15 00:00:00"), hoy=HOY)
    assert r["estado"] == VIGENTE
    assert r["vigente"] is True
    assert r["dias_restantes"] == (date(2027, 1, 15) - HOY).days


def test_por_vencer_dentro_de_la_ventana():
    r = evaluar(_payload("2026-09-01 00:00:00"), hoy=HOY)  # 31 días
    assert r["estado"] == POR_VENCER
    assert r["vigente"] is True  # vigente hoy, pero hay que avisar


def test_frontera_exacta_de_vencimiento():
    # Vence hoy: sigue vigente (0 días), no vencido.
    r = evaluar(_payload("2026-08-01 00:00:00"), hoy=HOY)
    assert r["vigente"] is True
    assert r["dias_restantes"] == 0
    # Ayer: vencido.
    assert evaluar(_payload("2026-07-31 00:00:00"), hoy=HOY)["estado"] == VENCIDO


def test_sin_registro_y_sin_fecha():
    assert evaluar(_payload("2027-01-01", registro=0), hoy=HOY)["estado"] == SIN_REGISTRO
    assert evaluar({}, hoy=HOY)["estado"] == SIN_REGISTRO
    indet = evaluar(_payload(None), hoy=HOY)
    assert indet["estado"] == INDETERMINADO
    assert indet["vigente"] is False  # nunca aprobamos lo que no podemos afirmar


def test_normalizar_aplana_identidad_y_actividades():
    r = normalizar(_payload("2027-01-15 00:00:00"), hoy=HOY)
    assert r["rfc"] == "ASE100712TT2"
    assert r["folio"] == 97261
    assert r["actividades"] == ["IMPLEMENTAR SISTEMAS DE COMPUTO"]
    assert r["vigente"] is True

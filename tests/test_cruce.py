"""Veredicto combinado REPSE × SAT — la matriz de decisión completa."""

from __future__ import annotations

from repse.cruce import APROBADO, INCOMPLETO, RECHAZADO, REVISAR, combinar

VIGENTE = {
    "vigente": True,
    "estado": "VIGENTE",
    "fecha_vencimiento": "2028-01-01",
    "veredicto": "Vigente",
}
VENCIDO = {"vigente": False, "estado": "VENCIDO", "veredicto": "Vencido desde 2024"}
POR_VENCER = {"vigente": True, "estado": "POR_VENCER", "veredicto": "Vence en 30 días"}
REPSE_ERROR = {"vigente": False, "estado": "ERROR", "veredicto": "portal caído"}

LIMPIO = {"disponible": True, "riesgo": "LIMPIO", "veredicto": "Sin coincidencias"}
EFOS = {"disponible": True, "riesgo": "CRITICO", "veredicto": "EFOS DEFINITIVO"}
PRESUNTO = {"disponible": True, "riesgo": "ALTO", "veredicto": "EFOS PRESUNTO"}
SAT_CAIDO = {"disponible": False, "error": "timeout"}


def test_vigente_y_limpio_aprueba():
    r = combinar(VIGENTE, LIMPIO)
    assert r["decision"] == APROBADO and r["aprobado"] is True


def test_efos_definitivo_rechaza_aunque_repse_vigente():
    # La razón de ser del cruce.
    r = combinar(VIGENTE, EFOS)
    assert r["decision"] == RECHAZADO
    assert any("CRITICO" in x for x in r["razones"])


def test_repse_vencido_rechaza_aunque_sat_limpio():
    assert combinar(VENCIDO, LIMPIO)["decision"] == RECHAZADO


def test_presunto_pide_revision():
    assert combinar(VIGENTE, PRESUNTO)["decision"] == REVISAR


def test_por_vencer_pide_revision():
    assert combinar(POR_VENCER, LIMPIO)["decision"] == REVISAR


def test_sat_caido_nunca_aprueba_a_ciegas():
    r = combinar(VIGENTE, SAT_CAIDO)
    assert r["decision"] == INCOMPLETO and r["aprobado"] is False


def test_repse_caido_es_incompleto_no_rechazado():
    assert combinar(REPSE_ERROR, LIMPIO)["decision"] == INCOMPLETO


def test_doble_falla_rechaza_si_sat_bloquea():
    # EFOS definitivo manda aunque REPSE no se haya podido consultar.
    assert combinar(REPSE_ERROR, EFOS)["decision"] == RECHAZADO

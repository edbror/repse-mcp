"""El lado de listas del cruce: traducir `severidad_fuente` a riesgo, sin copiar el criterio.

Centinela devuelve la gravedad de la lista en cada coincidencia. Estas pruebas
fijan la traducción a los niveles que `cruce.py` consume, y sobre todo fijan los
dos casos donde equivocarse cuesta caro: una coincidencia descartada por
identificador no cuenta, y ser PEP no rechaza.
"""

from __future__ import annotations

from repse.centinela import SEVERIDAD_BLOQUEA, _riesgo


def match(
    severidad: int,
    confianza: str = "HIGH_CONFIDENCE_MATCH",
    fuente: str = "X",
    nombre: str = "N",
):
    return {
        "severidad_fuente": severidad,
        "confidence_category": confianza,
        "provenance": {"source_name": fuente},
        "entity": {"primary_name": nombre},
    }


def test_sin_coincidencias_es_limpio():
    riesgo, detalle = _riesgo([])
    assert riesgo == "LIMPIO"
    assert detalle == []


def test_lista_grave_confirmada_rechaza():
    # Severidad 4 y 5 son el EFOS mexicano y los bloques grandes de sanciones.
    for severidad in (SEVERIDAD_BLOQUEA, 5):
        riesgo, _ = _riesgo([match(severidad)])
        assert riesgo == "CRITICO", f"severidad {severidad} debe bloquear"


def test_inhabilitacion_manda_a_revision_no_a_rechazo():
    # Severidad 2 y 3: impiden contratar o congelan en otra jurisdicción, pero
    # no son el EFOS que invalida los CFDI. El obligado decide con el expediente.
    for severidad in (2, 3):
        riesgo, _ = _riesgo([match(severidad)])
        assert riesgo == "ALTO"


# **Ser PEP vale 0 y aun así va a revisión, no a rechazo.** No es una acusación,
# pero obliga a diligencia reforzada: aprobar en automático sería el error.
def test_ser_pep_revisa_pero_no_rechaza():
    riesgo, _ = _riesgo([match(0, fuente="PEP_REGTECH")])
    assert riesgo == "MEDIO"
    assert riesgo not in {"CRITICO"}


def test_una_coincidencia_descartada_no_cuenta():
    # FALSE_POSITIVE_DISAMBIGUATED es la que el motor descartó porque un
    # identificador duro no empata. Contarla sería el falso positivo que ese
    # motor existe para no cometer.
    riesgo, detalle = _riesgo([match(5, confianza="FALSE_POSITIVE_DISAMBIGUATED")])
    assert riesgo == "LIMPIO"
    assert detalle == []


def test_manda_el_peor_match_no_el_primero():
    # El orden de `matches` lo decide el score, no la gravedad: si se tomara el
    # primero, una coincidencia en OFAC detrás de una del art. 69 no bloquearía.
    riesgo, detalle = _riesgo([match(0, fuente="SAT_69"), match(5, fuente="OFAC_SDN")])
    assert riesgo == "CRITICO"
    assert len(detalle) == 2, "el sustento declara todas las coincidencias vivas"


def test_grave_sin_confirmar_revisa_en_vez_de_rechazar():
    # Un UNCERTAIN_NEEDS_REVIEW en una lista grave NO es un rechazo: el motor
    # dijo que no puede decidir, y convertir ese "no sé" en un "no" es
    # exactamente lo que la tercera regla dura de Centinela evita.
    riesgo, _ = _riesgo([match(5, confianza="UNCERTAIN_NEEDS_REVIEW")])
    assert riesgo == "ALTO"


def test_severidad_ausente_no_bloquea():
    # Una fuente que Centinela no tenga rankeada devuelve 0. El valor seguro es
    # el que no afirma.
    riesgo, _ = _riesgo([{"confidence_category": "HIGH_CONFIDENCE_MATCH"}])
    assert riesgo == "MEDIO"

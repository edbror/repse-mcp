"""
Veredicto combinado REPSE × SAT 69/69-B — la regla de debida diligencia.

Determinista, sin IA. Un proveedor REPSE-vigente que es EFOS definitivo sigue
siendo un "no": el CFDI que emite no produce efectos fiscales aunque la STPS lo
tenga al corriente. Y al revés: LIMPIO en el SAT no salva a un REPSE vencido.
"""

from __future__ import annotations

APROBADO = "APROBADO"
REVISAR = "REVISAR"
RECHAZADO = "RECHAZADO"
INCOMPLETO = "INCOMPLETO"

# Riesgos sat69 que bloquean o piden revisión.
_SAT_BLOQUEA = {"CRITICO"}
_SAT_REVISA = {"ALTO", "MEDIO"}


def combinar(repse: dict, sat: dict) -> dict:
    """Combina los dos veredictos en una decisión única.

    RECHAZADO  — REPSE no vigente, o EFOS definitivo (69-B).
    REVISAR    — vigente pero con banderas: SAT ALTO/MEDIO o REPSE POR_VENCER.
    APROBADO   — vigente y sin banderas relevantes en el SAT.
    INCOMPLETO — un lado no se pudo consultar; nunca se aprueba a ciegas.
    """
    razones: list[str] = []

    repse_vigente = bool(repse.get("vigente"))
    # ERROR = el portal no respondió; distinto de "consultado y no vigente".
    repse_consultado = repse.get("estado") != "ERROR"
    sat_disponible = bool(sat.get("disponible"))
    riesgo_sat = (sat.get("riesgo") or "").upper() if sat_disponible else None

    if repse_consultado and not repse_vigente:
        razones.append(f"REPSE {repse.get('estado', 'SIN_REGISTRO')}: {repse.get('veredicto', '')}")
    if riesgo_sat in _SAT_BLOQUEA:
        razones.append(f"SAT {riesgo_sat}: {sat.get('veredicto', '')}")

    if razones:
        decision = RECHAZADO
    elif not repse_consultado:
        decision = INCOMPLETO
        razones.append(
            f"REPSE no consultado ({repse.get('veredicto', 'sin detalle')}). "
            "No apruebes sin confirmar la vigencia en la STPS."
        )
    elif not sat_disponible:
        decision = INCOMPLETO
        razones.append(
            "SAT 69/69-B no consultado (" + str(sat.get("error", "sin detalle")) + "). "
            "El lado REPSE está vigente, pero no apruebes sin el cruce fiscal."
        )
    elif riesgo_sat in _SAT_REVISA or repse.get("estado") == "POR_VENCER":
        decision = REVISAR
        if riesgo_sat in _SAT_REVISA:
            razones.append(f"SAT {riesgo_sat}: {sat.get('veredicto', '')}")
        if repse.get("estado") == "POR_VENCER":
            razones.append(f"REPSE POR_VENCER: {repse.get('veredicto', '')}")
    else:
        decision = APROBADO
        razones.append(
            f"REPSE vigente hasta {repse.get('fecha_vencimiento')} y SAT {riesgo_sat or 'LIMPIO'}."
        )

    return {
        "decision": decision,
        "aprobado": decision == APROBADO,
        "razones": razones,
        "repse": repse,
        "sat_69_69b": sat,
    }

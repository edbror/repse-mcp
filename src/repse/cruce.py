"""
Veredicto combinado REPSE × listas restrictivas — la regla de debida diligencia.

Determinista, sin IA. Un proveedor REPSE-vigente que es EFOS definitivo sigue
siendo un "no": el CFDI que emite no produce efectos fiscales aunque la STPS lo
tenga al corriente. Y al revés: LIMPIO en las listas no salva a un REPSE vencido.

El lado de listas lo resuelve Centinela (38 listas, recibo auditable) y no
sat69-mcp (4 listas, servicio suspendido). Lo que esta función consume no cambió:
el mismo `{disponible, riesgo, veredicto}`, con `riesgo` ya traducido allá desde
la severidad de la fuente. **La traducción vive en un solo lado a propósito**:
derivar aquí la gravedad desde el nombre de la lista sería una segunda copia del
criterio.
"""

from __future__ import annotations

APROBADO = "APROBADO"
REVISAR = "REVISAR"
RECHAZADO = "RECHAZADO"
INCOMPLETO = "INCOMPLETO"

# Riesgos que bloquean o piden revisión. Los traduce centinela.py desde
# `severidad_fuente`; aquí solo se decide qué hacer con ellos.
_SAT_BLOQUEA = {"CRITICO"}
_SAT_REVISA = {"ALTO", "MEDIO"}


def combinar(repse: dict, sat: dict) -> dict:
    """Combina los dos veredictos en una decisión única.

    RECHAZADO  — REPSE no vigente, o coincidencia confirmada en una lista grave.
    REVISAR    — vigente pero con banderas: listas ALTO/MEDIO o REPSE POR_VENCER.
    APROBADO   — vigente y sin banderas relevantes en las listas.
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
        razones.append(f"Listas {riesgo_sat}: {sat.get('veredicto', '')}")

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
            "Listas restrictivas no consultadas (" + str(sat.get("error", "sin detalle")) + "). "
            "El lado REPSE está vigente, pero no apruebes sin el cruce."
        )
    elif riesgo_sat in _SAT_REVISA or repse.get("estado") == "POR_VENCER":
        decision = REVISAR
        if riesgo_sat in _SAT_REVISA:
            razones.append(f"Listas {riesgo_sat}: {sat.get('veredicto', '')}")
        if repse.get("estado") == "POR_VENCER":
            razones.append(f"REPSE POR_VENCER: {repse.get('veredicto', '')}")
    else:
        decision = APROBADO
        razones.append(
            f"REPSE vigente hasta {repse.get('fecha_vencimiento')} "
            f"y listas {riesgo_sat or 'LIMPIO'}."
        )

    # **`listas` reemplaza a `sat_69_69b`, y es un cambio de contrato.** El
    # nombre viejo decía qué se consultaba y ahora serían 38 listas, no dos: un
    # agente que lea `sat_69_69b` y reporte "verificado contra el SAT" estaría
    # subdeclarando la cobertura, y en un producto de cumplimiento una clave que
    # miente sobre su contenido es peor que una clave renombrada.
    return {
        "decision": decision,
        "aprobado": decision == APROBADO,
        "razones": razones,
        "repse": repse,
        "listas": sat,
    }

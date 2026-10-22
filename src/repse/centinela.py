"""
Cliente hacia Centinela: el lado de listas restrictivas del cruce de debida
diligencia.

## Por qué reemplazó a sat69-mcp

El cruce consultaba `sat69-mcp` por MCP-over-HTTP, que cubre **cuatro** listas del
SAT (69-B, 69-B Bis, art. 69 y CSD sin efectos). Centinela cubre **38**, incluidas
esas cuatro, y devuelve además un recibo auditable: cada coincidencia carga la URL
de la fuente, su fecha de corte, cuándo se extrajo y el SHA-256 del contenido
procesado, y la consulta queda persistida con su `query_id`.

Y había una razón más urgente, medida el 2026-10-21: **el cruce no funcionaba.**
`verificar_proveedor` devolvía `INCOMPLETO` en cada llamada, por dos motivos
independientes. La llave no estaba configurada (*"SAT69_MCP_KEY no configurada;
cruce SAT 69/69-B deshabilitado"*) y el servicio del que dependía está suspendido
(*"This service has been suspended by its owner"*).

## Sin llave NO se deshabilita

El cliente anterior exigía `SAT69_MCP_KEY` y, sin ella, apagaba el cruce entero.
Centinela tiene dos carriles: sin encabezado responde con su razonador
determinista y 10 consultas por minuto; con llave de cliente usa el carril de IA
y el límite de la llave. **Así que sin configurar nada el cruce sigue dando un
veredicto real**, y `CENTINELA_API_KEY` solo cambia el carril. Lo que viaja de
vuelta incluye cuál respondió, en `method`.

## La escala de gravedad NO se reimplementa aquí

Centinela devuelve `severidad_fuente` (0 a 5) en cada coincidencia, que es el
mismo número con el que su Etapa 1 decide a quién le da lugar en el cupo. Derivar
el nivel desde el `source_name` de este lado sería una segunda copia del
criterio, y en ese repo eso ya costó un defecto en producción: dos
implementaciones de la Etapa 1 contestando distinto durante meses (WE-1111).

| `severidad_fuente` | Qué hay ahí | Aquí |
|---|---|---|
| 5, 4 | bloqueo de activos, y el EFOS que invalida CFDI | `CRITICO`, rechaza |
| 3, 2 | otros regímenes de congelamiento, inhabilitaciones | `ALTO`, revisa |
| 1, 0 | señal para investigar; estatus o exposición (PEP) | `MEDIO`, revisa |

**Ser PEP vale 0 y aun así manda a revisión**, no a rechazo: no es una acusación,
pero sí obliga a diligencia reforzada. Y una coincidencia
`FALSE_POSITIVE_DISAMBIGUATED` **no cuenta**: es la que el motor descartó porque
un identificador duro no empata, y contarla sería el falso positivo que ese motor
existe para no cometer.
"""

from __future__ import annotations

import logging

import httpx

from .config import settings

logger = logging.getLogger(__name__)

# Severidad mínima para rechazar. 4 es el EFOS mexicano y los bloques grandes de
# sanciones; de ahí para abajo el obligado decide con el expediente a la vista.
SEVERIDAD_BLOQUEA = 4

_DESCARTADA = "FALSE_POSITIVE_DISAMBIGUATED"


def configurado() -> bool:
    """Siempre: el carril anónimo no necesita llave. Ver el encabezado."""
    return bool(settings.centinela_url)


def con_llave() -> bool:
    return bool(settings.centinela_key)


def _riesgo(matches: list[dict]) -> tuple[str, list[str]]:
    """El riesgo es el del PEOR match que no fue descartado, con su sustento."""
    vivas = [m for m in matches if m.get("confidence_category") != _DESCARTADA]
    if not vivas:
        return "LIMPIO", []

    peor = max(vivas, key=lambda m: int(m.get("severidad_fuente") or 0))
    severidad = int(peor.get("severidad_fuente") or 0)
    confirmada = peor.get("confidence_category") == "HIGH_CONFIDENCE_MATCH"

    if severidad >= SEVERIDAD_BLOQUEA and confirmada:
        riesgo = "CRITICO"
    elif severidad >= 2:
        riesgo = "ALTO"
    else:
        riesgo = "MEDIO"

    detalle = []
    for m in vivas:
        fuente = (m.get("provenance") or {}).get("source_name", "?")
        nombre = (m.get("entity") or {}).get("primary_name", "?")
        detalle.append(
            f"{fuente} ({m.get('confidence_category', '?')}, severidad "
            f"{m.get('severidad_fuente', '?')}): {nombre}"
        )
    return riesgo, detalle


async def verificar_rfc(rfc: str, nombre: str | None = None) -> dict:
    """Criba un RFC contra las 38 listas. Devuelve {disponible, riesgo, veredicto, …}.

    Nunca lanza: si Centinela no responde, el cruce sale `INCOMPLETO` y no se
    aprueba a ciegas un lado que no se pudo consultar.
    """
    cuerpo: dict[str, str] = {"rfc": rfc}
    # El nombre mejora la Etapa 1 cuando lo hay, pero el RFC es lo que decide:
    # con identificador en los dos lados las reglas duras resuelven sin escalar.
    cuerpo["name"] = nombre or rfc

    cabeceras = {"content-type": "application/json"}
    if settings.centinela_key:
        cabeceras["authorization"] = f"Bearer {settings.centinela_key}"

    try:
        async with httpx.AsyncClient(timeout=settings.centinela_timeout) as cliente:
            res = await cliente.post(
                f"{settings.centinela_url}/v1/screen", json=cuerpo, headers=cabeceras
            )
        if res.status_code == 429:
            return {
                "disponible": False,
                "error": (
                    "Centinela devolvió 429 (límite del carril anónimo: 10/min). "
                    "Configura CENTINELA_API_KEY para el límite de tu llave."
                ),
            }
        res.raise_for_status()
        datos = res.json()
    except Exception as exc:  # noqa: BLE001 — cualquier falla degrada a INCOMPLETO
        logger.warning("Centinela no disponible para %s: %s", rfc, exc)
        return {"disponible": False, "error": f"Centinela no respondió: {exc}"}

    matches = datos.get("matches") or []
    riesgo, detalle = _riesgo(matches)
    descartadas = sum(1 for m in matches if m.get("confidence_category") == _DESCARTADA)

    if riesgo == "LIMPIO":
        veredicto = "Sin coincidencias en las listas restrictivas."
        if descartadas:
            veredicto += (
                f" {descartadas} coincidencia(s) de nombre descartada(s)"
                " por identificador distinto."
            )
    else:
        veredicto = "; ".join(detalle)

    return {
        "disponible": True,
        "riesgo": riesgo,
        "veredicto": veredicto,
        # Para el recibo: con esto se recupera la consulta completa y su
        # constancia en Centinela meses después.
        "query_id": datos.get("query_id"),
        "total_matches": datos.get("total_matches", len(matches)),
        "descartadas": descartadas,
        "carril": (matches[0].get("method") if matches else None)
        or ("llm" if con_llave() else "deterministic"),
        # Una entidad en varias jurisdicciones viene agrupada: son N
        # designaciones de una persona, no N personas.
        "grupos": datos.get("grupos") or [],
    }

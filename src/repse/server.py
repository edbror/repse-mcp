"""
Servidor FastMCP — Padrón Público REPSE (STPS).

Tools expuestas:
  • verificar_repse   — un RFC/folio/razón social → veredicto de vigencia
  • verificar_lote    — cartera de proveedores → sólo lo que requiere acción
  • buscar_padron     — búsqueda por razón social (typeahead del padrón)
  • estado_fuente     — salud y latencia del portal de la STPS
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from fastmcp import FastMCP

from .client import RepseError, get_client
from .config import settings
from .consulta import consultar
from .risk import SIN_REGISTRO, VENCIDO, normalizar_rfc

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _build_auth():
    """Provider OAuth (WorkOS AuthKit) si está configurado, o None."""
    if not settings.oauth_enabled:
        return None
    from fastmcp.server.auth.providers.workos import AuthKitProvider, WorkOSTokenVerifier

    logger.info("OAuth habilitado vía AuthKit (%s)", settings.authkit_domain)
    # Igual que sat69/SSC: verificamos por userinfo, sin chequeo de audience, para
    # NO tener que registrar resource indicators en WorkOS (hacerlo rompió SSC).
    return AuthKitProvider(
        authkit_domain=settings.authkit_domain,
        base_url=settings.base_url_public,
        token_verifier=WorkOSTokenVerifier(authkit_domain=settings.authkit_domain),
    )


mcp = FastMCP(
    name="repse",
    auth=_build_auth(),
    instructions="""\
Consulta el Padrón Público de Contratistas de Servicios Especializados u Obras
Especializadas (REPSE) de la STPS, en vivo.

Úsalo antes de dar de alta, contratar o pagar a un proveedor de servicios
especializados en México. Sin registro REPSE vigente, el contratante pierde la
deducción de IVA/ISR de esas facturas y asume responsabilidad solidaria como
patrón.

Lee SIEMPRE el campo `vigente` (booleano) para decidir. El campo `estado`
distingue VIGENTE / POR_VENCER / VENCIDO / SIN_REGISTRO / INDETERMINADO.

Verifica además que la ACTIVIDAD autorizada cubra el servicio contratado: un
proveedor vigente para "limpieza industrial" no está autorizado para vigilancia.

Esto informa; no sustituye la constancia oficial ni el criterio legal.""",
)


@mcp.tool
def verificar_repse(termino: str) -> dict:
    """Verifica un proveedor en el padrón REPSE por RFC, folio o razón social.

    Args:
        termino: RFC (p. ej. ASE100712TT2), folio de registro o razón social.

    Returns:
        Veredicto con `vigente`, `estado`, fecha de vencimiento y las
        actividades especializadas autorizadas.
    """
    try:
        return consultar(termino)
    except RepseError as exc:
        logger.error("verificar_repse(%s) falló: %s", termino, exc)
        return {"consulta": termino, "error": str(exc), "vigente": None}


@mcp.tool
def verificar_lote(rfcs: list[str]) -> dict:
    """Verifica una cartera de proveedores y resume lo que requiere acción.

    Args:
        rfcs: lista de RFCs, folios o razones sociales.

    Returns:
        Conteos por estado y el detalle SÓLO de los que no están vigentes.
    """
    terminos = [t for t in (s.strip() for s in rfcs or []) if t]
    if not terminos:
        return {"total": 0, "resumen": {}, "hallazgos": [], "errores": []}

    resultados: list[dict] = []
    errores: list[dict] = []

    def _uno(termino: str) -> None:
        try:
            resultados.append(consultar(termino))
        except RepseError as exc:
            errores.append({"consulta": termino, "error": str(exc)})

    with ThreadPoolExecutor(max_workers=settings.batch_concurrency) as pool:
        list(pool.map(_uno, terminos))

    resumen: dict[str, int] = {}
    for r in resultados:
        estado = r.get("estado", "DESCONOCIDO")
        resumen[estado] = resumen.get(estado, 0) + 1

    # Sólo devolvemos lo accionable: una cartera de 500 proveedores no cabe —
    # ni le sirve a nadie— completa en el contexto del agente.
    hallazgos = [r for r in resultados if not r.get("vigente")]
    hallazgos.sort(key=lambda r: (r.get("estado") != VENCIDO, r.get("estado") != SIN_REGISTRO))

    return {
        "total": len(terminos),
        "consultados": len(resultados),
        "resumen": resumen,
        "vigentes": sum(1 for r in resultados if r.get("vigente")),
        "hallazgos": hallazgos,
        "errores": errores,
    }


@mcp.tool
def buscar_padron(texto: str, limite: int = 20) -> dict:
    """Busca en el padrón por razón social (o fragmento de RFC/folio).

    Args:
        texto: nombre, razón social, RFC o folio (búsqueda parcial).
        limite: máximo de coincidencias a devolver (default 20).

    Returns:
        Coincidencias con su id interno; usa `verificar_repse` para el veredicto.
    """
    try:
        resultados = get_client().buscar(texto)
    except RepseError as exc:
        return {"texto": texto, "error": str(exc), "resultados": []}
    return {
        "texto": texto,
        "total": len(resultados),
        "resultados": [
            {"id": r.get("id"), "razon_social": r.get("text")} for r in resultados[: max(1, limite)]
        ],
        "nota": "El typeahead no expone el RFC; usa verificar_repse para confirmarlo.",
    }


@mcp.tool
def estado_fuente() -> dict:
    """Salud del portal de la STPS: disponibilidad y latencia de la consulta.

    Returns:
        Estado, latencia en ms y la URL de la fuente. No hay índice local: cada
        consulta va en vivo al padrón, así que la frescura del dato es total.
    """
    inicio = time.perf_counter()
    try:
        # Sonda barata contra un término que siempre existe en el padrón.
        resultados = get_client().buscar("SERVICIOS")
        ms = round((time.perf_counter() - inicio) * 1000)
        return {
            "status": "ok" if resultados else "degradado",
            "latencia_ms": ms,
            "muestra": len(resultados),
            "fuente": settings.base_url,
            "frescura": "en vivo (sin índice local)",
        }
    except RepseError as exc:
        return {
            "status": "error",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000),
            "error": str(exc),
            "fuente": settings.base_url,
        }


def main() -> None:
    """Transporte stdio (Claude Desktop / Claude Code)."""
    mcp.run()


__all__ = ["mcp", "main", "normalizar_rfc"]

if __name__ == "__main__":
    main()

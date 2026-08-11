"""
Servidor FastMCP — Padrón Público REPSE (STPS).

Tools expuestas:
  • verificar_repse     — un RFC/folio/razón social → veredicto de vigencia (EN VIVO)
  • verificar_proveedor — cruce REPSE × SAT 69/69-B → decisión única de debida diligencia
  • verificar_lote      — cartera de proveedores → sólo lo que requiere acción (EN VIVO)
  • buscar_padron       — búsqueda masiva en el índice local (FTS5, paginada)
  • por_vencer          — registros del índice cuya vigencia cae en una ventana
  • estado_fuente       — salud del portal en vivo + frescura del índice local
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from fastmcp import FastMCP

from . import cruce as cruce_mod
from . import padron, sat69
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
    import secrets as _secrets

    from fastmcp.server.auth import AccessToken
    from fastmcp.server.auth.providers.workos import AuthKitProvider, WorkOSTokenVerifier

    logger.info("OAuth habilitado vía AuthKit (%s)", settings.authkit_domain)

    class DualVerifier(WorkOSTokenVerifier):
        """Acepta el MCP_API_KEY estático (servidor-a-servidor) O un token OAuth.

        Con OAuth encendido, FastMCP es el único guardián de /connect y el
        verifier por defecto rechazaba la key estática con 401 invalid_token —
        las apps máquina-a-máquina (sin flujo authorization_code) quedaban
        fuera. Se checa la key primero (compare_digest) y si no, AuthKit.
        """

        async def verify_token(self, token: str) -> AccessToken | None:
            if settings.mcp_api_key and _secrets.compare_digest(token, settings.mcp_api_key):
                return AccessToken(token=token, client_id="watr-static-key", scopes=[])
            return await super().verify_token(token)

    # Igual que sat69/SSC: verificamos por userinfo, sin chequeo de audience, para
    # NO tener que registrar resource indicators en WorkOS (hacerlo rompió SSC).
    return AuthKitProvider(
        authkit_domain=settings.authkit_domain,
        base_url=settings.base_url_public,
        token_verifier=DualVerifier(authkit_domain=settings.authkit_domain),
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
async def verificar_proveedor(rfc: str) -> dict:
    """Debida diligencia completa: cruce REPSE (STPS) × listas SAT 69/69-B.

    Un proveedor REPSE-vigente que es EFOS definitivo sigue siendo un "no", y
    un LIMPIO en el SAT no salva a un REPSE vencido — por eso el cruce.

    Args:
        rfc: RFC del proveedor (física o moral).

    Returns:
        `decision` (APROBADO / REVISAR / RECHAZADO / INCOMPLETO) con las
        razones y los dos veredictos completos. INCOMPLETO significa que un
        lado no se pudo consultar: no aprobar hasta completarlo.
    """
    from starlette.concurrency import run_in_threadpool

    try:
        lado_repse = await run_in_threadpool(consultar, rfc)
    except RepseError as exc:
        lado_repse = {"vigente": False, "estado": "ERROR", "veredicto": str(exc)}
    lado_sat = await sat69.verificar_rfc(normalizar_rfc(rfc))
    return {"rfc": normalizar_rfc(rfc), **cruce_mod.combinar(lado_repse, lado_sat)}


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
def buscar_padron(
    texto: str, entidad: str | None = None, limite: int = 20, offset: int = 0
) -> dict:
    """Búsqueda masiva en el padrón por razón social o actividad, con paginación.

    Args:
        texto: palabras a buscar en razón social o actividades (ej. "limpieza industrial").
        entidad: filtro opcional por estado (ej. "Jalisco").
        limite: resultados por página (máx 100).
        offset: desplazamiento para paginar.

    Returns:
        Coincidencias del índice local (folio, razón social, ubicación, vigencia,
        actividades). Usa `verificar_repse` con el folio para el veredicto con RFC.
    """
    filas = padron.buscar(texto, entidad=entidad, limite=limite, offset=offset)
    if filas:
        return {
            "texto": texto,
            "fuente": "indice_local",
            "total_pagina": len(filas),
            "offset": offset,
            "resultados": filas,
        }
    # Índice vacío (primer boot) → fallback al typeahead en vivo (tapa en 30).
    if padron.estado()["filas"] == 0:
        try:
            vivos = get_client().buscar(texto)
        except RepseError as exc:
            return {"texto": texto, "error": str(exc), "resultados": []}
        return {
            "texto": texto,
            "fuente": "typeahead_vivo (índice aún no construido; tapa en 30)",
            "total_pagina": len(vivos[: max(1, limite)]),
            "resultados": [
                {"id": r.get("id"), "razon_social": r.get("text")} for r in vivos[: max(1, limite)]
            ],
        }
    return {"texto": texto, "fuente": "indice_local", "total_pagina": 0, "resultados": []}


@mcp.tool
def por_vencer(dias: int = 60, entidad: str | None = None, limite: int = 50) -> dict:
    """Registros del padrón cuya vigencia vence dentro de la ventana dada.

    Args:
        dias: tamaño de la ventana desde hoy (default 60).
        entidad: filtro opcional por estado.
        limite: máximo de registros (máx 200), ordenados por fecha de vencimiento.

    Returns:
        Registros próximos a vencer — insumo para pedir renovaciones a tiempo.
    """
    filas = padron.por_vencer(dias=dias, entidad=entidad, limite=limite)
    est = padron.estado()
    return {
        "ventana_dias": dias,
        "total": len(filas),
        "resultados": filas,
        "indice": est,
        "nota": "El xlsx del padrón no trae RFC; confirma con verificar_repse(folio).",
    }


@mcp.tool
def estado_fuente() -> dict:
    """Salud del portal en vivo de la STPS + frescura del índice local.

    Returns:
        Latencia del portal (usado por verificar_repse/verificar_lote) y estado
        del índice local (usado por buscar_padron/por_vencer): filas, última
        importación y vigencia máxima.
    """
    inicio = time.perf_counter()
    try:
        # Sonda barata contra un término que siempre existe en el padrón.
        resultados = get_client().buscar("SERVICIOS")
        vivo = {
            "status": "ok" if resultados else "degradado",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000),
            "muestra": len(resultados),
        }
    except RepseError as exc:
        vivo = {
            "status": "error",
            "latencia_ms": round((time.perf_counter() - inicio) * 1000),
            "error": str(exc),
        }
    return {"fuente": settings.base_url, "portal_vivo": vivo, "indice_local": padron.estado()}


def main() -> None:
    """Transporte stdio (Claude Desktop / Claude Code)."""
    mcp.run()


__all__ = ["mcp", "main", "normalizar_rfc"]

if __name__ == "__main__":
    main()

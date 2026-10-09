"""
Punto de entrada HTTP para el despliegue en Render.

Envuelve el servidor FastMCP con:
  • Transporte Streamable HTTP en /connect (igual que sat69 y SSC).
  • Bearer estático (MCP_API_KEY) selectivo por ruta.
  • Landing de venta en / y /health sin auth.
  • /refresh (bearer siempre) para reconstruir el índice local; al boot se
    reconstruye en hilo daemon si está vacío o viejo (rebuild-on-boot, sin Turso).
  • /verificar (bearer siempre) — la misma consulta que la tool, en REST plano,
    para backends que no hablan MCP.
  • /verificar-lote (bearer siempre) — hasta 100 términos por llamada, en paralelo.

Arranque:
    python -m repse.web   |   repse-web
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

from .config import settings

logger = logging.getLogger(__name__)

MCP_PATH = "/connect"
# Fuente única: landing/public/index.html (repo, para dev y el worker de
# Cloudflare). En el wheel viaja incrustada como repse/landing.html
# (force-include en pyproject) porque landing/ no se empaqueta.
_LANDING_CANDIDATES = (
    Path(__file__).resolve().parent / "landing.html",
    Path(__file__).resolve().parents[2] / "landing" / "public" / "index.html",
)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Bearer estático (MCP_API_KEY) selectivo por ruta.

    - / y /health → siempre abiertos (landing pública y health check de Render).
    - /connect    → OAuth ON: lo maneja FastMCP/AuthKit. OAuth OFF: Bearer estático.
    No-op si MCP_API_KEY no está definido (desarrollo local).
    """

    def _needs_static_bearer(self, path: str) -> bool:
        if path in ("/", "/health"):
            return False
        if path in ("/refresh", "/verificar", "/verificar-lote"):
            return True  # máquina-a-máquina (cron, backends): bearer siempre
        return not settings.oauth_enabled

    async def dispatch(self, request: Request, call_next):
        if not settings.mcp_api_key or not self._needs_static_bearer(request.url.path):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "Falta el header Authorization"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if auth[len("Bearer ") :] != settings.mcp_api_key:
            return JSONResponse(
                {"error": "Token inválido"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


# Tope por lote. Más bajo que el de sat69 (500) y a propósito: allá la consulta es
# SQLite local; aquí **cada término abre el portal de la STPS en vivo**, con búsqueda
# y apertura de detalle. El índice local no sirve para esto: su tabla `padron` no
# tiene columna de RFC —el typeahead de la STPS nunca lo devuelve, sólo el detalle—
# así que no hay forma de resolver un RFC sin ir al portal.
#
# 100 × ~2 s / BATCH_CONCURRENCY=4 ≈ 50 s por llamada: cabe en un request y no
# convierte el padrón público en un blanco de carga.
MAX_LOTE = 100


async def _verificar_lote(request: Request) -> JSONResponse:
    """Consulta hasta 100 términos en paralelo, reusando el pool de la tool.

    Devuelve **todos** los términos, no sólo los que no están vigentes —al revés que
    la tool `verificar_lote` del MCP. La tool le habla a un modelo, que quiere la
    señal; esto le habla a un expediente de defensa, donde "lo verifiqué el día D y
    estaba vigente" ES la evidencia de diligencia. Omitir los vigentes sería omitir
    la mitad de la prueba.
    """
    from concurrent.futures import ThreadPoolExecutor

    from starlette.concurrency import run_in_threadpool

    from .client import RepseError
    from .consulta import consultar

    try:
        cuerpo = await request.json()
    except Exception:
        return JSONResponse({"error": "Se espera un JSON con la clave `rfcs`."}, status_code=400)

    terminos = cuerpo.get("rfcs") if isinstance(cuerpo, dict) else None
    terminos = [t for t in (str(x).strip() for x in terminos or []) if t]
    if not terminos:
        return JSONResponse({"error": "Falta la lista `rfcs`."}, status_code=400)
    if len(terminos) > MAX_LOTE:
        return JSONResponse(
            {"error": f"Máximo {MAX_LOTE} términos por lote; llegaron {len(terminos)}."},
            status_code=400,
        )

    def _uno(termino: str) -> tuple[str, dict]:
        try:
            return termino, consultar(termino)
        except RepseError as exc:
            # 502 individual: el portal falló para ESE término. No es "no tiene
            # REPSE" — quien llama tiene que poder distinguirlo, igual que en la
            # ruta de uno solo.
            return termino, {"error": str(exc), "fuente_caida": True}

    def _todos() -> dict:
        with ThreadPoolExecutor(max_workers=settings.batch_concurrency) as pool:
            return dict(pool.map(_uno, terminos))

    resultados = await run_in_threadpool(_todos)
    caidos = sum(1 for r in resultados.values() if r.get("fuente_caida"))
    return JSONResponse(
        {"total": len(terminos), "fuente_caida": caidos, "resultados": resultados}
    )


async def _landing(request: Request) -> HTMLResponse:
    for candidate in _LANDING_CANDIDATES:
        try:
            return HTMLResponse(candidate.read_text(encoding="utf-8"))
        except OSError:
            continue
    return HTMLResponse("<h1>REPSE MCP</h1><p>Landing no disponible.</p>", status_code=200)


async def _health(request: Request) -> PlainTextResponse:
    """Health check: NO consulta a la STPS (Render lo pega cada minuto)."""
    from . import padron

    est = padron.estado()
    return PlainTextResponse(
        "\n".join(
            [
                "ok",
                f"fuente: {settings.base_url}",
                f"indice: {est['filas']} filas",
                f"import: {est['ultima_importacion'] or 'never'}",
            ]
        )
    )


async def _refresh(request: Request) -> JSONResponse:
    """Reconstruye el índice local descargando el padrón (bearer obligatorio)."""
    from starlette.concurrency import run_in_threadpool

    from . import padron

    logger.info("Refresh del padrón solicitado")
    try:
        result = await run_in_threadpool(padron.importar)
        return JSONResponse(result)
    except padron.ImportError_ as exc:
        logger.error("Refresh falló: %s", exc)
        return JSONResponse({"success": False, "error": str(exc)}, status_code=502)


async def _verificar(request: Request) -> JSONResponse:
    """Consulta del padrón en REST plano, para servidor-a-servidor.

    Existe porque hablar MCP desde un backend es un handshake de sesión completo
    para una pregunta de una línea: MATERIA sólo quiere saber si un RFC tiene
    REPSE vigente. Llama a la MISMA `consultar` que la tool `verificar_repse`,
    sin capa de traducción, para que las dos no se puedan desincronizar.

    Sin gate de quota a propósito: esta ruta exige `MCP_API_KEY`, que sólo
    tenemos nosotros, y esa identidad ya es ilimitada en `quota._TRUSTED_CLIENT_IDS`.
    No abre nada que la key no abriera ya.
    """
    from starlette.concurrency import run_in_threadpool

    from .client import RepseError
    from .consulta import consultar

    termino = (request.query_params.get("rfc") or "").strip()
    if not termino:
        return JSONResponse({"error": "Falta el parámetro `rfc`."}, status_code=400)

    try:
        return JSONResponse(await run_in_threadpool(consultar, termino))
    except RepseError as exc:
        # 502, no 500: el que falló fue el portal de la STPS, no nosotros. Quien
        # llama debe poder distinguir "no pude verificar" de "el proveedor está mal".
        logger.error("Consulta a REPSE falló: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=502)


def _startup_index() -> None:
    """Rebuild-on-boot: reconstruye el índice si está vacío o viejo. Hilo daemon
    para que uvicorn abra el puerto de inmediato (Render free reinicia si no)."""
    from . import padron

    if not settings.fetch_on_startup:
        return
    est = padron.estado()
    stale = True
    if est["ultima_importacion"]:
        edad = datetime.now(UTC) - datetime.fromisoformat(est["ultima_importacion"])
        stale = edad > timedelta(hours=settings.max_edad_horas)
    if est["filas"] > 0 and not stale:
        logger.info("Índice con %d filas y fresco — sin rebuild", est["filas"])
        return
    logger.info("Índice vacío o viejo — reconstruyendo en segundo plano…")
    try:
        result = padron.importar()
        logger.info("Rebuild terminó: %s filas", result.get("filas"))
    except Exception as exc:  # noqa: BLE001 — el servicio degrada a modo vivo
        logger.error("Rebuild del índice falló (las tools en vivo siguen): %s", exc)


async def _oauth_protected_resource_root(request: Request) -> JSONResponse:
    """Metadata OAuth (RFC 9728) en la RAÍZ.

    FastMCP sólo la registra con sufijo; el connector del Claude app la busca en
    la raíz y sin esto da 404 → "authorization failed" (es exactamente el bug
    WE-399 de sat69). Se sirve desde el día uno para no repetirlo.
    """
    return JSONResponse(
        {
            "resource": f"{settings.base_url_public}{MCP_PATH}",
            "authorization_servers": [settings.authkit_domain],
            "scopes_supported": [],
            "bearer_methods_supported": ["header"],
        }
    )


def create_app() -> Starlette:
    from .server import mcp

    mcp_app = mcp.http_app(path=MCP_PATH, transport="http")
    routes = [
        Route("/", _landing, methods=["GET"]),
        Route("/health", _health, methods=["GET"]),
        Route("/refresh", _refresh, methods=["POST"]),
        Route("/verificar", _verificar, methods=["GET"]),
        Route("/verificar-lote", _verificar_lote, methods=["POST"]),
    ]
    if settings.oauth_enabled:
        routes.append(
            Route(
                "/.well-known/oauth-protected-resource",
                _oauth_protected_resource_root,
                methods=["GET"],
            )
        )
    routes.append(Mount("/", app=mcp_app))
    return Starlette(
        routes=routes,
        middleware=[Middleware(BearerAuthMiddleware)],
        lifespan=mcp_app.lifespan,
    )


def main() -> None:
    logging.basicConfig(level=settings.log_level, format="%(asctime)s [%(levelname)s] %(message)s")
    threading.Thread(target=_startup_index, name="startup-index", daemon=True).start()
    uvicorn.run(
        create_app(),
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        timeout_graceful_shutdown=10,
    )


if __name__ == "__main__":
    main()

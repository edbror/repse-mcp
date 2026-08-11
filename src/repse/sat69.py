"""
Cliente servidor-a-servidor hacia sat69-mcp (listas SAT 69/69-B).

Habla MCP-over-HTTP con el FastMCP Client oficial contra el /connect de sat69,
autenticado con su MCP_API_KEY estática (env SAT69_MCP_KEY). Una llamada =
initialize + tools/call verificar_rfc.

Si sat69 no está configurado o no responde, el cruce NO truena: regresa
disponible=False y el veredicto combinado sale INCOMPLETO — nunca se aprueba a
ciegas un lado que no se pudo consultar.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

SAT69_URL = os.getenv("SAT69_MCP_URL", "https://sat69-mcp.onrender.com/connect")
SAT69_KEY = os.getenv("SAT69_MCP_KEY", "").strip()

# El free tier de Render duerme; el primer request puede tardar ~1 min.
TIMEOUT = int(os.getenv("SAT69_TIMEOUT", "90"))


def configurado() -> bool:
    return bool(SAT69_KEY)


async def verificar_rfc(rfc: str) -> dict:
    """Consulta sat69 por un RFC. Devuelve {disponible, riesgo, veredicto, ...}."""
    if not configurado():
        return {
            "disponible": False,
            "error": "SAT69_MCP_KEY no configurada; cruce SAT 69/69-B deshabilitado.",
        }
    try:
        from fastmcp import Client
        from fastmcp.client.auth import BearerAuth

        async with Client(SAT69_URL, auth=BearerAuth(SAT69_KEY), timeout=TIMEOUT) as client:
            result = await client.call_tool("verificar_rfc", {"rfc": rfc})
        payload = _extraer(result)
        return {"disponible": True, **payload}
    except Exception as exc:  # noqa: BLE001 — cualquier falla degrada a INCOMPLETO
        logger.warning("sat69 no disponible para %s: %s", rfc, exc)
        return {"disponible": False, "error": f"sat69-mcp no respondió: {exc}"}


def _extraer(result) -> dict:
    """El tool result de FastMCP trae structured_content o texto JSON."""
    data = getattr(result, "structured_content", None) or getattr(result, "data", None)
    if isinstance(data, dict):
        return data.get("result", data)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"veredicto": text}
    return {}

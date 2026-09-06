"""
Cliente Turso mínimo — SOLO para el contador de quota (ver quota.py).

REPSE consulta el padrón de la STPS EN VIVO y su índice local es efímero, así
que —a diferencia de sat69— aquí Turso no guarda datos de negocio; existe
únicamente como store durable del contador freemium por usuario. Con
TURSO_DATABASE_URL + TURSO_AUTH_TOKEN se habilita; si faltan, el gate falla
abierto (ver quota.py).
"""

from __future__ import annotations

import logging

from .config import settings

logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    for prefix in ("libsql://", "wss://"):
        if url.startswith(prefix):
            return "https://" + url[len(prefix) :]
    return url


def _client():
    if not settings.turso_enabled:
        return None
    try:
        import libsql_client

        return libsql_client.create_client_sync(
            url=_normalize_url(settings.turso_url), auth_token=settings.turso_token
        )
    except ImportError:
        logger.error("libsql-client no instalado — pip install libsql-client")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo conectar a Turso: %s", exc)
        return None

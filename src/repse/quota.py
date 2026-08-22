"""
Quota diaria por usuario (freemium) para REPSE.

El contador vive en Turso (durable, compartido entre instancias y redeploys).
Un usuario —identificado por el `sub` de su token OAuth, o su `client_id`—
tiene `settings.free_daily_limit` consultas gratis por día (zona CDMX). La key
estática servidor-a-servidor de WATR y los IDs en `settings.paid_user_ids` son
ilimitados.

Diseño defensivo (FALLA-ABIERTO): si no hay identidad, Turso está apagado, o
algo truena, se PERMITE la consulta. Un gate de cobro nunca debe tumbar la
herramienta; preferimos regalar una consulta a romper el servicio.
"""
from __future__ import annotations

import datetime as _dt
import logging

from . import turso
from .config import settings

logger = logging.getLogger(__name__)

# Key servidor-a-servidor de WATR (ver DualVerifier en server.py): ilimitada.
_TRUSTED_CLIENT_IDS = frozenset({"watr-static-key"})

# ponytail: la tabla se crea una vez por proceso; evita un round-trip a Turso
# por consulta. En un proceso nuevo se vuelve a asegurar (idempotente).
_ensured = False


def _dia_cdmx() -> str:
    """Día actual en CDMX (UTC-6, sin horario de verano desde 2022) → el límite
    se reinicia a medianoche local, no a las 18:00."""
    return (_dt.datetime.now(_dt.UTC) - _dt.timedelta(hours=6)).strftime("%Y-%m-%d")


def user_id(token) -> str | None:
    """Identidad estable del token: `sub` del claim (por-usuario) o `client_id`."""
    if token is None:
        return None
    claims = getattr(token, "claims", None) or {}
    return claims.get("sub") or getattr(token, "client_id", None)


def _ilimitado(uid: str) -> bool:
    return uid in _TRUSTED_CLIENT_IDS or uid in settings.paid_user_ids


def check(token) -> dict | None:
    """Registra una consulta y aplica el límite freemium.

    Devuelve None si la consulta está permitida (y ya la contó); o un dict de
    error si el usuario alcanzó su límite gratis del día. Falla-abierto.
    """
    global _ensured

    uid = user_id(token)
    if not uid or _ilimitado(uid) or not settings.turso_enabled:
        return None

    # ponytail: abre un client Turso por consulta (create_client_sync). Simple y
    # suficiente para el volumen freemium; poolear si el tráfico sube.
    client = turso._client()
    if client is None:
        return None  # falla-abierto: sin store durable no forzamos

    dia = _dia_cdmx()
    try:
        if not _ensured:
            client.execute(
                "CREATE TABLE IF NOT EXISTS uso_diario ("
                " user_id TEXT NOT NULL, dia TEXT NOT NULL,"
                " n INTEGER NOT NULL DEFAULT 0,"
                " PRIMARY KEY (user_id, dia))"
            )
            _ensured = True
        res = client.execute(
            "INSERT INTO uso_diario (user_id, dia, n) VALUES (?, ?, 1)"
            " ON CONFLICT(user_id, dia) DO UPDATE SET n = n + 1"
            " RETURNING n",
            [uid, dia],
        )
        n = int(res.rows[0][0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("quota.check falló (falla-abierto): %s", exc)
        return None
    finally:
        client.close()

    limite = settings.free_daily_limit
    if n > limite:
        return {
            "error": "limite_gratis_alcanzado",
            "mensaje": (
                f"Alcanzaste tu límite gratis de {limite} consulta(s) por día. "
                "Para acceso ilimitado, suscríbete o escríbenos en "
                "https://repse.watr.mx"
            ),
            "consultas_hoy": n,
            "limite_gratis": limite,
        }
    return None

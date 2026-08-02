"""
Cliente HTTP del padrón público REPSE (STPS).

Hallazgo que define la arquitectura: el portal NO exige scraping de HTML. Su
bundle JS (`build/assets/sourceInicio-*.js`) llama a dos endpoints JSON, ambos
sin autenticación:

    GET  /busca_razon_social?term=…   → [{id, text}]  (RFC, folio o razón social)
    POST /buscar-padron  razon_social=<id>            → detalle + actividades

`buscar-padron` es POST de Laravel: exige cookie de sesión + X-CSRF-TOKEN, que
se toman del `<meta name="csrf-token">` del home. El token se cachea y se
renueva solo si la STPS responde 419 (token expirado).
"""

from __future__ import annotations

import logging
import re
import threading

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_CSRF_RE = re.compile(r'name="csrf-token"\s+content="([^"]+)"')

# El portal responde 419 cuando la sesión/token caducó. Es el único caso en el
# que vale la pena reintentar: cualquier otro error es real.
_CSRF_EXPIRED = 419


class RepseError(RuntimeError):
    """Falla al hablar con el portal de la STPS."""


class RepseClient:
    """Cliente síncrono y reutilizable. Mantiene cookie de sesión y token CSRF."""

    def __init__(self, timeout: int | None = None) -> None:
        self._client = httpx.Client(
            timeout=timeout or settings.http_timeout,
            follow_redirects=True,
            verify=settings.verify_tls,
            proxy=settings.fetch_proxy or None,
            headers={
                # El portal es público; identificarse es lo correcto y evita que
                # nos confundan con un bot anónimo si algún día filtran por UA.
                "User-Agent": "repse-mcp/0.1 (+https://repse.watr.mx) WATR compliance tooling",
                "Accept": "application/json, text/plain, */*",
            },
        )
        self._csrf: str | None = None
        self._lock = threading.Lock()

    # -- CSRF ---------------------------------------------------------------

    def _fetch_csrf(self) -> str:
        """Trae el home para sembrar la cookie de sesión y extraer el token."""
        try:
            resp = self._client.get(settings.url("/"))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RepseError(f"No se pudo abrir el portal REPSE: {exc}") from exc
        match = _CSRF_RE.search(resp.text)
        if not match:
            raise RepseError("El portal REPSE no expuso csrf-token — probablemente cambió el HTML.")
        return match.group(1)

    def _csrf_token(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._csrf:
                self._csrf = self._fetch_csrf()
            return self._csrf

    # -- Endpoints ----------------------------------------------------------

    def buscar(self, termino: str) -> list[dict]:
        """Typeahead del padrón. Acepta RFC, folio de registro o razón social.

        Devuelve [{"id": int, "text": str}]. Lista vacía = sin coincidencias.
        """
        termino = (termino or "").strip()
        if not termino:
            return []
        try:
            resp = self._client.get(settings.url(settings.path_buscar), params={"term": termino})
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise RepseError(f"Búsqueda en REPSE falló: {exc}") from exc
        except ValueError as exc:
            raise RepseError("REPSE devolvió una respuesta no-JSON en la búsqueda.") from exc
        return payload.get("results") or []

    def detalle(self, registro_id: int | str) -> dict:
        """Detalle del registro por el id interno que devuelve `buscar`.

        Devuelve el payload crudo de la STPS:
            {"registro": 1, "data": {...}, "actividades": [{"descripcion", "folio"}]}
        """
        data = {"razon_social": str(registro_id)}

        def _post(token: str) -> httpx.Response:
            return self._client.post(
                settings.url(settings.path_detalle),
                data=data,
                headers={"X-CSRF-TOKEN": token, "X-Requested-With": "XMLHttpRequest"},
            )

        try:
            resp = _post(self._csrf_token())
            if resp.status_code == _CSRF_EXPIRED:
                logger.info("CSRF expirado (419) — renovando token y reintentando")
                resp = _post(self._csrf_token(force=True))
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise RepseError(f"Consulta de detalle en REPSE falló: {exc}") from exc
        except ValueError as exc:
            raise RepseError("REPSE devolvió una respuesta no-JSON en el detalle.") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RepseClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


_default: RepseClient | None = None
_default_lock = threading.Lock()


def get_client() -> RepseClient:
    """Cliente compartido a nivel proceso (reusa cookie de sesión y token)."""
    global _default
    with _default_lock:
        if _default is None:
            _default = RepseClient()
        return _default

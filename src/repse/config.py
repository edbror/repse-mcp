"""
Configuración centralizada del MCP de REPSE.

Toda lectura de variables de entorno vive aquí. Mismo patrón que sat69-mcp,
menos la mitad: REPSE no necesita base de datos ni Turso porque el portal de la
STPS expone JSON en vivo (ver client.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Portal público del REPSE. Overrideable por env: la STPS ya movió rutas antes
# (la `/Publico` que cita la spec original hoy da 404) y el equivalente en
# sat69 —la URL congelada del 69-B— nos costó un mes de datos viejos.
BASE_URL = os.getenv("REPSE_BASE_URL", "https://repse.stps.gob.mx/")

# Endpoints descubiertos en el bundle JS del portal (sourceInicio-*.js):
#   GET  busca_razon_social?term=…  → typeahead: acepta RFC, folio o razón social
#   POST buscar-padron  (razon_social=<id>)  → detalle + actividades autorizadas
PATH_BUSCAR = os.getenv("REPSE_PATH_BUSCAR", "busca_razon_social")
PATH_DETALLE = os.getenv("REPSE_PATH_DETALLE", "buscar-padron")
# Descarga del padrón completo (.xlsx, ~26 MB, ~155k filas). Ruta no enlazada
# en el home; descubierta vía índice de buscadores. Overrideable por env.
PATH_PADRON_XLSX = os.getenv("REPSE_PATH_PADRON_XLSX", "padron-public-excel")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Snapshot inmutable de la configuración derivada del entorno."""

    # --- Fuente ---
    base_url: str = BASE_URL
    path_buscar: str = PATH_BUSCAR
    path_detalle: str = PATH_DETALLE
    path_padron_xlsx: str = PATH_PADRON_XLSX
    http_timeout: int = _env_int("HTTP_TIMEOUT", 30)
    download_timeout: int = _env_int("DOWNLOAD_TIMEOUT", 300)

    # --- Índice local (SQLite; efímero /tmp en Render, rebuild-on-boot) ---
    db_path: Path = Path(os.getenv("DB_PATH", str(_REPO_ROOT / "data" / "repse.db")))
    fetch_on_startup: bool = _env_bool("FETCH_ON_STARTUP", True)
    # Guard de frescura: el corte real trae ~155k filas; menos de esto = fuente rota.
    min_filas: int = _env_int("MIN_FILAS", 100_000)
    # Índice más viejo que esto (horas) dispara rebuild al boot.
    max_edad_horas: int = _env_int("MAX_EDAD_HORAS", 26)
    # Cortesía con un portal de gobierno: tope de concurrencia en lote.
    batch_concurrency: int = _env_int("BATCH_CONCURRENCY", 4)
    # Días antes del vencimiento en que un registro se marca POR_VENCER.
    dias_alerta: int = _env_int("DIAS_ALERTA", 60)

    # Proxy opcional de salida (paridad con sat69; la STPS no bloqueó datacenter
    # en pruebas, se deja por si geo/rate-limita).
    fetch_proxy: str = os.getenv("FETCH_PROXY", "").strip()

    # --- Centinela (cribado contra 38 listas restrictivas) ---
    # Sin llave NO se deshabilita el cruce: Centinela tiene carril anónimo con
    # razonador determinista y 10 consultas por minuto. La llave solo cambia el
    # carril y el límite. Ver centinela.py.
    centinela_url: str = os.getenv(
        "CENTINELA_API_URL", "https://centinela-api-op1b.onrender.com"
    ).rstrip("/")
    centinela_key: str = os.getenv("CENTINELA_API_KEY", "").strip()
    centinela_timeout: int = _env_int("CENTINELA_TIMEOUT", 60)

    # --- HTTP / despliegue ---
    mcp_api_key: str = os.getenv("MCP_API_KEY", "").strip()
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _env_int("PORT", 8080)

    # --- OAuth (WorkOS AuthKit) ---
    authkit_domain: str = os.getenv("AUTHKIT_DOMAIN", "").strip()
    base_url_public: str = (os.getenv("BASE_URL") or os.getenv("MCP_BASE_URL") or "").strip()

    # --- Turso (SOLO para el contador de quota; ver turso.py / quota.py) ---
    turso_url: str = os.getenv("TURSO_DATABASE_URL", "").strip()
    turso_token: str = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    # --- Freemium / quota (límite diario por usuario) ---
    free_daily_limit: int = _env_int("REPSE_FREE_DAILY_LIMIT", 1)
    paid_user_ids: frozenset[str] = frozenset(
        x.strip() for x in os.getenv("REPSE_PAID_USER_IDS", "").split(",") if x.strip()
    )

    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    verify_tls: bool = _env_bool("VERIFY_TLS", True)

    @property
    def oauth_enabled(self) -> bool:
        return bool(self.authkit_domain and self.base_url_public)

    @property
    def turso_enabled(self) -> bool:
        return bool(self.turso_url)

    def url(self, path: str) -> str:
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")

    @property
    def url_padron(self) -> str:
        return self.url(self.path_padron_xlsx)


settings = Settings()

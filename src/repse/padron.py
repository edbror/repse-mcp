"""
Índice local del padrón REPSE — descarga del xlsx público + SQLite/FTS5.

Fuente: GET /padron-public-excel (ruta descubierta vía índice de buscadores; no
está enlazada en el HTML del home). ~26 MB, una hoja, ~155k filas con strings
INLINE (por eso el parser lee <is><t>, no sharedStrings). Columnas:

    Folio | Razón Social | Estado | Municipio | Vigencia (YYYY-MM-DD) | Actividades

El xlsx NO trae RFC — la verificación por RFC sigue siendo en vivo (consulta.py).
Este índice existe para lo que el typeahead no puede dar: búsqueda masiva con
paginación (el vivo tapa en 30) y ventanas de vencimiento.

Sin Turso a propósito: la fuente es un solo archivo público que parsea en
segundos, así que el índice se reconstruye al boot (rebuild-on-boot). Si la
STPS llegara a bloquear descargas desde datacenter, el fallback es Turso
sembrado desde GitHub Actions (patrón sat69).
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
import threading
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .config import settings

logger = logging.getLogger(__name__)

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COLUMNAS = ("folio", "razon_social", "entidad", "municipio", "vigencia", "actividades")

_write_lock = threading.Lock()


class ImportError_(RuntimeError):
    """Falla de descarga, parseo o guard de frescura del padrón."""


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = _connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS padron (
            folio        INTEGER PRIMARY KEY,
            razon_social TEXT NOT NULL,
            entidad      TEXT,
            municipio    TEXT,
            vigencia     TEXT,          -- YYYY-MM-DD (orden lexicográfico = cronológico)
            actividades  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_padron_vigencia ON padron(vigencia);
        CREATE INDEX IF NOT EXISTS idx_padron_entidad  ON padron(entidad);
        CREATE VIRTUAL TABLE IF NOT EXISTS padron_fts USING fts5(
            razon_social, actividades, content='padron', content_rowid='folio'
        );
        CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
        """
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Parser del xlsx (stdlib puro)
# ---------------------------------------------------------------------------


def parse_xlsx(path: Path):
    """Itera filas del padrón como tuplas (folio, razón, entidad, mpio, vigencia, acts).

    Streaming con iterparse: nunca materializa las 155k filas. Salta el
    encabezado y cualquier fila sin folio numérico.
    """
    with zipfile.ZipFile(path) as z, z.open("xl/worksheets/sheet1.xml") as sheet:
        for _, el in ET.iterparse(sheet):
            if el.tag != _NS + "row":
                continue
            vals: list[str] = []
            for c in el:
                t = c.find(_NS + "is/" + _NS + "t")  # inline string
                if t is None:
                    t = c.find(_NS + "v")  # numérico, por si la STPS cambia
                vals.append((t.text or "").strip() if t is not None else "")
            el.clear()
            vals += [""] * (6 - len(vals))
            try:
                folio = int(vals[0])
            except ValueError:
                continue  # encabezado o basura
            yield (folio, vals[1], vals[2], vals[3], vals[4], vals[5])


def descargar_xlsx(destino: Path) -> None:
    """Descarga el padrón en streaming (26 MB) al archivo destino."""
    url = settings.url_padron
    logger.info("Descargando padrón: %s", url)
    try:
        with (
            httpx.Client(
                timeout=settings.download_timeout,
                follow_redirects=True,
                verify=settings.verify_tls,
                proxy=settings.fetch_proxy or None,
                headers={"User-Agent": "repse-mcp/0.1 (+https://repse.watr.mx)"},
            ) as client,
            client.stream("GET", url) as resp,
        ):
            resp.raise_for_status()
            with destino.open("wb") as f:
                for chunk in resp.iter_bytes(1 << 16):
                    f.write(chunk)
    except httpx.HTTPError as exc:
        raise ImportError_(f"Descarga del padrón falló: {exc}") from exc


# ---------------------------------------------------------------------------
# Importación
# ---------------------------------------------------------------------------


def _max_vigencia(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(vigencia) AS m FROM padron").fetchone()
    return row["m"] if row else None


def importar(db_path: Path | None = None, xlsx_path: Path | None = None) -> dict:
    """Descarga (o usa xlsx_path) e importa el padrón completo. Atómico.

    Guard de frescura — lección sat69 (la URL congelada del 69-B daba 200 con
    datos viejos y el cron pasaba verde):
      1. filas >= MIN_FILAS (default 100k; el corte real trae ~155k), y
      2. max(vigencia) no retrocede respecto al import anterior.
    Cualquier violación aborta SIN tocar el índice existente.
    """
    with _write_lock:
        conn = init_db(db_path)
        try:
            if xlsx_path is None:
                tmp = Path(tempfile.mkstemp(suffix=".xlsx")[1])
                try:
                    descargar_xlsx(tmp)
                    return _importar_archivo(conn, tmp)
                finally:
                    tmp.unlink(missing_ok=True)
            return _importar_archivo(conn, xlsx_path)
        finally:
            conn.close()


def _importar_archivo(conn: sqlite3.Connection, xlsx: Path) -> dict:
    previo_max = _max_vigencia(conn)

    conn.execute("DROP TABLE IF EXISTS padron_nuevo")
    conn.execute(
        "CREATE TABLE padron_nuevo (folio INTEGER PRIMARY KEY, razon_social TEXT NOT NULL, "
        "entidad TEXT, municipio TEXT, vigencia TEXT, actividades TEXT)"
    )
    filas = 0
    lote: list[tuple] = []
    for row in parse_xlsx(xlsx):
        lote.append(row)
        if len(lote) >= 5000:  # lotes chicos: lección WE-390 (OOM en 512Mi)
            conn.executemany("INSERT OR REPLACE INTO padron_nuevo VALUES (?,?,?,?,?,?)", lote)
            filas += len(lote)
            lote.clear()
    if lote:
        conn.executemany("INSERT OR REPLACE INTO padron_nuevo VALUES (?,?,?,?,?,?)", lote)
        filas += len(lote)

    # Guard 1: tamaño mínimo.
    if filas < settings.min_filas:
        conn.execute("DROP TABLE padron_nuevo")
        conn.commit()
        raise ImportError_(
            f"El padrón descargado trae {filas} filas (< {settings.min_filas}). "
            "Fuente sospechosa de estar rota o truncada; se conserva el índice anterior."
        )
    # Guard 2: la vigencia máxima no retrocede.
    nuevo_max = conn.execute("SELECT MAX(vigencia) AS m FROM padron_nuevo").fetchone()["m"]
    if previo_max and nuevo_max and nuevo_max < previo_max:
        conn.execute("DROP TABLE padron_nuevo")
        conn.commit()
        raise ImportError_(
            f"max(vigencia) retrocedió ({previo_max} → {nuevo_max}): la fuente parece "
            "estar sirviendo un corte viejo. Se conserva el índice anterior."
        )

    # Swap atómico + reconstrucción del FTS.
    conn.executescript(
        """
        BEGIN;
        DELETE FROM padron;
        INSERT INTO padron SELECT * FROM padron_nuevo;
        DROP TABLE padron_nuevo;
        INSERT INTO padron_fts(padron_fts) VALUES('delete-all');
        INSERT INTO padron_fts(rowid, razon_social, actividades)
            SELECT folio, razon_social, actividades FROM padron;
        COMMIT;
        """
    )
    ahora = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES ('ultima_importacion', ?), ('filas', ?)",
        (ahora, str(filas)),
    )
    conn.commit()
    logger.info("Padrón importado: %d filas (max vigencia %s)", filas, nuevo_max)
    return {"success": True, "filas": filas, "max_vigencia": nuevo_max, "importado": ahora}


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def _fts_query(texto: str) -> str:
    """Texto libre → query FTS5 segura: tokens entre comillas con AND implícito."""
    tokens = [t.replace('"', "") for t in texto.split() if t.strip('"')]
    return " ".join(f'"{t}"' for t in tokens)


def estado(db_path: Path | None = None) -> dict:
    conn = init_db(db_path)
    try:
        meta = {r["clave"]: r["valor"] for r in conn.execute("SELECT * FROM meta")}
        total = conn.execute("SELECT COUNT(*) AS c FROM padron").fetchone()["c"]
        return {
            "filas": total,
            "ultima_importacion": meta.get("ultima_importacion"),
            "max_vigencia": _max_vigencia(conn),
        }
    finally:
        conn.close()


def buscar(
    texto: str,
    entidad: str | None = None,
    limite: int = 20,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict]:
    """Búsqueda FTS por razón social / actividades, con filtro de entidad y paginación."""
    conn = init_db(db_path)
    try:
        query = _fts_query(texto)
        if not query:
            return []
        sql = (
            "SELECT p.* FROM padron_fts f JOIN padron p ON p.folio = f.rowid "
            "WHERE padron_fts MATCH ?"
        )
        params: list = [query]
        if entidad:
            sql += " AND p.entidad LIKE ?"
            params.append(f"%{entidad}%")
        sql += " ORDER BY rank LIMIT ? OFFSET ?"
        params += [max(1, min(limite, 100)), max(0, offset)]
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def por_vencer(
    dias: int = 60,
    entidad: str | None = None,
    limite: int = 50,
    db_path: Path | None = None,
) -> list[dict]:
    """Registros cuya vigencia cae dentro de la ventana [hoy, hoy+dias]."""
    from datetime import date, timedelta

    hoy = date.today().isoformat()
    tope = (date.today() + timedelta(days=max(0, dias))).isoformat()
    conn = init_db(db_path)
    try:
        sql = "SELECT * FROM padron WHERE vigencia >= ? AND vigencia <= ?"
        params: list = [hoy, tope]
        if entidad:
            sql += " AND entidad LIKE ?"
            params.append(f"%{entidad}%")
        sql += " ORDER BY vigencia LIMIT ?"
        params.append(max(1, min(limite, 200)))
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()

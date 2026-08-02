"""Índice local: parser del xlsx, guards de frescura, FTS y por_vencer."""

from __future__ import annotations

import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from repse import padron

# --- xlsx sintético (mismo formato que sirve la STPS: inline strings) --------

_SHEET_TMPL = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>{rows}</sheetData></worksheet>"""

_HEADER = ("Folio", "Razón Social", "Estado", "Municipio", "Vigencia", "Actividades")


def _row(vals) -> str:
    cells = "".join(f'<c t="inlineStr"><is><t>{v}</t></is></c>' for v in vals)
    return f"<row>{cells}</row>"


def make_xlsx(path: Path, rows: list[tuple]) -> Path:
    sheet = _SHEET_TMPL.format(rows="".join(_row(r) for r in [_HEADER, *rows]))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
    return path


FILAS = [
    (
        "100",
        "LIMPIEZA TOTAL SA DE CV",
        "Jalisco",
        "Guadalajara",
        "2027-05-01",
        "Limpieza industrial de plantas",
    ),
    (
        "200",
        "VIGILANCIA AZTECA SA DE CV",
        "Ciudad de México",
        "Benito Juárez",
        "2024-01-15",
        "Servicios de vigilancia y seguridad privada",
    ),
    (
        "300",
        "SOFTWARE ANDINO SC",
        "Jalisco",
        "Zapopan",
        (date.today() + timedelta(days=30)).isoformat(),
        "Desarrollo de software a la medida",
    ),
]


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB temporal + import del xlsx sintético (guard de tamaño relajado)."""
    monkeypatch.setattr(padron, "settings", replace(padron.settings, min_filas=3))
    db_path = tmp_path / "test.db"
    xlsx = make_xlsx(tmp_path / "padron.xlsx", FILAS)
    result = padron.importar(db_path=db_path, xlsx_path=xlsx)
    assert result["success"] and result["filas"] == 3
    return db_path


def test_parse_xlsx_salta_encabezado(tmp_path):
    xlsx = make_xlsx(tmp_path / "p.xlsx", FILAS)
    rows = list(padron.parse_xlsx(xlsx))
    assert len(rows) == 3
    assert rows[0] == (
        100,
        "LIMPIEZA TOTAL SA DE CV",
        "Jalisco",
        "Guadalajara",
        "2027-05-01",
        "Limpieza industrial de plantas",
    )


def test_guard_tamano_minimo(tmp_path, monkeypatch):
    monkeypatch.setattr(padron, "settings", replace(padron.settings, min_filas=100))
    xlsx = make_xlsx(tmp_path / "p.xlsx", FILAS)  # sólo 3 filas
    with pytest.raises(padron.ImportError_, match="filas"):
        padron.importar(db_path=tmp_path / "t.db", xlsx_path=xlsx)


def test_guard_vigencia_no_retrocede(tmp_path, monkeypatch, db):
    # Re-import con corte "viejo" (max vigencia menor) → aborta y conserva datos.
    monkeypatch.setattr(padron, "settings", replace(padron.settings, min_filas=1))
    viejo = make_xlsx(
        tmp_path / "viejo.xlsx",
        [("999", "EMPRESA VIEJA SA", "Sonora", "Hermosillo", "2023-01-01", "X")],
    )
    with pytest.raises(padron.ImportError_, match="retrocedió"):
        padron.importar(db_path=db, xlsx_path=viejo)
    assert padron.estado(db_path=db)["filas"] == 3  # índice intacto


def test_fts_busca_por_actividad_y_filtra_entidad(db):
    hits = padron.buscar("limpieza", db_path=db)
    assert [h["folio"] for h in hits] == [100]
    # filtro por entidad que no corresponde → vacío
    assert padron.buscar("limpieza", entidad="Sonora", db_path=db) == []
    # multi-token = AND implícito
    assert padron.buscar("desarrollo software", db_path=db)[0]["folio"] == 300


def test_por_vencer_ventana(db):
    proximos = padron.por_vencer(dias=60, db_path=db)
    assert [p["folio"] for p in proximos] == [300]  # vence en 30 días
    # el vencido (2024) y el lejano (2027) quedan fuera
    assert padron.por_vencer(dias=60, entidad="Sonora", db_path=db) == []


def test_reimport_es_idempotente(db, tmp_path, monkeypatch):
    monkeypatch.setattr(padron, "settings", replace(padron.settings, min_filas=3))
    xlsx = make_xlsx(tmp_path / "otra.xlsx", FILAS)
    r = padron.importar(db_path=db, xlsx_path=xlsx)
    assert r["filas"] == 3
    assert padron.estado(db_path=db)["filas"] == 3

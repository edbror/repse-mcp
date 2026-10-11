"""Celdas vacías omitidas por el xlsx (WE-1039).

El xlsx no escribe las celdas vacías. El parser apilaba por orden de aparición,
así que una fila sin Vigencia recorría todo a la izquierda y metía las
Actividades en esa columna. 28 de las 157,983 filas del corte del 10-oct caían
ahí, y como `MAX(vigencia)` es lexicográfico —el texto ordena arriba de
"2028-…"— el guard de frescura comparaba dos cadenas de actividades distintas,
lo leía como regresión y tumbaba el refresh diario de forma intermitente.

El archivo real sí trae el atributo `r` en cada celda (`A2311`, `B2311`, …,
`F2311`), que es justo el dato que dice a qué columna pertenece cada valor.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from repse import padron

_SHEET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>{rows}</sheetData></worksheet>"""

ACTIVIDAD = "OTROS TRABAJOS DE ACABADOS EN EDIFICACIONES"


def _fila(n: int, celdas: dict[str, str]) -> str:
    """Fila con referencias reales. `celdas` va por letra; lo que no esté, se
    omite — exactamente como lo serializa la STPS."""
    cs = "".join(
        f'<c r="{col}{n}" t="inlineStr"><is><t>{v}</t></is></c>' for col, v in celdas.items()
    )
    return f'<row r="{n}">{cs}</row>'


def _xlsx(path: Path, filas: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", _SHEET.format(rows="".join(filas)))
    return path


def test_fila_sin_vigencia_no_corre_las_actividades(tmp_path):
    # Caso real: folio 294754, refs [A, B, C, D, F] — falta la E.
    ruta = _xlsx(
        tmp_path / "p.xlsx",
        [
            _fila(
                1,
                {
                    "A": "Folio",
                    "B": "Razón Social",
                    "C": "Estado",
                    "D": "Municipio",
                    "E": "Vigencia",
                    "F": "Actividades",
                },
            ),
            _fila(
                2,
                {"A": "294754", "B": "ACABADOS SA", "C": "Jalisco", "D": "Zapopan", "F": ACTIVIDAD},
            ),
        ],
    )
    ((folio, razon, entidad, mpio, vigencia, acts),) = list(padron.parse_xlsx(ruta))

    assert folio == 294754 and razon == "ACABADOS SA"
    assert entidad == "Jalisco" and mpio == "Zapopan"
    assert vigencia == "", f"las actividades se colaron a vigencia: {vigencia!r}"
    assert acts == ACTIVIDAD


def test_fila_sin_actividades_conserva_la_vigencia(tmp_path):
    # El otro caso real: folio 49003, refs [A, B, C, D, E] — falta la F.
    ruta = _xlsx(
        tmp_path / "p.xlsx",
        [
            _fila(1, {"A": "Folio", "B": "RS", "C": "E", "D": "M", "E": "V", "F": "A"}),
            _fila(
                2,
                {
                    "A": "49003",
                    "B": "SIN ACTS SA",
                    "C": "Nuevo León",
                    "D": "Monterrey",
                    "E": "2027-10-10",
                },
            ),
        ],
    )
    ((_, _, _, _, vigencia, acts),) = list(padron.parse_xlsx(ruta))
    assert vigencia == "2027-10-10"
    assert acts == ""


def test_sin_atributo_r_sigue_funcionando_por_posicion(tmp_path):
    # Respaldo: un writer que omita `r` debe seguir parseando como antes.
    celdas = "".join(
        f'<c t="inlineStr"><is><t>{v}</t></is></c>'
        for v in ("777", "POSICIONAL SA", "Puebla", "Puebla", "2029-01-15", "LIMPIEZA")
    )
    ruta = _xlsx(tmp_path / "p.xlsx", [f"<row>{celdas}</row>"])
    ((folio, razon, _, _, vigencia, acts),) = list(padron.parse_xlsx(ruta))
    assert folio == 777 and razon == "POSICIONAL SA"
    assert vigencia == "2029-01-15" and acts == "LIMPIEZA"


def test_el_guard_ignora_una_vigencia_que_no_es_fecha(tmp_path):
    """Defensa en profundidad: una fila con basura no debe mover el máximo."""
    conn = padron.init_db(tmp_path / "x.db")
    conn.executemany(
        "INSERT INTO padron (folio, razon_social, vigencia) VALUES (?, ?, ?)",
        [(1, "A", "2027-01-01"), (2, "B", ACTIVIDAD), (3, "C", "2028-06-30")],
    )
    conn.commit()
    try:
        assert padron._max_vigencia(conn) == "2028-06-30"
    finally:
        conn.close()

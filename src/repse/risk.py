"""
Normalización de RFC y veredicto determinista de vigencia REPSE.

El veredicto NO usa IA: es aritmética de fechas sobre lo que responde la STPS.

Trampa central, verificada contra el portal (2026-08-01): el campo `registro`
que devuelve `buscar-padron` vale 1 para registros **ya vencidos** — significa
"lo encontré en el padrón", no "está vigente". Ejemplo real: ASE100712TT2
regresa registro=1 con fecha_vencimiento_registro=2024-09-10. Quien lea
`registro` como vigencia aprueba proveedores vencidos; por eso la vigencia se
calcula aquí, contra la fecha de vencimiento.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .config import settings

_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

# Estados posibles del veredicto.
VIGENTE = "VIGENTE"
POR_VENCER = "POR_VENCER"
VENCIDO = "VENCIDO"
SIN_REGISTRO = "SIN_REGISTRO"
INDETERMINADO = "INDETERMINADO"


def normalizar_rfc(rfc: str) -> str:
    """Mayúsculas, sin espacios ni guiones."""
    return re.sub(r"[^A-Za-z0-9&Ññ]", "", (rfc or "").strip()).upper()


def rfc_valido(rfc: str) -> bool:
    """Valida la forma básica de un RFC (moral 12, física 13)."""
    return bool(_RFC_RE.match(rfc))


def parse_fecha(valor: str | None) -> date | None:
    """La STPS manda 'YYYY-MM-DD HH:MM:SS' o None. Cualquier basura → None."""
    if not valor:
        return None
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def evaluar(payload: dict, hoy: date | None = None) -> dict:
    """Convierte la respuesta cruda de la STPS en un veredicto normalizado.

    Devuelve {estado, vigente, veredicto, dias_restantes, fecha_vencimiento}.
    `vigente` es el booleano que debe gobernar un bloqueo de pago o alta.
    """
    hoy = hoy or date.today()

    if not payload or int(payload.get("registro") or 0) != 1:
        return {
            "estado": SIN_REGISTRO,
            "vigente": False,
            "veredicto": (
                "No aparece en el Padrón Público de Contratistas de Servicios "
                "Especializados u Obras Especializadas. No puede prestar servicios "
                "especializados ni facturarlos como tales."
            ),
            "dias_restantes": None,
            "fecha_vencimiento": None,
        }

    data = payload.get("data") or {}
    vence = parse_fecha(data.get("fecha_vencimiento_registro"))

    if vence is None:
        return {
            "estado": INDETERMINADO,
            "vigente": False,
            "veredicto": (
                "Aparece en el padrón pero la STPS no publicó fecha de vencimiento. "
                "No se puede afirmar vigencia; confirma en el portal antes de contratar."
            ),
            "dias_restantes": None,
            "fecha_vencimiento": None,
        }

    dias = (vence - hoy).days
    iso = vence.isoformat()

    if dias < 0:
        return {
            "estado": VENCIDO,
            "vigente": False,
            "veredicto": (
                f"Registro VENCIDO desde el {iso} ({abs(dias)} día(s)). El registro REPSE "
                "dura 3 años y exige declaración cuatrimestral; sin vigencia, el "
                "contratante pierde la deducción de IVA/ISR y asume responsabilidad "
                "solidaria. No contratar ni pagar como servicio especializado."
            ),
            "dias_restantes": dias,
            "fecha_vencimiento": iso,
        }

    if dias <= settings.dias_alerta:
        return {
            "estado": POR_VENCER,
            "vigente": True,
            "veredicto": (
                f"Vigente, pero vence el {iso} (faltan {dias} día(s)). Pide la "
                "renovación antes de firmar contratos que rebasen esa fecha."
            ),
            "dias_restantes": dias,
            "fecha_vencimiento": iso,
        }

    return {
        "estado": VIGENTE,
        "vigente": True,
        "veredicto": f"Registro VIGENTE hasta el {iso} (faltan {dias} día(s)).",
        "dias_restantes": dias,
        "fecha_vencimiento": iso,
    }


def normalizar(payload: dict, hoy: date | None = None) -> dict:
    """Registro completo y plano: identidad + veredicto + actividades."""
    data = (payload or {}).get("data") or {}
    veredicto = evaluar(payload, hoy)
    return {
        **veredicto,
        "rfc": (data.get("rfc") or "").upper() or None,
        "razon_social": data.get("razon_social"),
        "folio": data.get("folio"),
        "entidad": data.get("entidad"),
        "municipio": data.get("municipio"),
        "fecha_registro": data.get("fecha_registro"),
        "actividades": [
            a.get("descripcion", "").strip()
            for a in (payload or {}).get("actividades") or []
            if a.get("descripcion")
        ],
        "fuente": settings.base_url,
    }

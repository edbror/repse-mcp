"""
Resolución de una consulta REPSE: término libre → registro normalizado.

El typeahead de la STPS sólo devuelve `{id, razón social}` — nunca el RFC. Así
que cuando la consulta es por RFC hay que abrir el detalle para confirmar que
el RFC coincide: el typeahead hace match parcial y puede regresar homónimos o
empresas del mismo grupo. Aprobar al primer resultado sin verificar es cómo se
autoriza al proveedor equivocado.
"""

from __future__ import annotations

import logging

from .client import RepseClient, get_client
from .risk import SIN_REGISTRO, normalizar, normalizar_rfc, rfc_valido

logger = logging.getLogger(__name__)

# Tope de detalles a abrir cuando el typeahead regresa varios candidatos.
# Con RFC exacto la STPS regresa 1; el tope sólo acota búsquedas ambiguas.
MAX_CANDIDATOS = 5


def _sin_registro(termino: str, motivo: str) -> dict:
    return {
        "consulta": termino,
        "encontrado": False,
        "estado": SIN_REGISTRO,
        "vigente": False,
        "veredicto": motivo,
        "candidatos": [],
    }


def consultar(termino: str, client: RepseClient | None = None) -> dict:
    """Consulta el padrón por RFC, folio de registro o razón social."""
    termino = (termino or "").strip()
    if not termino:
        return _sin_registro(termino, "Consulta vacía: proporciona RFC, folio o razón social.")

    client = client or get_client()
    rfc = normalizar_rfc(termino)
    es_rfc = rfc_valido(rfc)
    busqueda = rfc if es_rfc else termino

    resultados = client.buscar(busqueda)
    if not resultados:
        return _sin_registro(
            termino,
            f"'{termino}' no aparece en el Padrón Público de Contratistas de la STPS. "
            "Sin registro REPSE no puede prestar ni facturar servicios especializados.",
        )

    candidatos = resultados[:MAX_CANDIDATOS]
    primero: dict | None = None

    for cand in candidatos:
        registro = normalizar(client.detalle(cand["id"]))
        if primero is None:
            primero = registro
        # Con RFC exigimos coincidencia exacta; con texto libre basta el primero.
        if not es_rfc:
            break
        if registro.get("rfc") == rfc:
            primero = registro
            break
    else:
        if es_rfc:
            # Hubo resultados de texto, pero ninguno con ese RFC.
            return _sin_registro(
                termino,
                f"El RFC {rfc} no coincide con ningún registro del padrón REPSE "
                f"({len(resultados)} resultado(s) por texto, ninguno con ese RFC).",
            )

    assert primero is not None  # hay al menos un candidato
    return {
        "consulta": termino,
        "encontrado": True,
        **primero,
        "candidatos": [c.get("text") for c in resultados[:MAX_CANDIDATOS]]
        if len(resultados) > 1
        else [],
    }

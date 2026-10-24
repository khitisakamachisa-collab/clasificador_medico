from __future__ import annotations

import math

from .config import Config
from .utils import CATEGORÍAS

PESOS = Config.CRITICALITY_WEIGHTS


def calcular_criticidad(
    impacto: float,
    redundancia: float,
    frecuencia: float,
    historial: float,
    costo: float,
) -> dict:
    """Calcula el índice ponderado de criticidad y el nivel resultante."""
    values = (impacto, redundancia, frecuencia, historial, costo)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 1 <= value <= 5
        for value in values
    ):
        raise ValueError("Cada factor de criticidad debe estar entre 1 y 5.")

    indice = (
        impacto * PESOS["impacto_clinico"]
        + redundancia * PESOS["redundancia"]
        + frecuencia * PESOS["frecuencia_uso"]
        + historial * PESOS["historial_fallas"]
        + costo * PESOS["costo_tiempo"]
    )
    if indice >= Config.CRITICALITY_LEVELS["ALTA"]:
        nivel = "ALTA"
    elif indice >= Config.CRITICALITY_LEVELS["MEDIA"]:
        nivel = "MEDIA"
    else:
        nivel = "BAJA"

    return {
        "indice": round(indice, 2),
        "nivel": nivel,
        "desglose": {
            "impacto_clinico": impacto,
            "redundancia": redundancia,
            "frecuencia_uso": frecuencia,
            "historial_fallas": historial,
            "costo_tiempo": costo,
        },
    }


def obtener_valores_por_defecto(categoria: str) -> dict[str, int]:
    """Retorna los valores por defecto asociados a una categoría."""
    if categoria not in CATEGORÍAS:
        categoria = "OFI-01"
    return CATEGORÍAS[categoria]["defaults"].copy()


def ajustar_por_mdr(valores: dict[str, int], mdr_class: str) -> dict[str, int]:
    """Ajusta los valores de criticidad según la clase MDR."""
    valores_ajustados = valores.copy()
    if mdr_class == "III":
        valores_ajustados["impacto_clinico"] = 5
    elif mdr_class == "IIb":
        valores_ajustados["impacto_clinico"] = max(valores_ajustados["impacto_clinico"], 4)
    elif mdr_class == "IIa":
        valores_ajustados["impacto_clinico"] = max(valores_ajustados["impacto_clinico"], 3)
    return valores_ajustados

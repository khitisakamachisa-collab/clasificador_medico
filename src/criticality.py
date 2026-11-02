from __future__ import annotations

import math
import json

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
    with Config.CRITICALITY_DEFAULTS_PATH.open(encoding="utf-8") as file:
        defaults = json.load(file)
    if categoria not in defaults:
        raise ValueError(f"No hay valores de criticidad para la categoría {categoria}.")
    return {field: defaults[categoria][field] for field in PESOS}


def cargar_criticidad_defaults() -> dict:
    """Carga y valida los valores externos para todas las categorías propias."""
    with Config.CRITICALITY_DEFAULTS_PATH.open(encoding="utf-8") as file:
        defaults = json.load(file)
    if not isinstance(defaults, dict) or set(defaults) != set(CATEGORÍAS):
        raise ValueError(
            "Los valores de criticidad deben cubrir exactamente las 25 categorías propias."
        )
    for category, data in defaults.items():
        if not isinstance(data, dict) or not isinstance(data.get("justificacion"), str):
            raise ValueError(f"Faltan datos o justificación para la categoría {category}.")
        for field in PESOS:
            value = data.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f"{category}.{field} debe ser un entero entre 1 y 5.")
        expected = calcular_criticidad(*(data[field] for field in PESOS))["indice"]
        if (
            isinstance(data.get("indice"), bool)
            or not isinstance(data.get("indice"), (int, float))
            or not math.isclose(data["indice"], expected, abs_tol=0.001)
        ):
            raise ValueError(
                f"El índice documentado de {category} no coincide: "
                f"se esperaba {expected:.2f}."
            )
    return defaults


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

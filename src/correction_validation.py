from __future__ import annotations

import re
import unicodedata
from typing import Any

from .criticality import calcular_criticidad
from .emdn_importer import load_emdn_database
from .rules_dictionary import EMDN_PREFIXES
from .utils import CATEGORÍAS, CATEGORY_KEYWORDS

_MDR_LEVELS = {"I": 1, "IIa": 2, "IIb": 3, "III": 4}
_CRITICALITY_FIELDS = (
    "impacto_clinico",
    "redundancia",
    "frecuencia_uso",
    "historial_fallas",
    "costo_tiempo",
)
_STOP_WORDS = {
    "a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "para",
    "por", "un", "una", "y", "and", "for", "or", "the", "with", "equipment",
    "device", "devices", "medical",
}
_SEMANTIC_SYNONYMS = {
    "bisturi": {"scalpel", "scalpels", "knife", "surgical"},
    "cama": {"bed", "beds", "patient", "intensive", "care", "hospital"},
    "electroestimulador": {
        "electromechanical", "physical", "therapy", "electrical", "stimulation", "stimulator"
    },
    "monitor": {"monitor", "monitors", "vital", "signs", "multiparameter"},
    "mesa": {"table", "tables", "operating", "surgical"},
    "quirofano": {"operating", "surgery", "surgical"},
    "uci": {"intensive", "care", "critical"},
}
_ADDITIONAL_EMDN_PREFIXES = {
    # Instrumentos quirúrgicos reutilizables pertenecen a L01 en EMDN, no a Z1201.
    "CIR-01": ("L0101",),
}


def _normalize_words(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return {
        word
        for word in re.findall(r"[a-z0-9]+", normalized)
        if word not in _STOP_WORDS
    }


def validar_semantica(nombre_equipo: str, termino_emdn: str) -> bool:
    """Comprueba relación léxica o sinónimos médicos entre equipo y término EMDN."""
    equipment_words = _normalize_words(nombre_equipo or "")
    term_words = _normalize_words(termino_emdn or "")
    if not equipment_words or not term_words:
        return False
    if equipment_words & term_words:
        return True

    aliases = set()
    for word in equipment_words:
        aliases.update(_SEMANTIC_SYNONYMS.get(word, ()))
    if aliases & term_words:
        return True

    # Las palabras clave de categoría amplían equivalencias de nombres de equipos médicos.
    for category, keywords in CATEGORY_KEYWORDS.items():
        keyword_words = set().union(*(_normalize_words(keyword) for keyword in keywords))
        if equipment_words & keyword_words:
            category_aliases = set().union(
                *(_normalize_words(keyword) for keyword in CATEGORY_KEYWORDS[category])
            )
            if category_aliases & term_words:
                return True
    return False


def verificar_emdn_en_excel(categoria: str, emdn_code: str) -> bool:
    """Comprueba que el código EMDN sea terminal y use el prefijo de la categoría."""
    prefixes = (EMDN_PREFIXES.get(categoria), *_ADDITIONAL_EMDN_PREFIXES.get(categoria, ()))
    prefixes = tuple(prefix for prefix in prefixes if prefix)
    if not prefixes or not emdn_code:
        return False
    database = load_emdn_database()
    item = database.get("flat", {}).get(str(emdn_code).strip())
    return bool(
        item
        and item.get("terminal_level") == "YES"
        and str(emdn_code).strip().startswith(prefixes)
    )


def verificar_mdr_categoria(categoria: str, mdr_class: str) -> bool:
    """Acepta la clase MDR por defecto o una clase vecina en la escala regulatoria."""
    category = CATEGORÍAS.get(categoria)
    if not category or not isinstance(mdr_class, str):
        return False
    default_level = _MDR_LEVELS.get(category.get("mdr_default"))
    candidate_level = _MDR_LEVELS.get(mdr_class)
    return bool(
        default_level is not None
        and candidate_level is not None
        and abs(default_level - candidate_level) <= 1
    )


def verificar_criticidad_categoria(categoria: str, criticidad: dict[str, Any]) -> bool:
    """Verifica rangos, proximidad a los valores de categoría e índice coherente."""
    category = CATEGORÍAS.get(categoria)
    if not category or not isinstance(criticidad, dict):
        return False

    defaults = category["defaults"]
    values = {}
    for field in _CRITICALITY_FIELDS:
        value = criticidad.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 1 <= value <= 5
            or abs(value - defaults[field]) > 1
        ):
            return False
        values[field] = value

    try:
        expected = calcular_criticidad(*(values[field] for field in _CRITICALITY_FIELDS))
    except (TypeError, ValueError):
        return False
    index = criticidad.get("indice")
    level = criticidad.get("nivel")
    return bool(
        isinstance(index, (int, float))
        and not isinstance(index, bool)
        and abs(index - expected["indice"]) <= 0.01
        and level == expected["nivel"]
    )


def validar_correccion_automaticamente(
    correccion: dict[str, Any], *, nombre_equipo: str | None = None
) -> dict[str, Any]:
    """Asigna una puntuación de coherencia basada en las tres validaciones objetivas."""
    category = correccion.get("categoria_propia") or correccion.get("categoria")
    emdn_code = correccion.get("emdn_code", "")
    database = load_emdn_database()
    emdn_entry = database.get("flat", {}).get(str(emdn_code).strip())
    term = (emdn_entry or {}).get("term") or correccion.get("emdn_term") or ""
    semantic_valid = validar_semantica(
        nombre_equipo or correccion.get("nombre_equipo") or correccion.get("nombre") or "",
        term,
    )
    checks = {
        "emdn_valido": verificar_emdn_en_excel(category, emdn_code),
        "mdr_coherente": verificar_mdr_categoria(category, correccion.get("mdr_class", "")),
        "criticidad_razonable": verificar_criticidad_categoria(
            category, correccion.get("criticidad", {})
        ),
        "semantica_valida": semantic_valid,
    }
    passed = sum(checks[key] for key in ("emdn_valido", "mdr_coherente", "criticidad_razonable"))
    if not semantic_valid:
        confidence = 0.0
        state = "RECHAZADA"
        message = (
            "Corrección rechazada: El término EMDN no tiene relación semántica "
            "con el nombre del equipo. Por favor, revise la corrección."
        )
    elif passed == 3:
        confidence = 0.95
        state = "VALIDADA_AUTOMATICAMENTE"
        message = (
            "✅ Corrección validada automáticamente. EMDN, MDR, criticidad y "
            "coherencia semántica verificadas."
        )
    elif passed == 2:
        confidence = 0.75
        state = "PENDIENTE_REVISION"
        message = "Corrección pendiente de revisión. 2 de 3 validaciones pasaron."
    else:
        confidence = 0.30
        state = "RECHAZADA"
        message = "Corrección rechazada. Los datos no son coherentes."

    return {
        "confidence": confidence,
        "estado": state,
        "validaciones": checks,
        "mensaje": message,
    }

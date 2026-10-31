from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
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
    "por", "un", "una", "unos", "unas", "y", "and", "for", "or", "the",
    "with", "equipment", "device", "devices", "medical",
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
SINONIMOS_MEDICOS = {
    "monitor": {"monito", "monitores", "monitoreo", "monitor", "monitors"},
    "ecografo": {
        "ecografo", "ultrasonido", "eco", "ultrason", "ultrasound", "scanner", "scanners"
    },
    "respirador": {
        "respirador",
        "ventilador",
        "ventilacion",
        "respirator",
        "respirators",
        "ventilator",
        "ventilators",
    },
    "bisturi": {"bisturi", "escalpelo", "scalpel", "scalpels", "knife", "surgical"},
    "cama": {
        "cama", "camilla", "litera", "bed", "beds", "patient", "intensive", "care",
        "hospital",
    },
    "lampara": {
        "lampara", "luz", "foco", "lamp", "lamps", "light", "lights", "source",
        "sources", "scialytic", "scialytics",
    },
    "tens": {
        "physical", "therapy", "physiotherapy", "fisioterapia", "terapia", "fisica",
    },
    "ems": {
        "physical", "therapy", "physiotherapy", "fisioterapia", "terapia", "fisica",
    },
    "uci": {
        "uci", "unidad", "unidades", "cuidados", "intensivos", "intensive", "care",
        "critical",
    },
}
_ADDITIONAL_EMDN_PREFIXES = {
    # Instrumentos quirúrgicos reutilizables pertenecen a L01 en EMDN, no a Z1201.
    "CIR-01": ("L0101",),
}
_ADDITIONAL_EMDN_CODES = {"CIR-01": {"Z129004"}}


def _stem_word(word: str) -> str:
    """Reduce plurales comunes en español e inglés a una forma comparable."""
    if len(word) > 5 and word.endswith("es"):
        return word[:-2]
    if len(word) > 4 and word.endswith("s"):
        return word[:-1]
    return word


def normalizar_texto(texto: str) -> str:
    """Normaliza acentos, caracteres, palabras vacías y plurales comunes."""
    normalized = unicodedata.normalize("NFKD", (texto or "").lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]+", normalized)
    return " ".join(_stem_word(word) for word in words if word not in _STOP_WORDS)


def _normalize_words(value: str) -> set[str]:
    return set(normalizar_texto(value).split())


def calcular_similitud(str1: str, str2: str) -> float:
    """Calcula la similitud entre dos términos mediante SequenceMatcher."""
    return SequenceMatcher(None, str1, str2).ratio()


def validar_semantica(nombre_equipo: str, termino_emdn: str) -> bool:
    """Comprueba relación léxica o sinónimos médicos entre equipo y término EMDN."""
    equipment_words = _normalize_words(nombre_equipo or "")
    term_words = _normalize_words(termino_emdn or "")
    if not equipment_words or not term_words:
        return False
    if equipment_words & term_words:
        return True

    for word in equipment_words:
        for canonical, synonyms in SINONIMOS_MEDICOS.items():
            synonym_words = _normalize_words(" ".join({canonical, *synonyms}))
            if word in synonym_words and synonym_words & term_words:
                return True

    aliases = set()
    for word in equipment_words:
        aliases.update(_SEMANTIC_SYNONYMS.get(word, ()))
    if _normalize_words(" ".join(aliases)) & term_words:
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

    # La comparación aproximada se limita a palabras suficientemente largas para
    # evitar coincidencias accidentales entre términos cortos.
    for word in equipment_words:
        if len(word) < 4:
            continue
        for term_word in term_words:
            if len(term_word) >= 4 and calcular_similitud(word, term_word) >= 0.80:
                return True
    return False


def verificar_emdn_en_excel(categoria: str, emdn_code: str) -> bool:
    """Comprueba que el código EMDN sea terminal y use el prefijo de la categoría."""
    prefixes = (EMDN_PREFIXES.get(categoria), *_ADDITIONAL_EMDN_PREFIXES.get(categoria, ()))
    prefixes = tuple(prefix for prefix in prefixes if prefix)
    allowed_codes = _ADDITIONAL_EMDN_CODES.get(categoria, set())
    if (not prefixes and not allowed_codes) or not emdn_code:
        return False
    database = load_emdn_database()
    code = str(emdn_code).strip()
    item = database.get("flat", {}).get(code)
    return bool(
        item
        and item.get("terminal_level") == "YES"
        and (code.startswith(prefixes) or code in allowed_codes)
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
    """Asigna confianza según las validaciones estructurales y semánticas."""
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
        confidence = 0.30
        state = "RECHAZADA"
        message = (
            "❌ Corrección rechazada: El nombre del equipo no tiene relación "
            "semántica con el término EMDN seleccionado. Por favor, revise la "
            "categoría elegida."
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

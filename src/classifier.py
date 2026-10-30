from __future__ import annotations

import json
import math
import re
import unicodedata
import logging
import pickle
from functools import lru_cache
from pathlib import Path

import joblib

from .config import Config
from .criticality import ajustar_por_mdr, calcular_criticidad, obtener_valores_por_defecto
from .correction_validation import validar_correccion_automaticamente
from .emdn_importer import buscar_emdn, load_emdn_database, validar_codigo_emdn
from .code_generator import generar_codigo_interno
from .trainer import preprocess_text, train_model
from .rules_dictionary import EMDN_PREFIXES, EMDN_SUBCATEGORY_PREFIXES, REGLAS_CLASIFICACION
from .utils import CATEGORÍAS, MODELS_DIR

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def load_model_assets():
    classifier_path = MODELS_DIR / f"classifier_{Config.MODEL_VERSION}.pkl"
    vectorizer_path = MODELS_DIR / f"vectorizer_{Config.MODEL_VERSION}.pkl"
    if not classifier_path.exists() or not vectorizer_path.exists():
        train_model()
    clf = joblib.load(classifier_path)
    vectorizer = joblib.load(vectorizer_path)
    return clf, vectorizer


@lru_cache(maxsize=512)
def _cached_emdn_search(
    search_terms: tuple[str, ...],
    prefix: str,
    limit: int,
    source: str,
    modified: int | None,
) -> tuple[tuple[str, float, str], ...]:
    database = load_emdn_database(source)
    return tuple(
        buscar_emdn(list(search_terms), database, limit=limit, prefix=prefix)
    )


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


@lru_cache(maxsize=1)
def _load_master_rules() -> tuple[dict[str, str], ...]:
    """Carga las reglas maestras externas y valida su estructura y valores."""
    with Config.MASTER_RULES_PATH.open(encoding="utf-8") as file:
        rules = json.load(file)
    if not isinstance(rules, list):
        raise ValueError("El archivo de reglas maestras debe contener una lista.")

    required_fields = {"keyword", "categoria", "emdn_code", "mdr_class", "criticidad"}
    for rule in rules:
        if not isinstance(rule, dict) or not required_fields.issubset(rule):
            raise ValueError("Cada regla maestra debe incluir todos los campos requeridos.")
        if (
            not isinstance(rule["keyword"], str)
            or not rule["keyword"].strip()
            or not isinstance(rule["categoria"], str)
            or rule["categoria"] not in CATEGORÍAS
            or not isinstance(rule["emdn_code"], str)
            or not rule["emdn_code"].strip()
            or not isinstance(rule["mdr_class"], str)
            or rule["mdr_class"] not in {"I", "IIa", "IIb", "III"}
            or not isinstance(rule["criticidad"], str)
            or rule["criticidad"] not in {"BAJA", "MEDIA", "ALTA"}
            or (
                "confidence" in rule
                and (
                    not isinstance(rule["confidence"], (int, float))
                    or isinstance(rule["confidence"], bool)
                    or not math.isfinite(rule["confidence"])
                    or not 0 <= rule["confidence"] <= 1
                )
            )
        ):
            raise ValueError(f"Regla maestra no válida: {rule!r}")
    return tuple(rules)


def _master_rule_match(name: str, category: str | None = None) -> dict[str, str] | None:
    """Devuelve la regla maestra más específica que coincide con el nombre."""
    normalized_name = f" {_normalize_text(name)} "
    matches = [
        rule
        for rule in _load_master_rules()
        if (category is None or rule["categoria"] == category)
        and f" {_normalize_text(rule['keyword'])} " in normalized_name
    ]
    return max(matches, key=lambda rule: len(_normalize_text(rule["keyword"])), default=None)


def _master_rule_for_keyword(keyword: str | None) -> dict[str, str] | None:
    """Obtiene los metadatos externos asociados a una palabra clave."""
    if keyword is None:
        return None
    normalized_keyword = _normalize_text(keyword)
    return next(
        (
            rule
            for rule in _load_master_rules()
            if _normalize_text(rule["keyword"]) == normalized_keyword
        ),
        None,
    )


def _category_from_rules(name: str) -> tuple[str, str, float] | None:
    master_rule = _master_rule_match(name)
    if master_rule:
        return (
            master_rule["categoria"],
            master_rule["keyword"],
            float(master_rule.get("confidence", 0.96)),
        )

    normalized_name = f" {_normalize_text(name)} "
    matches = []
    for keyword, rule in REGLAS_CLASIFICACION.items():
        normalized_keyword = _normalize_text(keyword)
        if normalized_keyword and f" {normalized_keyword} " in normalized_name:
            matches.append((len(normalized_keyword), rule["categoria"], keyword, rule["confidence"]))
    if not matches:
        return None
    _, category, keyword, confidence = max(matches)
    return category, keyword, confidence


def _rule_keyword_for_category(name: str, category: str) -> str | None:
    normalized_name = f" {_normalize_text(name)} "
    matching_keywords = [
        rule["keyword"]
        for rule in _load_master_rules()
        if rule["categoria"] == category
        and f" {_normalize_text(rule['keyword'])} " in normalized_name
    ] + [
        keyword
        for keyword, rule in REGLAS_CLASIFICACION.items()
        if rule["categoria"] == category
        and (normalized_keyword := _normalize_text(keyword))
        and f" {normalized_keyword} " in normalized_name
    ]
    return max(
        matching_keywords,
        key=lambda keyword: len(_normalize_text(keyword)),
        default=None,
    )


def obtener_semaforo(confidence: float) -> dict:
    """Traduce la confianza del clasificador a un nivel visual de revisión."""
    if confidence >= 0.90:
        return {
            "color": "verde",
            "hex": "#10B981",
            "nivel": "ALTA",
            "mensaje": "Clasificación de alta confianza",
            "icono": "✅",
            "requiere_revision": False,
        }
    if confidence >= 0.70:
        return {
            "color": "amarillo",
            "hex": "#F59E0B",
            "nivel": "MEDIA",
            "mensaje": "Confianza media. Verificar si es correcto.",
            "icono": "⚠️",
            "requiere_revision": True,
        }
    return {
        "color": "rojo",
        "hex": "#EF4444",
        "nivel": "BAJA",
        "mensaje": "Baja confianza. Requiere revisión manual.",
        "icono": "❌",
        "requiere_revision": True,
    }


def _emdn_prefix(category: str, nombre: str, ubicacion: str | None) -> tuple[str, list[str]]:
    normalized = _normalize_text(f"{nombre or ''} {ubicacion or ''}")
    subcategories = EMDN_SUBCATEGORY_PREFIXES.get(category, {})
    preferred_terms = []

    if category == "IMG-02":
        if re.search(r"\b(pet|positron)\b", normalized):
            return subcategories["pet"], ["positron emission tomographs"]
        if re.search(r"\b(mri|rm|resonador|resonancia|magnet|magnetic)\b", normalized):
            return subcategories["mri"], [
                "closed magnet mri scanners with magnetic field less than or equal to 2t"
            ]
        return subcategories["ct"], ["computed tomographs"]

    if category == "RES-01":
        if "portable" in normalized or "portatil" in normalized:
            preferred_terms = ["portable pulmonary ventilators"]
            return subcategories["portable"], preferred_terms
        if re.search(
            r"\b(uci|uti|hospital|hospitalario|quirofano|sala operatoria|sala de operaciones|emergencia|urgencias|ucin|postoperatorio)\b",
            normalized,
        ):
            preferred_terms = ["adult pulmonary ventilators"]
            return subcategories["hospital"], preferred_terms
        if re.search(r"\b(ambulatorio|domicilio|home)\b", normalized):
            return subcategories["non_hospital"], ["pulmonary ventilators for non-hospital use"]

    if category == "IMG-01":
        return subcategories["radiography"], ["teleradiographs"]

    if category == "CIR-01":
        if re.search(r"\b(movil|mobile)\b", normalized):
            return subcategories["scialytic_mobile"], ["mobile scialytic lamps"]
        if re.search(r"\b(cialitica|quirurgica|scialytic|operating lamp)\b", normalized):
            return subcategories["scialytic_fixed"], ["fixed scialytic lamps"]

    if category == "EST-01":
        small_autoclave_terms = (
            "mesa", "pequeno", "small", "portatil", "consultorio", "odontolog",
            "dental", "clinica pequena",
        )
        if any(term in normalized for term in small_autoclave_terms):
            return subcategories["small_load_autoclave"], ["small load autoclaves"]
        return subcategories["large_autoclave"], ["autoclaves with a chamber larger than or equal to 1 standard sterilisation unit"]

    if category == "MON-01":
        if re.search(r"\b(portable|transportable|portatil)\b", normalized):
            return subcategories["portable"], ["transportable portable multi parameter patient monitors"]
        if re.search(r"\b(uci|uti|hospital|bedside)\b", normalized):
            return subcategories["bedside"], ["multi parameter patient bedside monitors"]

    if category == "URG-01":
        if re.search(r"\b(semi|semiautomatico|semi automatic)\b", normalized):
            return subcategories["semi"], ["semi automatic defibrillators"]
        if re.search(r"\b(automatic|automatico|dea)\b", normalized):
            return subcategories["automatic"], ["automatic defibrillators"]
        return subcategories["manual"], ["manual defibrillators"]

    if category == "IMG-03":
        if "cardiolog" in normalized:
            return subcategories["cardiology"], ["cardiology ultrasound scanners"]
        if re.search(r"\b(obstetr|ginecolog)", normalized):
            return subcategories["obstetric"], ["obstetric gynaecological ultrasound scanners"]
        if re.search(r"\b(portable|portatil|emergency|emergencia)\b", normalized):
            return subcategories["portable"], ["portable ultrasound scanners"]
        preferred_terms = ["portable ultrasound"]

    if category == "DIA-01":
        if "peritoneal" in normalized or "peritoneal" in _normalize_text(nombre):
            return subcategories["peritoneal"], ["peritoneal dialysis equipment"]
        return subcategories["haemodialysis"], ["haemodialysis equipment"]

    if category == "GAS-01":
        if re.search(r"\b(oxygen|oxigeno|concentrador)\b", normalized):
            return subcategories["oxygen_concentrator"], ["oxygen concentrators"]
        return subcategories["gas_pipeline"], ["medical medicinal gas pipeline systems"]

    if category == "INF-01":
        if re.search(r"\b(jeringa|syringe)\b", normalized):
            return subcategories["syringe"], ["syringe pumps"]
        if re.search(r"\b(enteral|nutricion)\b", normalized):
            return subcategories["enteral"], ["enteral feeding pumps"]
        return subcategories["infusion"], ["infusion pumps"]

    return EMDN_PREFIXES.get(category, ""), preferred_terms


def refinar_emdn_por_ubicacion(
    categoria: str,
    nombre_equipo: str | None,
    ubicacion: str | None,
    candidatos_emdn: list,
):
    """Prioriza la subfamilia EMDN según el equipo y su ubicación."""
    if not candidatos_emdn:
        return None
    if not ubicacion:
        return candidatos_emdn[0]

    equipment_name = _normalize_text(nombre_equipo or "")
    location = _normalize_text(ubicacion or "")
    combined_text = f"{equipment_name} {location}".strip()
    hospital_locations = tuple(_normalize_text(place) for place in Config.HOSPITAL_LOCATIONS)
    non_hospital_locations = (
        "domicilio", "casa", "hogar", "ambulatorio externo", "transporte",
        "ambulancia", "vehiculo", "al aire libre", "campo", "rural remoto",
    )
    is_hospital = any(place in location for place in hospital_locations)
    is_non_hospital = any(place in location for place in non_hospital_locations)

    subcategories = EMDN_SUBCATEGORY_PREFIXES.get(categoria, {})
    preferred_prefix = None
    if categoria == "CIR-01" and any(
        term in combined_text for term in ("cialitica", "quirurgica", "scialytic", "operating lamp")
    ):
        lamp_type = "scialytic_mobile" if re.search(r"\b(movil|mobile)\b", combined_text) else "scialytic_fixed"
        preferred_prefix = subcategories[lamp_type]
    elif categoria == "EST-01":
        small_autoclave_terms = (
            "mesa", "pequeno", "small", "portatil", "consultorio", "odontolog",
            "dental", "clinica pequena",
        )
        auto_prefix = "small_load_autoclave" if any(
            term in combined_text for term in small_autoclave_terms
        ) else "large_autoclave"
        preferred_prefix = subcategories[auto_prefix]
    elif categoria == "RES-01":
        if is_non_hospital:
            preferred_prefix = subcategories["non_hospital"]
        elif is_hospital:
            preferred_prefix = subcategories["hospital"]
    elif categoria == "MON-01":
        if any(place in location for place in ("urgencia", "emergencia", "transporte", "ambulancia")):
            preferred_prefix = subcategories["portable"]
        elif is_hospital:
            preferred_prefix = subcategories["bedside"]
    elif categoria == "URG-01":
        if any(place in location for place in ("recepcion", "pasillo", "gimnasio", "publico")):
            preferred_prefix = subcategories["automatic"]
        elif is_hospital:
            preferred_prefix = subcategories["manual"]
    elif categoria == "IMG-03":
        if "portatil" in location or "emergencia" in location:
            preferred_prefix = subcategories["portable"]
        elif "cardiolog" in location:
            preferred_prefix = subcategories["cardiology"]
        elif "obstetr" in location or "ginecolog" in location:
            preferred_prefix = subcategories["obstetric"]
    elif categoria == "INF-01":
        if "jeringa" in location or "syringe" in location:
            preferred_prefix = subcategories["syringe"]
        elif "enteral" in location or "nutricion" in location:
            preferred_prefix = subcategories["enteral"]

    if preferred_prefix:
        for candidate in candidatos_emdn:
            code = candidate["emdn_code"] if isinstance(candidate, dict) else candidate[0]
            if code.startswith(preferred_prefix):
                return candidate
    return candidatos_emdn[0]


def buscar_emdn_por_categoria(
    categoria: str,
    nombre_equipo: str,
    ubicacion: str | None = None,
    database: dict | None = None,
    keywords: list[str] | None = None,
    limit: int = 3,
):
    """Limita la búsqueda EMDN a la familia verificada de la categoría propia."""
    database = database if database is not None else load_emdn_database()
    prefix, preferred_terms = _emdn_prefix(categoria, nombre_equipo, ubicacion)
    category_terms = [
        keyword
        for keyword, rule in REGLAS_CLASIFICACION.items()
        if rule["categoria"] == categoria
    ]
    search_terms = list(dict.fromkeys(preferred_terms + (keywords or []) + category_terms + [nombre_equipo]))
    source = database.get("source")
    if source is None:
        candidates = buscar_emdn(search_terms, database, limit=limit, prefix=prefix)
        if not candidates:
            return []
        preferred = refinar_emdn_por_ubicacion(categoria, nombre_equipo, ubicacion, candidates)
        return [preferred] + [candidate for candidate in candidates if candidate != preferred]

    source = str(source)
    try:
        modified = Path(source).stat().st_mtime_ns
    except OSError:
        modified = None
    candidates = _cached_emdn_search(
        tuple(str(term) for term in search_terms),
        prefix,
        limit,
        source,
        modified,
    )
    if not candidates:
        return []
    preferred = refinar_emdn_por_ubicacion(categoria, nombre_equipo, ubicacion, candidates)
    return [preferred] + [candidate for candidate in candidates if candidate != preferred]


def classify_equipment(
    nombre: str,
    marca: str | None = None,
    ubicacion: str | None = None,
    categoria_forzada: str | None = None,
):
    """Clasifica un equipo nuevo a partir de nombre, marca y ubicación."""
    if categoria_forzada is not None:
        if categoria_forzada not in CATEGORÍAS:
            raise ValueError(f"Categoría desconocida: {categoria_forzada}")
        category_key = categoria_forzada
        matched_keyword = _rule_keyword_for_category(nombre or "", category_key)
        method = "CORRECCION_MANUAL"
        confidence = 0.0
    else:
        rule_match = _category_from_rules(nombre or "")
        if rule_match:
            category_key, matched_keyword, confidence = rule_match
            method = "REGLAS"
        else:
            try:
                text = preprocess_text(f"{nombre or ''} {marca or ''} {ubicacion or ''}")
                if not text.strip():
                    raise ValueError("No hay texto útil para clasificar.")
                clf, vectorizer = load_model_assets()
                X = vectorizer.transform([text])
                category_key = clf.predict(X)[0]
                proba = clf.predict_proba(X)[0]
                confidence = float(max(proba)) if len(proba) > 0 else 0.0
                matched_keyword = None
                method = "NLP"
            except (
                EOFError,
                ImportError,
                OSError,
                pickle.PickleError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                logger.exception("No se pudo usar el clasificador NLP; se requiere revisión manual.")
                category_key = "OTR-01"
                confidence = 0.0
                matched_keyword = None
                method = "MANUAL"
                nlp_error = str(exc)

    category_data = CATEGORÍAS.get(category_key, CATEGORÍAS["OTR-01"])
    category_name = category_data["nombre"]
    emdn_db = load_emdn_database()
    flat = emdn_db.get("flat", {})
    candidates = buscar_emdn_por_categoria(
        category_key,
        nombre or "",
        ubicacion,
        emdn_db,
        keywords=[matched_keyword] if matched_keyword else None,
        limit=3,
    )
    master_rule = _master_rule_for_keyword(matched_keyword)
    matched_rule = master_rule or (
        REGLAS_CLASIFICACION.get(matched_keyword) if matched_keyword else None
    )
    explicit_emdn_code = matched_rule.get("emdn_code") if matched_rule else None
    explicit_emdn = flat.get(explicit_emdn_code) if explicit_emdn_code else None
    if explicit_emdn and explicit_emdn.get("terminal_level") == "YES":
        explicit_candidate = (explicit_emdn_code, 1.0, explicit_emdn["term"])
        candidates = [explicit_candidate] + [
            candidate for candidate in candidates if candidate[0] != explicit_emdn_code
        ]
    valid_candidates = [
        (code, score, term)
        for code, score, term in candidates
        if validar_codigo_emdn(code, emdn_db)
    ]
    if master_rule and explicit_emdn and explicit_emdn.get("terminal_level") == "YES":
        emdn_code = explicit_emdn_code
        emdn_name = explicit_emdn["term"]
        emdn_verified = True
    else:
        emdn_code, emdn_name = (
            (valid_candidates[0][0], valid_candidates[0][2])
            if valid_candidates
            else ("PENDIENTE_DE_VALIDACION", None)
        )
        emdn_verified = bool(valid_candidates)
    emdn_candidates = [
        {"emdn_code": code, "emdn_term": term, "score": score}
        for code, score, term in valid_candidates
    ]

    mdr_class = category_data["mdr_default"]
    if method != "CORRECCION_MANUAL" and matched_rule:
        mdr_class = matched_rule.get("mdr_class", mdr_class)
    defaults = obtener_valores_por_defecto(category_key)
    adjusted = ajustar_por_mdr(defaults, mdr_class)
    criticidad = calcular_criticidad(
        adjusted["impacto_clinico"],
        adjusted["redundancia"],
        adjusted["frecuencia_uso"],
        adjusted["historial_fallas"],
        adjusted["costo_tiempo"],
    )

    result = {
        "categoria": category_key,
        "categoria_propia": category_key,
        "categoria_nombre": category_name,
        "emdn_code": emdn_code,
        "emdn_term": emdn_name,
        "emdn_name": emdn_name,
        "emdn_verified": emdn_verified,
        "emdn_candidates": emdn_candidates,
        "mdr_class": mdr_class,
        "confidence": round(confidence, 4),
        "semaforo": obtener_semaforo(confidence),
        "metodo": method,
        "codigo_interno": generar_codigo_interno(category_key),
        "criticidad": {
            "impacto_clinico": adjusted["impacto_clinico"],
            "redundancia": adjusted["redundancia"],
            "frecuencia_uso": adjusted["frecuencia_uso"],
            "historial_fallas": adjusted["historial_fallas"],
            "costo_tiempo": adjusted["costo_tiempo"],
            "indice": criticidad["indice"],
            "nivel": criticidad["nivel"],
        },
    }
    if master_rule:
        result["criticidad_regla"] = master_rule["criticidad"]

    if method == "CORRECCION_MANUAL":
        validation = validar_correccion_automaticamente(result, nombre_equipo=nombre)
        result["validacion_correccion"] = validation
        result["confidence"] = validation["confidence"]
        result["semaforo"] = obtener_semaforo(validation["confidence"])
        result["semaforo"]["mensaje"] = validation["mensaje"]
    elif method == "MANUAL":
        result["advertencia"] = (
            "No fue posible usar el modelo NLP; se requiere revisión manual. "
            f"Detalle: {nlp_error}"
        )
    elif confidence < Config.LOW_CONFIDENCE_THRESHOLD:
        result["advertencia"] = "Clasificación de baja confianza. Se recomienda revisión manual."
    elif method == "NLP" and confidence < Config.NLP_CONFIDENCE_THRESHOLD:
        result["advertencia"] = (
            "Confianza NLP inferior al umbral configurado. Se recomienda revisión manual."
        )
    return result


def clasificar_equipo(nombre: str, marca: str | None = None, ubicacion: str | None = None):
    """Alias en español para clasificar un equipo médico."""
    return classify_equipment(nombre, marca, ubicacion)

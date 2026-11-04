from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .config import Config
from .emdn_importer import buscar_emdn, load_emdn_database
from .rules_dictionary import EMDN_ADDITIONAL_CATEGORY_PREFIXES, EMDN_PREFIXES
from .utils import CATEGORÍAS, PROCESSED_DIR, RAW_DIR, ensure_directories


def _normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _find_column(frame: pd.DataFrame, expected: str) -> object | None:
    normalized_expected = _normalize_label(expected)
    return next(
        (
            column
            for column in frame.columns
            if _normalize_label(column) == normalized_expected
            or _normalize_label(column).startswith(normalized_expected + " ")
        ),
        None,
    )


def _category_prefixes(category: str) -> tuple[str, ...]:
    return (
        EMDN_PREFIXES.get(category, ""),
        *EMDN_ADDITIONAL_CATEGORY_PREFIXES.get(category, ()),
    )


def _internal_category_for_code(code: str) -> str | None:
    matches = [
        (len(prefix), category)
        for category in CATEGORÍAS
        for prefix in _category_prefixes(category)
        if prefix and code.startswith(prefix)
    ]
    if not matches:
        return None
    longest = max(length for length, _ in matches)
    categories = {category for length, category in matches if length == longest}
    return next(iter(categories)) if len(categories) == 1 else None


def _category_matches(
    suggested: str, code: str, official_row: dict[str, str]
) -> tuple[bool, str | None]:
    normalized_suggestion = _normalize_label(suggested)
    normalized_internal = {
        _normalize_label(category): category for category in CATEGORÍAS
    }
    normalized_internal.update(
        {
            _normalize_label(details["nombre"]): category
            for category, details in CATEGORÍAS.items()
        }
    )
    internal_category = normalized_internal.get(normalized_suggestion)
    if internal_category:
        allowed_prefixes = tuple(
            prefix for prefix in _category_prefixes(internal_category) if prefix
        )
        matches = code.startswith(allowed_prefixes)
        return matches, internal_category if matches else None

    emdn_category = _normalize_label(official_row.get("category", ""))
    emdn_description = _normalize_label(official_row.get("category_description", ""))
    if normalized_suggestion not in {emdn_category, emdn_description}:
        return False, None

    derived_category = _internal_category_for_code(code)
    return derived_category is not None, derived_category


def validate_suggestions(
    input_path: str | Path | None = None,
    emdn_path: str | Path | None = None,
    validated_output: str | Path | None = None,
    discrepancies_output: str | Path | None = None,
) -> dict:
    """Valida sugerencias sin corregir códigos ni categorías automáticamente."""
    ensure_directories()
    source = Path(input_path) if input_path else PROCESSED_DIR / "sugerencias_ia_ejemplo.json"
    excel = Path(emdn_path) if emdn_path else Config.EMDN_EXCEL_PATH
    valid_target = (
        Path(validated_output)
        if validated_output
        else PROCESSED_DIR / "equipos_validados.json"
    )
    discrepancies_target = (
        Path(discrepancies_output)
        if discrepancies_output
        else PROCESSED_DIR / "discrepancias.json"
    )

    with source.open("r", encoding="utf-8") as file:
        suggestions = json.load(file)
    if not isinstance(suggestions, list):
        raise ValueError("El archivo de sugerencias debe contener una lista JSON.")

    frame = pd.read_excel(excel, header=1, dtype=str)
    code_column = _find_column(frame, "code")
    terminal_column = _find_column(frame, "terminal level")
    category_column = _find_column(frame, "category")
    description_column = _find_column(frame, "category description")
    term_column = _find_column(frame, "term emdn")
    if any(
        column is None
        for column in (
            code_column,
            terminal_column,
            category_column,
            description_column,
            term_column,
        )
    ):
        raise ValueError(
            "El Excel debe incluir CODE, TERMINAL LEVEL, CATEGORY, "
            "CATEGORY DESCRIPTION y TERM EMDN."
        )

    rows_by_code: dict[str, list[dict[str, str]]] = {}
    for _, row in frame.iterrows():
        code = str(row[code_column] or "").strip()
        if not code or code.casefold() == "nan":
            continue
        rows_by_code.setdefault(code, []).append(
            {
                "terminal": str(row[terminal_column] or "").strip().upper(),
                "category": str(row[category_column] or "").strip(),
                "category_description": str(row[description_column] or "").strip(),
                "term": str(row[term_column] or "").strip(),
            }
        )

    validated = []
    discrepancies = []
    for index, record in enumerate(suggestions, start=1):
        if not isinstance(record, dict):
            discrepancies.append(
                {
                    "registro": index,
                    "sugerencia": record,
                    "estado": "DISCREPANCIA",
                    "motivo": "El registro debe ser un objeto JSON.",
                }
            )
            continue

        name = str(record.get("nombre_equipo") or "").strip()
        suggested_category = str(record.get("categoria_sugerida") or "").strip()
        suggested_code = str(record.get("emdn_sugerido") or "").strip()
        reasons = []
        if not name:
            reasons.append("Falta nombre_equipo.")
        if not suggested_category:
            reasons.append("Falta categoria_sugerida.")
        if not suggested_code:
            reasons.append("Falta emdn_sugerido.")

        official_rows = rows_by_code.get(suggested_code, [])
        if suggested_code and not official_rows:
            reasons.append("El código no existe en el Excel oficial.")
        elif official_rows and not any(
            row["terminal"] == "YES" for row in official_rows
        ):
            reasons.append("El código existe, pero no es terminal (TERMINAL LEVEL != YES).")

        official_row = next(
            (row for row in official_rows if row["terminal"] == "YES"),
            official_rows[0] if official_rows else {},
        )
        category_matches = False
        internal_category = None
        if suggested_category and official_row:
            category_matches, internal_category = _category_matches(
                suggested_category, suggested_code, official_row
            )
            if not category_matches:
                reasons.append(
                    "La categoría sugerida no coincide con la categoría EMDN "
                    "ni con la familia interna del código."
                )
        elif suggested_category and not official_row:
            reasons.append("No se pudo validar la categoría sin un código existente.")

        if reasons:
            discrepancies.append(
                {
                    **record,
                    "estado": "DISCREPANCIA",
                    "motivo": " ".join(reasons),
                    "motivos": reasons,
                }
            )
            continue

        validated.append(
            {
                **record,
                "nombre": name,
                "marca": record.get("marca"),
                "ubicacion": record.get("ubicacion"),
                "categoria": internal_category,
                "emdn_code": suggested_code,
                "emdn_term": official_row["term"],
                "estado": "VALIDADO",
                "source": "EMDN_VALIDATED_SUGGESTION",
            }
        )

    for target, records in (
        (valid_target, validated),
        (discrepancies_target, discrepancies),
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)

    return {
        "total": len(suggestions),
        "validados": len(validated),
        "discrepancias": len(discrepancies),
        "equipos_validados": str(valid_target),
        "discrepancias_path": str(discrepancies_target),
    }


def build_demo_equipment_dataset() -> list[dict]:
    """Genera un conjunto sintético de 224 ejemplos para entrenamiento y validación."""
    base = [
        ("Ecógrafo Samsung WS80A", "Samsung", "Imagenología", "IMG-03", "IIa"),
        ("Monitor fetal Edan F6", "Edan", "Neonatología", "MON-01", "IIa"),
        ("Equipo de rayos X GE Optima", "GE", "Radiología", "IMG-01", "IIb"),
        ("Ventilador respiratorio Dräger V500", "Dräger", "UTI", "RES-01", "IIb"),
        ("Bomba de infusión Alaris GP", "BD", "Infusión", "INF-01", "IIb"),
        ("Anestesia máquina Aisys", "GE", "Quirófano", "ANE-01", "IIb"),
    ]

    records = []
    for idx in range(224):
        nombre, marca, ubicacion, categoria, mdr = base[idx % len(base)]
        nombre_f = f"{nombre} {idx + 1}"
        records.append(
            {
                "id": idx + 1,
                "nombre": nombre_f,
                "marca": marca,
                "ubicacion": ubicacion,
                "categoria": categoria,
                "mdr": mdr,
                "criticidad": {"impacto_clinico": 3, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3},
            }
        )
    return records


def load_equipment_dataset(path: str | Path | None = None):
    ensure_directories()
    target = Path(path) if path else RAW_DIR / "equipos_ejemplo.json"
    if not target.exists():
        dataset = build_demo_equipment_dataset()
        with open(target, "w", encoding="utf-8") as file:
            json.dump(dataset, file, ensure_ascii=False, indent=2)
        return dataset
    with open(target, "r", encoding="utf-8") as file:
        return json.load(file)


def validate_equipment_dataset(dataset_path: str | Path | None = None, emdn_path: str | Path | None = None):
    """Valida el dataset de entrenamiento contra la base EMDN y genera reportes."""
    ensure_directories()
    dataset = load_equipment_dataset(dataset_path)
    database = load_emdn_database(emdn_path)
    flat = database.get("flat", {})

    validos = 0
    corregidos = 0
    no_encontrados = 0
    detalles = []
    search_cache = {}

    def buscar_coincidencias(nombre: str):
        query = re.sub(r"\s+\d+\s*$", "", str(nombre or "")).strip()
        cache_key = query.casefold()
        if cache_key not in search_cache:
            search_cache[cache_key] = buscar_emdn(query, database)
        return search_cache[cache_key]

    for record in dataset:
        original = record.get("emdn_code")
        nombre = record.get("nombre", "")
        state = "VALIDO"
        corrected = None
        observation = "Código verificado correctamente"

        if original in flat:
            validos += 1
        else:
            matches = buscar_coincidencias(nombre)
            if matches:
                corrected = matches[0][0]
                state = "CORREGIDO"
                corregidos += 1
                observation = f"Código original no existe en EMDN 2026. Sugerido {corrected} ({matches[0][2]})"
            else:
                state = "NO_ENCONTRADO"
                no_encontrados += 1
                observation = "No se encontró un código EMDN compatible. Requiere revisión manual."

        detalles.append(
            {
                "equipo": nombre,
                "emdn_original": original,
                "estado": state,
                "emdn_corregido": corrected,
                "observacion": observation,
            }
        )

    report = {
        "resumen": {
            "total_equipos": len(dataset),
            "validos": validos,
            "corregidos": corregidos,
            "no_encontrados": no_encontrados,
        },
        "detalles": detalles,
    }

    with open(PROCESSED_DIR / "discrepancias_report.json", "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    validated = []
    for record in dataset:
        original = record.get("emdn_code")
        if original in flat:
            validated.append(record)
            continue
        matches = buscar_coincidencias(record.get("nombre", ""))
        if matches:
            record["emdn_code"] = matches[0][0]
            record["observacion"] = matches[0][2]
        else:
            record.pop("emdn_code", None)
        validated.append(record)

    with open(PROCESSED_DIR / "equipos_demo_nlp.json", "w", encoding="utf-8") as file:
        json.dump(validated, file, ensure_ascii=False, indent=2)

    return report

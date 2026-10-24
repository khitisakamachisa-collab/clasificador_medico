from __future__ import annotations

import json
import re
from pathlib import Path

from .emdn_importer import buscar_emdn, load_emdn_database
from .utils import PROCESSED_DIR, RAW_DIR, ensure_directories


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

    with open(PROCESSED_DIR / "equipos_validados.json", "w", encoding="utf-8") as file:
        json.dump(validated, file, ensure_ascii=False, indent=2)

    return report

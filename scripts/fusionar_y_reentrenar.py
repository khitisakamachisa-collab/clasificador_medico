from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trainer import train_massive_model

PROCESSED_DIR = ROOT / "data" / "processed"
DEFAULT_PROPOSALS = PROCESSED_DIR / "propuestas_correccion.json"
DEFAULT_MASSIVE = PROCESSED_DIR / "equipos_validados_masivo.json"
DEFAULT_OUTPUT = PROCESSED_DIR / "equipos_entrenamiento_final.json"


def normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def read_json_list(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el archivo requerido: {path}")
    with path.open(encoding="utf-8") as file:
        content = json.load(file)
    if not isinstance(content, list):
        raise ValueError(f"El archivo debe contener una lista JSON: {path}")
    if any(not isinstance(record, dict) for record in content):
        raise ValueError(f"Todos los elementos deben ser objetos JSON: {path}")
    return content


def normalize_correction(proposal: dict) -> dict:
    name = str(proposal.get("nombre_equipo") or "").strip()
    category = str(proposal.get("categoria_actual_sugerida") or "").strip()
    code = str(proposal.get("emdn_propuesto") or "").strip()
    if not name or not category or not code:
        raise ValueError(
            "Cada propuesta aprobada debe incluir nombre_equipo, "
            "categoria_actual_sugerida y emdn_propuesto."
        )

    description = proposal.get("descripcion_emdn")
    return {
        "nombre": name,
        "marca": None,
        "ubicacion": None,
        "categoria_propia": category,
        "codigo_emdn": code,
        "descripcion_emdn": description,
        # Estos alias mantienen compatibilidad con los registros que consume trainer.py.
        "categoria": category,
        "emdn_code": code,
        "emdn_term": description,
        "estado": "VALIDADO",
        "source": "USER_CORRECTION",
    }


def merge_datasets(massive: list[dict], proposals: list[dict]) -> tuple[list[dict], int, int]:
    merged: dict[str, dict] = {}
    for record in massive:
        name = str(record.get("nombre") or record.get("nombre_equipo") or "").strip()
        identity = normalize_name(name)
        if not identity:
            raise ValueError("Cada registro del dataset masivo debe incluir nombre.")
        if identity not in merged:
            merged[identity] = {**record, "nombre": name}

    original_count = len(merged)
    approved = [
        proposal
        for proposal in proposals
        if proposal.get("accion_recomendada") == "APROBAR"
        and proposal.get("emdn_propuesto") is not None
    ]
    normalized_approved: dict[str, dict] = {}
    for proposal in approved:
        correction = normalize_correction(proposal)
        identity = normalize_name(correction["nombre"])
        normalized_approved[identity] = correction

    # Las propuestas aprobadas reemplazan el registro masivo con el mismo nombre normalizado.
    for identity, correction in normalized_approved.items():
        merged[identity] = {**merged.get(identity, {}), **correction}

    added_count = sum(identity not in {
        normalize_name(str(record.get("nombre") or record.get("nombre_equipo") or ""))
        for record in massive
    } for identity in normalized_approved)
    return list(merged.values()), original_count, added_count


def save_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fusiona correcciones aprobadas y reentrena el modelo NLP."
    )
    parser.add_argument("--propuestas", type=Path, default=DEFAULT_PROPOSALS)
    parser.add_argument("--masivo", type=Path, default=DEFAULT_MASSIVE)
    parser.add_argument("--salida", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-entrenar",
        action="store_true",
        help="Genera y valida el dataset sin entrenar el modelo.",
    )
    args = parser.parse_args()

    proposals = read_json_list(args.propuestas)
    massive = read_json_list(args.masivo)
    final_dataset, original_count, added_count = merge_datasets(massive, proposals)

    names = [normalize_name(record.get("nombre")) for record in final_dataset]
    if len(names) != len(set(names)):
        raise ValueError("La fusión produjo nombres duplicados.")
    if any(not record.get("categoria") for record in final_dataset):
        raise ValueError(
            "Cada registro final debe incluir categoria para ser compatible con trainer.py."
        )

    save_json(args.salida, final_dataset)
    print(f"Dataset final: {len(final_dataset)} equipos")
    print(f"Equipos del masivo original: {original_count}")
    print(f"Equipos nuevos agregados de correcciones: {added_count}")
    print(f"Archivo guardado: {args.salida}")

    if not args.no_entrenar:
        result = train_massive_model(dataset_path=args.salida)
        print(f"Reentrenamiento completado. Métricas: {result['metrics']}")


if __name__ == "__main__":
    main()

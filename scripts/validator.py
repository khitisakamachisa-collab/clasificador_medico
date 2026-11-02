from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import Config
from src.utils import PROCESSED_DIR
from src.validator import validate_suggestions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida sugerencias de clasificación contra el Excel EMDN oficial."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROCESSED_DIR / "sugerencias_ia_ejemplo.json",
        help="Archivo JSON de sugerencias (por defecto, el conjunto de ejemplo).",
    )
    parser.add_argument(
        "--excel",
        type=Path,
        default=Config.EMDN_EXCEL_PATH,
        help="Ruta del Excel oficial EMDN.",
    )
    parser.add_argument(
        "--valid-output",
        type=Path,
        default=PROCESSED_DIR / "equipos_validados.json",
        help="Salida exclusiva para registros validados.",
    )
    parser.add_argument(
        "--discrepancies-output",
        type=Path,
        default=PROCESSED_DIR / "discrepancias.json",
        help="Salida para registros que requieren revisión.",
    )
    arguments = parser.parse_args()

    report = validate_suggestions(
        input_path=arguments.input,
        emdn_path=arguments.excel,
        validated_output=arguments.valid_output,
        discrepancies_output=arguments.discrepancies_output,
    )
    print(
        f"Registros: {report['total']} | Validados: {report['validados']} | "
        f"Discrepancias: {report['discrepancias']}"
    )
    print(f"Dataset de entrenamiento: {report['equipos_validados']}")
    print(f"Revisión manual: {report['discrepancias_path']}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.classifier import classify_equipment
from src.emdn_importer import import_emdn_excel
from src.trainer import train_model
from src.validator import validate_equipment_dataset


def run_pipeline():
    print("[1/5] Importando base EMDN...")
    import_emdn_excel()
    print("[2/5] Validando dataset...")
    report = validate_equipment_dataset()
    print(f"Resumen: {report['resumen']}")
    print("[3/5] Entrenando modelo NLP...")
    metrics = train_model()
    print(f"Métricas: {metrics['metrics']}")
    print("[4/5] Probando 5 equipos de ejemplo...")
    ejemplos = [
        ("Ecógrafo Samsung WS80A", "Samsung", "Imagenología"),
        ("Monitor fetal Edan F6", "Edan", "Neonatología"),
        ("Ventilador respiratorio Dräger V500", "Dräger", "UTI"),
        ("Bomba de infusión Alaris GP", "BD", "Infusión"),
        ("Máquina de anestesia Aisys", "GE", "Quirófano"),
    ]
    for nombre, marca, ubicacion in ejemplos:
        print(classify_equipment(nombre, marca, ubicacion))
    print("[5/5] Sistema listo para uso vía API REST.")


if __name__ == "__main__":
    run_pipeline()

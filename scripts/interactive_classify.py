from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.classifier import classify_equipment


if __name__ == "__main__":
    while True:
        nombre = input("Nombre del equipo (o q para salir): ")
        if nombre.lower() in {"q", "quit", "salir"}:
            break
        marca = input("Marca (opcional): ")
        ubicacion = input("Ubicación (opcional): ")
        print(classify_equipment(nombre, marca or None, ubicacion or None))

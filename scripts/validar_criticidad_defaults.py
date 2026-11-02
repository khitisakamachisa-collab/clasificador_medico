from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.criticality import cargar_criticidad_defaults


if __name__ == "__main__":
    defaults = cargar_criticidad_defaults()
    for category, values in sorted(defaults.items()):
        print(f"{category}: IC {values['indice']:.2f} — {values['nombre']}")
    print(f"Validación correcta: {len(defaults)} categorías.")

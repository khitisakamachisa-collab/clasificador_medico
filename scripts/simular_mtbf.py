from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import Config
from src.criticality_store import asegurar_equipo, recalcular_por_mtbf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simula actualizaciones externas de MTBF en una base temporal."
    )
    parser.add_argument(
        "--mtbf-dias",
        nargs="+",
        type=float,
        default=[15, 400],
        help="Valores MTBF de prueba en días (predeterminado: 15 400).",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="simulacion-criticidad-") as directory:
        Config.CORRECTIONS_DB_PATH = Path(directory) / "criticidad.sqlite"
        results = []
        for index, mtbf_days in enumerate(args.mtbf_dias, start=1):
            equipment_id = f"SIM-MTBF-{index:02d}"
            baseline = asegurar_equipo(
                equipment_id,
                "RES-01",
                name=f"Ventilador de simulación {index}",
                location="UCI",
            )
            updated = recalcular_por_mtbf(equipment_id, mtbf_days)
            results.append(
                {
                    "equipo_id": equipment_id,
                    "mtbf_dias": mtbf_days,
                    "indice_inicial": baseline["indice"],
                    "historial_fallas": updated["criticidad"]["historial_fallas"],
                    "indice_actualizado": updated["criticidad"]["indice"],
                    "origen_historial": updated["criticidad"]["origen_historial"],
                }
            )
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

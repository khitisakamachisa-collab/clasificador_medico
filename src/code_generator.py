from __future__ import annotations

import json
import logging
import threading

from .utils import PROCESSED_DIR, ensure_directories


_SEQUENCE_PATH = PROCESSED_DIR / "internal_code_sequences.json"
_SEQUENCE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def generar_codigo_interno(categoria: str, equipos_existentes: list[str] | None = None) -> str:
    """Genera un código secuencial; persiste la secuencia si no se pasa una lista."""
    base = categoria.replace("-", "")
    if equipos_existentes is None:
        ensure_directories()
        with _SEQUENCE_LOCK:
            try:
                with open(_SEQUENCE_PATH, "r", encoding="utf-8") as file:
                    sequences = json.load(file)
            except FileNotFoundError:
                sequences = {}
            except json.JSONDecodeError as exc:
                logger.exception("El archivo de secuencias de códigos está dañado.")
                raise ValueError(
                    f"No se pueden generar códigos internos: {_SEQUENCE_PATH} no contiene JSON válido."
                ) from exc
            next_number = int(sequences.get(base, 0)) + 1
            sequences[base] = next_number
            temporary = _SEQUENCE_PATH.with_suffix(".tmp")
            with open(temporary, "w", encoding="utf-8") as file:
                json.dump(sequences, file, ensure_ascii=False, indent=2)
            temporary.replace(_SEQUENCE_PATH)
            return f"{base}-{next_number:03d}"

    matches = [code for code in equipos_existentes if code.startswith(base)]
    last = 0
    for code in matches:
        suffix = code.split("-")[-1]
        try:
            last = max(last, int(suffix))
        except ValueError:
            continue
    next_number = last + 1
    return f"{base}-{next_number:03d}"


def generate_internal_code(categoria: str, equipos_existentes: list[str] | None = None) -> str:
    return generar_codigo_interno(categoria, equipos_existentes)

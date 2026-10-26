from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

from .utils import DATA_DIR, MODELS_DIR, RAW_DIR


def _load_criticality_weights() -> dict[str, float]:
    default_weights = {
        "impacto_clinico": 0.40,
        "redundancia": 0.20,
        "frecuencia_uso": 0.15,
        "historial_fallas": 0.15,
        "costo_tiempo": 0.10,
    }
    raw_weights = os.getenv("CRITICALITY_WEIGHTS_JSON")
    if not raw_weights:
        return default_weights

    parsed = json.loads(raw_weights)
    if not isinstance(parsed, dict) or set(parsed) != set(default_weights):
        raise ValueError(
            "CRITICALITY_WEIGHTS_JSON debe incluir exactamente los cinco factores "
            "de criticidad documentados."
        )
    weights = {key: float(value) for key, value in parsed.items()}
    if (
        any(not math.isfinite(value) or value < 0 for value in weights.values())
        or abs(sum(weights.values()) - 1.0) > 1e-6
    ):
        raise ValueError("Los pesos de criticidad deben ser no negativos y sumar 1.")
    return weights


class Config:
    """Configuración centralizada; los valores se pueden sobrescribir con variables de entorno."""

    DATA_DIR = Path(os.getenv("DATA_DIR", str(DATA_DIR)))
    RAW_DIR = Path(os.getenv("RAW_DIR", str(RAW_DIR)))
    PROCESSED_DIR = Path(
        os.getenv("PROCESSED_DIR", str(DATA_DIR / "processed"))
    )
    MODELS_DIR = Path(os.getenv("MODELS_DIR", str(MODELS_DIR)))
    CORRECTIONS_DB_PATH = Path(
        os.getenv("CORRECTIONS_DB_PATH", str(DATA_DIR / "corrections.db"))
    )
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
    EMDN_EXCEL_PATH = Path(
        os.getenv(
            "EMDN_EXCEL_PATH",
            str(Path(os.getenv("RAW_DIR", str(RAW_DIR))) / "emdn_codes_2026.xlsx"),
        )
    )
    MODEL_VERSION = os.getenv("MODEL_VERSION", "v1")
    EMDN_VERSION = os.getenv("EMDN_VERSION", "2026")
    NLP_MODEL = os.getenv("SPACY_MODEL", "es_core_news_sm")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    NLP_CONFIDENCE_THRESHOLD = float(os.getenv("NLP_CONFIDENCE_THRESHOLD", "0.70"))
    LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.50"))
    CRITICALITY_WEIGHTS = _load_criticality_weights()
    CRITICALITY_LEVELS = {"ALTA": 4.0, "MEDIA": 2.5, "BAJA": 0.0}
    HOSPITAL_LOCATIONS = (
        "uci",
        "uti",
        "cuidados intensivos",
        "quirófano",
        "quirofano",
        "hospitalización",
        "hospitalizacion",
        "hospital",
        "emergencia",
        "urgencias",
        "radiología",
        "radiologia",
        "imagenología",
        "imagenologia",
        "cardiología",
        "cardiologia",
        "oncología",
        "oncologia",
        "pediatría",
        "pediatria",
        "neonatología",
        "neonatologia",
        "ucin",
        "área crítica",
        "area critica",
        "laboratorio",
        "farmacia",
        "esterilización",
        "esterilizacion",
        "endoscopía",
        "endoscopia",
        "diálisis",
        "dialisis",
        "consulta",
        "ambulatorio",
        "consultorio",
    )
    CORS_ORIGINS = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    )
    RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "120"))
    RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    BATCH_MAX_SIZE = int(os.getenv("BATCH_MAX_SIZE", "100"))

    if RATE_LIMIT_REQUESTS < 1 or RATE_LIMIT_WINDOW_SECONDS < 1 or BATCH_MAX_SIZE < 1:
        raise ValueError("Los límites de tasa y tamaño de lote deben ser enteros positivos.")
    if (
        not math.isfinite(NLP_CONFIDENCE_THRESHOLD)
        or not math.isfinite(LOW_CONFIDENCE_THRESHOLD)
        or not 0 <= NLP_CONFIDENCE_THRESHOLD <= 1
        or not 0 <= LOW_CONFIDENCE_THRESHOLD <= 1
    ):
        raise ValueError("Los umbrales de confianza deben estar entre 0 y 1.")
    if not isinstance(getattr(logging, LOG_LEVEL, None), int):
        raise ValueError(f"Nivel de logging no válido: {LOG_LEVEL}")

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from src.classifier import classify_equipment
from src.config import Config
from src.emdn_importer import buscar_emdn, load_emdn_database
from src.trainer import re_entrenar
from src.utils import CATEGORÍAS
from .schemas import (
    BatchClassificationRequest,
    ClassificationRequest,
    EMDNValidationRequest,
    RetrainRequest,
    SearchEMDNRequest,
)

router = APIRouter()


def _validate_emdn_code(emdn_code: str) -> dict:
    database = load_emdn_database()
    info = database.get("flat", {}).get(emdn_code)
    if not info:
        return {
            "exists": False,
            "emdn_code": emdn_code,
            "name": None,
            "term": None,
            "parent": None,
            "level": None,
        }
    return {"exists": True, "emdn_code": emdn_code, **info}


@router.post("/clasificar")
def clasificar(payload: ClassificationRequest):
    return classify_equipment(payload.nombre, payload.marca, payload.ubicacion)


@router.post("/validar")
@router.post("/validar-emdn")
def validar(payload: EMDNValidationRequest):
    return _validate_emdn_code(payload.emdn_code)


@router.post("/buscar-emdn")
def buscar_emdn_endpoint(payload: SearchEMDNRequest):
    db = load_emdn_database()
    matches = buscar_emdn(payload.keyword, db)
    return [{"code": code, "name": name, "score": score} for code, score, name in matches]


@router.post("/batch-clasificar")
def batch_clasificar(payload: BatchClassificationRequest):
    results = [
        classify_equipment(equipo.nombre, equipo.marca, equipo.ubicacion)
        for equipo in payload.equipos
    ]
    return {"total": len(results), "resultados": results}


@router.get("/categorias")
def categorias():
    return [
        {
            "categoria": key,
            "nombre": value["nombre"],
            "mdr_default": value["mdr_default"],
            "defaults": value["defaults"],
        }
        for key, value in CATEGORÍAS.items()
    ]


@router.get("/metricas")
def metricas():
    metrics_path = Config.MODELS_DIR / f"metrics_{Config.MODEL_VERSION}.json"
    if not metrics_path.exists():
        raise HTTPException(
            status_code=503,
            detail="Métricas no disponibles. Ejecuta el pipeline de preparación primero.",
        )
    with open(metrics_path, "r", encoding="utf-8") as file:
        return json.load(file)


@router.post("/reentrenar")
def reentrenar(payload: RetrainRequest):
    nuevos = payload.nuevos_ejemplos or []
    response = re_entrenar(nuevos)
    return response


@router.get("/health")
def health():
    database = load_emdn_database()
    dataset_path = Config.PROCESSED_DIR / "equipos_validados.json"
    example_count = 0
    if dataset_path.exists():
        with open(dataset_path, "r", encoding="utf-8") as file:
            example_count = len(json.load(file))
    return {
        "status": "ok",
        "model_version": Config.MODEL_VERSION,
        "emdn_version": Config.EMDN_VERSION,
        "emdn_available": database.get("available", False),
        "ejemplos_entrenamiento": example_count,
    }

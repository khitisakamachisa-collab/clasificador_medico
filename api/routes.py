from __future__ import annotations

import json
import math
import secrets

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from src.classifier import classify_equipment, obtener_semaforo
from src.config import Config
from src.corrections import (
    get_correction,
    list_audit_logs,
    list_corrections,
    record_audit,
    review_correction,
    save_correction,
    validate_saved_corrections,
)
from src.correction_validation import validar_correccion_automaticamente
from src.emdn_importer import buscar_emdn, load_emdn_database
from src.trainer import re_entrenar
from src.utils import CATEGORÍAS
from .schemas import (
    BatchClassificationRequest,
    ClassificationRequest,
    RecalculateRequest,
    RegisterCorrectionRequest,
    EMDNValidationRequest,
    RejectCorrectionRequest,
    RequestInformationRequest,
    RetrainRequest,
    SearchEMDNRequest,
)

router = APIRouter()


def _require_admin(
    request: Request,
    x_admin_key: str | None = Header(default=None),
    x_admin_user: str | None = Header(default=None),
) -> str:
    """Valida el secreto de administración y obtiene la identidad auditada."""
    configured_key = Config.ADMIN_API_KEY
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="El acceso administrativo no está configurado en el servidor.",
        )
    if not x_admin_key or not secrets.compare_digest(x_admin_key, configured_key):
        raise HTTPException(status_code=403, detail="Se requiere autenticación de administrador.")
    if not x_admin_user or not x_admin_user.strip():
        raise HTTPException(status_code=400, detail="El nombre del administrador es obligatorio.")
    request.state.admin_user = x_admin_user.strip()
    return x_admin_user.strip()


def _request_audit_metadata(request: Request) -> dict[str, str | None]:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


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
    result = classify_equipment(payload.nombre, payload.marca, payload.ubicacion)
    if payload.cmms_equipment_id:
        result["cmms_equipment_id"] = payload.cmms_equipment_id
    return result


@router.post("/recalcular")
def recalcular(payload: RecalculateRequest, request: Request):
    result = classify_equipment(
        payload.nombre,
        payload.marca,
        payload.ubicacion,
        categoria_forzada=payload.categoria_forzada,
    )
    validation = validar_correccion_automaticamente(result, nombre_equipo=payload.nombre)
    result["validacion_correccion"] = validation
    result["metodo"] = "CORRECCION_MANUAL"
    result["confidence"] = 0.95
    result["semaforo"] = obtener_semaforo(result["confidence"])
    result["semaforo"]["mensaje"] = "Validado manualmente por experto biomédico"
    if payload.cmms_equipment_id:
        result["cmms_equipment_id"] = payload.cmms_equipment_id
    record_audit(
        user=payload.usuario or "USUARIO",
        action="CORREGIR",
        entity="EQUIPO",
        old_data={"categoria": None},
        new_data={
            "nombre": payload.nombre,
            "categoria": result["categoria_propia"],
            "validacion": validation,
        },
        **_request_audit_metadata(request),
    )
    return result


@router.post("/registrar-correccion")
def registrar_correccion(payload: RegisterCorrectionRequest, request: Request):
    original = payload.entrada_original.model_dump()
    corrected = payload.resultado_corregido
    if corrected.get("categoria_propia") != payload.categoria_correcta:
        raise HTTPException(
            status_code=400,
            detail="La categoría del resultado corregido no coincide con categoria_correcta.",
        )
    confidence = corrected.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise HTTPException(
            status_code=400,
            detail="El resultado corregido debe incluir una confianza válida entre 0 y 1.",
        )
    if confidence < 0.75:
        raise HTTPException(
            status_code=400,
            detail="No se puede guardar una corrección con menos de 2 validaciones coherentes.",
        )
    recalculated = classify_equipment(
        original["nombre"],
        original.get("marca"),
        original.get("ubicacion"),
        categoria_forzada=payload.categoria_correcta,
    )
    validation = validar_correccion_automaticamente(
        recalculated, nombre_equipo=original["nombre"]
    )
    recalculated["validacion_correccion"] = validation
    manual_correction = (
        corrected.get("metodo") == "CORRECCION_MANUAL" and confidence == 0.95
    )
    if manual_correction:
        recalculated["metodo"] = "CORRECCION_MANUAL"
        recalculated["confidence"] = 0.95
        recalculated["semaforo"] = obtener_semaforo(0.95)
        recalculated["semaforo"]["mensaje"] = "Validado manualmente"
    else:
        recalculated["confidence"] = validation["confidence"]
        recalculated["semaforo"] = obtener_semaforo(validation["confidence"])
        recalculated["semaforo"]["mensaje"] = validation["mensaje"]
    if (
        recalculated["categoria_propia"] != payload.categoria_correcta
        or (
            not manual_correction
            and (
                recalculated["confidence"] < 0.75
                or abs(recalculated["confidence"] - confidence) > 1e-6
            )
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="No se puede guardar una corrección con menos de 2 validaciones coherentes.",
        )
    correction_id = save_correction(
        original,
        payload.categoria_correcta,
        recalculated,
        payload.usuario,
    )
    record_audit(
        user=payload.usuario or "USUARIO",
        action="CORREGIR",
        entity="CORRECCION",
        entity_id=str(correction_id),
        new_data=recalculated,
        **_request_audit_metadata(request),
    )
    return {
        "status": "ok",
        "correction_id": correction_id,
        "source": "USER_CORRECTION",
        "estado": "PENDIENTE_REVISION" if manual_correction else validation["estado"],
        "cmms_equipment_id": original.get("cmms_equipment_id"),
        "resultado_corregido": recalculated,
    }


@router.get("/correcciones/pendientes-revision")
def correcciones_pendientes(
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(request, x_admin_key, x_admin_user)
    return list_corrections("PENDIENTE")


@router.get("/correcciones/revisadas")
def correcciones_revisadas(
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(request, x_admin_key=x_admin_key, x_admin_user=x_admin_user)
    return list_corrections("APROBADA") + list_corrections("RECHAZADA")


@router.post("/correcciones/{correction_id}/aprobar")
def aprobar_correccion(
    correction_id: int,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    user = _require_admin(request, x_admin_key, x_admin_user)
    try:
        correction = review_correction(
            correction_id,
            action="APROBAR",
            user=user,
            **_request_audit_metadata(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if correction is None:
        raise HTTPException(status_code=404, detail="No se encontró la corrección solicitada.")
    return {"status": "ok", "estado": correction["estado"], "correccion": correction}


@router.post("/correcciones/{correction_id}/rechazar")
def rechazar_correccion(
    correction_id: int,
    payload: RejectCorrectionRequest,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    user = _require_admin(request, x_admin_key, x_admin_user)
    try:
        correction = review_correction(
            correction_id,
            action="RECHAZAR",
            user=user,
            reason=payload.motivo_rechazo,
            **_request_audit_metadata(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if correction is None:
        raise HTTPException(status_code=404, detail="No se encontró la corrección solicitada.")
    return {"status": "ok", "estado": correction["estado"], "correccion": correction}


@router.post("/correcciones/{correction_id}/solicitar-informacion")
def solicitar_informacion_correccion(
    correction_id: int,
    payload: RequestInformationRequest,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    user = _require_admin(request, x_admin_key, x_admin_user)
    try:
        correction = review_correction(
            correction_id,
            action="SOLICITAR_INFORMACION",
            user=user,
            reason=payload.nota,
            **_request_audit_metadata(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if correction is None:
        raise HTTPException(status_code=404, detail="No se encontró la corrección solicitada.")
    return {"status": "ok", "estado": correction["estado"], "correccion": correction}


@router.get("/audit-log")
def audit_log(
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(request, x_admin_key=x_admin_key, x_admin_user=x_admin_user)
    return list_audit_logs()


@router.get("/correcciones/{correction_id}")
def consultar_correccion(correction_id: int):
    correction = get_correction(correction_id)
    if correction is None:
        raise HTTPException(status_code=404, detail="No se encontró la corrección solicitada.")
    return correction


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
    results = []
    for equipo in payload.equipos:
        result = classify_equipment(equipo.nombre, equipo.marca, equipo.ubicacion)
        if equipo.cmms_equipment_id:
            result["cmms_equipment_id"] = equipo.cmms_equipment_id
        results.append(result)
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
def reentrenar(
    payload: RetrainRequest,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    user = _require_admin(request, x_admin_key, x_admin_user)
    if not payload.validar_correcciones:
        raise HTTPException(
            status_code=400,
            detail="El reentrenamiento requiere validar las correcciones guardadas.",
        )
    approved_count = validate_saved_corrections()
    if approved_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No hay correcciones guardadas para reentrenar.",
        )
    if approved_count < 10:
        raise HTTPException(
            status_code=400,
            detail=(
                "Se necesitan al menos 10 correcciones aprobadas para reentrenar. "
                f"Actualmente: {approved_count}"
            ),
        )
    try:
        response = re_entrenar(
            validar_correcciones=payload.validar_correcciones,
            nueva_version=payload.nueva_version,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudieron validar las correcciones guardadas.",
        ) from exc
    record_audit(
        user=user,
        action="REENTRENAR",
        entity="MODELO",
        entity_id=response.get("modelo_activo"),
        new_data=response,
        **_request_audit_metadata(request),
    )
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

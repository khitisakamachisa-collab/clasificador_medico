from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import json
import math
import re
import secrets
import unicodedata
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
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
from src.criticality import cargar_criticidad_defaults
from src.criticality_store import (
    ajustar_criticidad,
    asegurar_equipo,
    listar_ajustes,
    obtener_criticidad,
    recalcular_por_mtbf,
    reporte_distribucion,
)
from src.emdn_importer import buscar_emdn, load_emdn_database
from src.rules_dictionary import EMDN_ADDITIONAL_CATEGORY_PREFIXES, EMDN_PREFIXES
from src.trainer import re_entrenar
from src.utils import CATEGORÍAS, CATEGORY_KEYWORDS
from .schemas import (
    BatchClassificationRequest,
    ClassificationRequest,
    AdjustCriticalityRequest,
    MTBFRequest,
    RecalculateRequest,
    RegisterCorrectionRequest,
    EMDNValidationRequest,
    RejectCorrectionRequest,
    RequestInformationRequest,
    RetrainRequest,
    SearchEMDNRequest,
)

router = APIRouter()


def _normalize_search_text(value: str) -> str:
    """Normaliza términos de búsqueda quitando tildes y signos de puntuación."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    tokens = re.sub(r"[^a-z0-9]+", " ", without_accents).split()
    stopwords = {"a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "para", "por", "y"}
    return " ".join(token for token in tokens if token not in stopwords)


def build_emdn_search_index(database: dict) -> dict[str, Any]:
    """Prepara términos y trigramas una sola vez al iniciar la API."""
    records = []
    trigrams: dict[str, set[int]] = defaultdict(set)
    categories: dict[str, list[int]] = defaultdict(list)
    synonyms_path = Config.DATA_DIR / "rules" / "sinonimos_medico.json"
    synonyms = {}
    if synonyms_path.is_file():
        with synonyms_path.open("r", encoding="utf-8") as file:
            synonym_data = json.load(file)
        if not isinstance(synonym_data, dict):
            raise ValueError("El diccionario de sinónimos médicos debe ser un objeto JSON.")
        for term, alternatives in synonym_data.items():
            if (
                not isinstance(term, str)
                or not isinstance(alternatives, list)
                or any(not isinstance(synonym, str) for synonym in alternatives)
            ):
                raise ValueError("El diccionario de sinónimos médicos tiene una entrada inválida.")
            normalized_term = _normalize_search_text(term)
            normalized_alternatives = [
                _normalize_search_text(synonym)
                for synonym in alternatives
                if _normalize_search_text(synonym)
            ]
            if normalized_term:
                synonyms[normalized_term] = normalized_alternatives
    category_prefixes = [
        (prefix, category)
        for category, prefix in EMDN_PREFIXES.items()
    ]
    category_prefixes.extend(
        (prefix, category)
        for category, prefixes in EMDN_ADDITIONAL_CATEGORY_PREFIXES.items()
        for prefix in prefixes
    )
    category_prefixes.sort(key=lambda item: len(item[0]), reverse=True)

    for code, item in database.get("flat", {}).items():
        term = str(item.get("term") or item.get("name") or "")
        normalized_term = _normalize_search_text(term)
        category = next(
            (category for prefix, category in category_prefixes if code.startswith(prefix)),
            None,
        )
        record = {
            "codigo_emdn": code,
            "termino_emdn": term,
            "categoria_propia": category,
            "clase_mdr": CATEGORÍAS.get(category, {}).get("mdr_default"),
            "nivel_terminal": item.get("terminal_level") == "YES",
            "_termino_normalizado": normalized_term,
        }
        record_index = len(records)
        records.append(record)
        if category:
            categories[category].append(record_index)
        for position in range(max(0, len(normalized_term) - 2)):
            trigrams[normalized_term[position : position + 3]].add(record_index)

    return {
        "records": records,
        "trigrams": dict(trigrams),
        "categories": dict(categories),
        "synonyms": synonyms,
    }


def _search_category(query: str) -> str | None:
    normalized_query = _normalize_search_text(query)
    for category in CATEGORÍAS:
        if normalized_query == _normalize_search_text(category):
            return category
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(
            normalized_query in _normalize_search_text(keyword)
            or _normalize_search_text(keyword) in normalized_query
            for keyword in keywords
            if len(normalized_query) >= 3
        ):
            return category
    return None


def _public_search_result(record: dict[str, Any], similarity: float) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if not key.startswith("_")
    } | {"similitud": round(similarity, 4)}


def _find_emdn_matches(search_index: dict[str, Any], query: str, limit: int):
    normalized_query = _normalize_search_text(query)
    records = search_index["records"]
    if not normalized_query:
        return []

    if re.fullmatch(r"[a-z]\d+", normalized_query):
        matches = [
            record for record in records
            if record["codigo_emdn"].lower().startswith(normalized_query)
        ]
        return [_public_search_result(record, 1.0) for record in matches[:limit]]

    category = _search_category(query)
    if category and normalized_query == _normalize_search_text(category):
        candidates = [
            record for record in records if record["categoria_propia"] == category
        ]
        return [_public_search_result(record, 1.0) for record in candidates[:limit]]

    search_terms = [normalized_query]
    for synonym, alternatives in search_index["synonyms"].items():
        if normalized_query in synonym or synonym in normalized_query:
            search_terms.extend(alternatives)
    search_terms = list(dict.fromkeys(search_terms))

    ngram_counts: Counter[int] = Counter()
    for search_term in search_terms:
        if len(search_term) >= 3:
            for position in range(len(search_term) - 2):
                ngram_counts.update(search_index["trigrams"].get(
                    search_term[position : position + 3], ()
                ))
        else:
            ngram_counts.update(
                index
                for index, record in enumerate(records)
                if search_term in record["_termino_normalizado"]
            )

    if category:
        category_indexes = search_index["categories"].get(category, ())
        candidate_indexes = sorted(
            category_indexes,
            key=lambda index: ngram_counts.get(index, 0),
            reverse=True,
        )[:400]
    else:
        candidate_indexes = [
            index for index, _ in ngram_counts.most_common(400)
        ]

    matches = []
    for index in candidate_indexes:
        record = records[index]
        similarity = max(
            max(
                SequenceMatcher(None, search_term, record["_termino_normalizado"]).ratio(),
                max(
                    (
                        SequenceMatcher(None, search_term, token).ratio()
                        for token in record["_termino_normalizado"].split()
                    ),
                    default=0.0,
                ),
            )
            for search_term in search_terms
        )
        if similarity >= 0.25 or category and record["categoria_propia"] == category:
            exact_term_match = any(
                search_term in record["_termino_normalizado"]
                for search_term in search_terms
            )
            matches.append((exact_term_match, similarity, record))
    matches.sort(
        key=lambda match: (
            not match[0],
            -match[1],
            match[2]["codigo_emdn"],
        )
    )
    return [
        _public_search_result(record, similarity)
        for _, similarity, record in matches[:limit]
    ]


def _apply_equipment_criticality(
    result: dict[str, Any],
    equipment_id: str | None,
    name: str,
    location: str | None,
    allow_category_change: bool = False,
) -> str:
    identifier = equipment_id or result.get("codigo_interno") or uuid.uuid4().hex
    try:
        profile = asegurar_equipo(
            identifier,
            result["categoria_propia"],
            name,
            location,
            permitir_cambio_categoria=allow_category_change,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result["criticidad"] = {
        key: value
        for key, value in profile.items()
        if key not in {"categoria", "defaults"}
    }
    result["equipo_id"] = identifier
    return identifier


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
    _apply_equipment_criticality(
        result, payload.cmms_equipment_id, payload.nombre, payload.ubicacion
    )
    return result


@router.post("/recalcular")
def recalcular(payload: RecalculateRequest, request: Request):
    result = classify_equipment(
        payload.nombre,
        payload.marca,
        payload.ubicacion,
        categoria_forzada=payload.categoria_forzada,
    )
    if payload.cmms_equipment_id:
        result["cmms_equipment_id"] = payload.cmms_equipment_id
    equipment_id = _apply_equipment_criticality(
        result,
        payload.cmms_equipment_id,
        payload.nombre,
        payload.ubicacion,
        allow_category_change=True,
    )
    validation = validar_correccion_automaticamente(
        result, nombre_equipo=payload.nombre, equipo_id=equipment_id
    )
    result["validacion_correccion"] = validation
    result["metodo"] = "CORRECCION_MANUAL"
    if validation["validaciones"]["semantica_valida"]:
        result["confidence"] = 0.95
        result["semaforo"] = obtener_semaforo(result["confidence"])
        result["semaforo"]["mensaje"] = "Validado manualmente por experto biomédico"
    else:
        result["confidence"] = validation["confidence"]
        result["semaforo"] = obtener_semaforo(validation["confidence"])
        result["semaforo"]["mensaje"] = validation["mensaje"]
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
    original_equipment_id = (
        original.get("cmms_equipment_id") or recalculated.get("codigo_interno")
    )
    recalculated["cmms_equipment_id"] = original.get("cmms_equipment_id")
    equipment_id = _apply_equipment_criticality(
        recalculated,
        original_equipment_id,
        original["nombre"],
        original.get("ubicacion"),
        allow_category_change=True,
    )
    validation = validar_correccion_automaticamente(
        recalculated, nombre_equipo=original["nombre"], equipo_id=equipment_id
    )
    recalculated["validacion_correccion"] = validation
    if not validation["validaciones"]["semantica_valida"]:
        raise HTTPException(status_code=400, detail=validation["mensaje"])

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


@router.get("/buscar")
def buscar_emdn_autocomplete(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
):
    """Busca códigos terminales por término, código o categoría propia."""
    return _find_emdn_matches(request.app.state.emdn_search_index, q, limit)


@router.post("/batch-clasificar")
def batch_clasificar(payload: BatchClassificationRequest):
    results = []
    for equipo in payload.equipos:
        result = classify_equipment(equipo.nombre, equipo.marca, equipo.ubicacion)
        if equipo.cmms_equipment_id:
            result["cmms_equipment_id"] = equipo.cmms_equipment_id
        _apply_equipment_criticality(
            result, equipo.cmms_equipment_id, equipo.nombre, equipo.ubicacion
        )
        results.append(result)
    return {"total": len(results), "resultados": results}


@router.get("/categorias")
def categorias():
    defaults = cargar_criticidad_defaults()
    return [
        {
            "categoria": key,
            "nombre": value["nombre"],
            "mdr_default": value["mdr_default"],
            "defaults": {
                field: defaults[key][field]
                for field in (
                    "impacto_clinico",
                    "redundancia",
                    "frecuencia_uso",
                    "historial_fallas",
                    "costo_tiempo",
                )
            },
        }
        for key, value in CATEGORÍAS.items()
    ]


@router.post("/admin/auth")
def validar_acceso_admin(
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    """Valida las credenciales administrativas con el mismo control de las acciones protegidas."""
    user = _require_admin(request, x_admin_key, x_admin_user)
    return {"status": "ok", "usuario": user}


@router.post("/criticidad/ajustar")
def ajustar_criticidad_endpoint(
    payload: AdjustCriticalityRequest,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    user = _require_admin(request, x_admin_key, x_admin_user)
    try:
        profile, changed = ajustar_criticidad(
            payload.equipo_id,
            payload.valores.model_dump(),
            user,
            payload.justificacion,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not changed:
        return {"status": "sin_cambios", "criticidad": profile}
    return {"status": "ok", "criticidad": profile}


@router.get("/criticidad/reportes/distribucion")
def criticidad_reporte_distribucion():
    return reporte_distribucion()


@router.get("/criticidad/reportes/auditoria")
def criticidad_reporte_auditoria(
    request: Request,
    usuario: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
    equipo_id: str | None = None,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(request, x_admin_key, x_admin_user)
    for label, value in (("fecha_inicio", fecha_inicio), ("fecha_fin", fecha_fin)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"{label} debe tener formato YYYY-MM-DD."
                ) from exc
    return listar_ajustes(equipo_id, usuario, fecha_inicio, fecha_fin)


@router.get("/criticidad/{equipo_id}/auditoria")
def criticidad_equipo_auditoria(
    equipo_id: str,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(request, x_admin_key, x_admin_user)
    if not obtener_criticidad(equipo_id):
        raise HTTPException(status_code=404, detail="No se encontró el equipo.")
    return listar_ajustes(equipment_id=equipo_id)


@router.get("/criticidad/{equipo_id}")
def criticidad_equipo(equipo_id: str):
    profile = obtener_criticidad(equipo_id)
    if not profile:
        raise HTTPException(status_code=404, detail="No se encontró el equipo.")
    return {
        **profile,
        "historial_ajustes": listar_ajustes(equipment_id=equipo_id),
    }


@router.post("/criticidad/mtbf")
def criticidad_actualizar_mtbf(
    payload: MTBFRequest,
    request: Request,
    x_admin_user: str = Header(default=""),
    x_admin_key: str | None = Header(default=None),
):
    admin_user = payload.administrador or x_admin_user.strip() or "SISTEMA"
    user = _require_admin(request, x_admin_key, admin_user)
    records = (
        payload.equipos
        if payload.equipos is not None
        else [{"equipo_id": payload.equipo_id, "mtbf_dias": payload.mtbf_dias}]
    )
    for record in records:
        equipment_id = (
            record.equipo_id if hasattr(record, "equipo_id") else record["equipo_id"]
        )
        if not obtener_criticidad(equipment_id):
            raise HTTPException(
                status_code=404, detail=f"No se encontró el equipo {equipment_id}."
            )
    details = []
    for record in records:
        try:
            details.append(
                recalcular_por_mtbf(
                    record.equipo_id if hasattr(record, "equipo_id") else record["equipo_id"],
                    record.mtbf_dias if hasattr(record, "mtbf_dias") else record["mtbf_dias"],
                    user,
                )
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "actualizados": sum(item["actualizado"] for item in details),
        "omitidos": sum(item["omitido"] for item in details),
        "detalle": details,
    }


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

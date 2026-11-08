import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api import routes
from api.main import app
from src import code_generator
from src.config import Config
from src.criticality import obtener_valores_por_defecto
from src import corrections
from src.utils import CATEGORÍAS, MODELS_DIR

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key", "X-Admin-User": "test-admin"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(code_generator, "_SEQUENCE_PATH", tmp_path / "sequences.json")
    monkeypatch.setattr(Config, "CORRECTIONS_DB_PATH", tmp_path / "corrections.sqlite")
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "test-admin-key")
    api_main._rate_windows.clear()
    with TestClient(app) as test_client:
        yield test_client


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


def test_locations_endpoint_returns_classifier_locations(client):
    response = client.get("/api/v1/ubicaciones")

    assert response.status_code == 200
    assert "radiología" in response.json()
    assert "uci" in response.json()
    assert "quirófano general" in response.json()


def _classify_with_equipment_id(client, equipment_id, name="Ventilador mecánico"):
    response = client.post(
        "/api/v1/clasificar",
        json={"nombre": name, "cmms_equipment_id": equipment_id},
    )
    assert response.status_code == 200
    return response.json()


def test_criticality_response_preserves_fields_and_adds_radar_data(client):
    result = _classify_with_equipment_id(client, "ACT-CRIT-1")
    criticality = result["criticidad"]
    assert result["equipo_id"] == "ACT-CRIT-1"
    assert {
        "impacto_clinico",
        "redundancia",
        "frecuencia_uso",
        "historial_fallas",
        "costo_tiempo",
        "indice",
        "nivel",
    }.issubset(criticality)
    assert len(criticality["radar_data"]) == 5
    assert len(criticality["contribuciones"]) == 5
    assert criticality["radar_data"][0]["peso"] == 0.4


def test_admin_authentication_endpoint_and_admin_actions_share_one_key(client, monkeypatch):
    wrong_headers = {"X-Admin-Key": "wrong-key", "X-Admin-User": "test-admin"}
    rejected_auth = client.post("/api/v1/admin/auth", headers=wrong_headers)
    rejected_retrain = client.post(
        "/api/v1/reentrenar",
        headers=wrong_headers,
        json={"validar_correcciones": True, "nueva_version": "v2"},
    )
    assert rejected_auth.status_code == rejected_retrain.status_code == 403
    assert rejected_auth.json()["detail"] == rejected_retrain.json()["detail"]

    authorized = client.post("/api/v1/admin/auth", headers=ADMIN_HEADERS)
    assert authorized.status_code == 200
    assert authorized.json() == {"status": "ok", "usuario": "test-admin"}

    monkeypatch.setattr(routes, "validate_saved_corrections", lambda: 10)
    monkeypatch.setattr(
        routes,
        "re_entrenar",
        lambda **kwargs: {
            "status": "ok",
            "modelo_activo": "v2",
            "nuevos_totales": 14,
            "accuracy": 0.88,
            "correcciones_validadas": 10,
        },
    )
    retrained = client.post(
        "/api/v1/reentrenar",
        headers=ADMIN_HEADERS,
        json={"validar_correcciones": True, "nueva_version": "v2"},
    )
    assert retrained.status_code == 200

    _classify_with_equipment_id(client, "ACT-ADMIN-AUTH")
    values = {
        "impacto_clinico": 3,
        "redundancia": 3,
        "frecuencia_uso": 5,
        "historial_fallas": 3,
        "costo_tiempo": 3,
    }
    adjusted = client.post(
        "/api/v1/criticidad/ajustar",
        headers=ADMIN_HEADERS,
        json={
            "equipo_id": "ACT-ADMIN-AUTH",
            "valores": values,
            "usuario": "test-admin",
            "justificacion": "Evaluación validada por el administrador.",
        },
    )
    assert adjusted.status_code == 200


def test_manual_criticality_adjustment_requires_justification_and_is_audited(client):
    result = _classify_with_equipment_id(client, "ACT-CRIT-2")
    values = {
        key: result["criticidad"][key]
        for key in (
            "impacto_clinico",
            "redundancia",
            "frecuencia_uso",
            "historial_fallas",
            "costo_tiempo",
        )
    }
    values["impacto_clinico"] = 3
    payload = {
        "equipo_id": "ACT-CRIT-2",
        "valores": values,
        "usuario": "biomedico",
        "justificacion": "",
    }
    missing = client.post(
        "/api/v1/criticidad/ajustar", json=payload, headers=ADMIN_HEADERS
    )
    assert missing.status_code == 422
    payload["justificacion"] = "breve"
    short = client.post(
        "/api/v1/criticidad/ajustar", json=payload, headers=ADMIN_HEADERS
    )
    assert short.status_code == 422
    assert client.get("/api/v1/criticidad/ACT-CRIT-2").json()["impacto_clinico"] == 5

    payload["justificacion"] = "Evaluación clínica de impacto asistencial."
    saved = client.post(
        "/api/v1/criticidad/ajustar", json=payload, headers=ADMIN_HEADERS
    )
    assert saved.status_code == 200
    assert saved.json()["criticidad"]["impacto_clinico"] == 3
    assert saved.json()["criticidad"]["ajustado_manualmente"] is True
    audit = client.get(
        "/api/v1/criticidad/ACT-CRIT-2/auditoria", headers=ADMIN_HEADERS
    )
    assert audit.status_code == 200
    assert any(row["origen"] == "MANUAL" for row in audit.json())

    payload["justificacion"] = ""
    no_op = client.post(
        "/api/v1/criticidad/ajustar", json=payload, headers=ADMIN_HEADERS
    )
    assert no_op.status_code == 200
    assert no_op.json()["status"] == "sin_cambios"
    refreshed_audit = client.get(
        "/api/v1/criticidad/ACT-CRIT-2/auditoria", headers=ADMIN_HEADERS
    )
    assert sum(row["origen"] == "MANUAL" for row in refreshed_audit.json()) == 1


def test_criticality_adjustment_rejects_out_of_range_values(client):
    _classify_with_equipment_id(client, "ACT-CRIT-3")
    values = obtener_valores_por_defecto("RES-01")
    values["impacto_clinico"] = 0
    response = client.post(
        "/api/v1/criticidad/ajustar",
        headers=ADMIN_HEADERS,
        json={
            "equipo_id": "ACT-CRIT-3",
            "valores": values,
            "usuario": "biomedico",
            "justificacion": "Cambio justificado por revisión.",
        },
    )
    assert response.status_code == 422


def test_mtbf_updates_values_and_respects_recent_manual_history(client):
    first = _classify_with_equipment_id(client, "ACT-MTBF-1")
    baseline = first["criticidad"]["indice"]
    low_mtbf = client.post(
        "/api/v1/criticidad/mtbf",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"equipo_id": "ACT-MTBF-1", "mtbf_dias": 15},
    )
    assert low_mtbf.status_code == 200
    assert low_mtbf.json()["detalle"][0]["criticidad"]["historial_fallas"] == 5
    assert low_mtbf.json()["detalle"][0]["criticidad"]["indice"] > baseline
    default_audit = client.get(
        "/api/v1/criticidad/ACT-MTBF-1/auditoria", headers=ADMIN_HEADERS
    )
    assert any(
        row["usuario"] == "SISTEMA" and row["origen"] == "MTBF"
        for row in default_audit.json()
    )

    _classify_with_equipment_id(client, "ACT-MTBF-EXPLICIT")
    explicit_mtbf = client.post(
        "/api/v1/criticidad/mtbf",
        headers={"X-Admin-Key": "test-admin-key"},
        json={
            "equipo_id": "ACT-MTBF-EXPLICIT",
            "mtbf_dias": 15,
            "administrador": "auditor-mtbf",
        },
    )
    assert explicit_mtbf.status_code == 200
    explicit_audit = client.get(
        "/api/v1/criticidad/ACT-MTBF-EXPLICIT/auditoria", headers=ADMIN_HEADERS
    )
    assert any(
        row["usuario"] == "auditor-mtbf" and row["origen"] == "MTBF"
        for row in explicit_audit.json()
    )

    second = _classify_with_equipment_id(client, "ACT-MTBF-2")
    baseline_high_mtbf = second["criticidad"]["indice"]
    high_mtbf = client.post(
        "/api/v1/criticidad/mtbf",
        headers=ADMIN_HEADERS,
        json={"equipo_id": "ACT-MTBF-2", "mtbf_dias": 400},
    )
    assert high_mtbf.status_code == 200
    assert high_mtbf.json()["detalle"][0]["criticidad"]["historial_fallas"] == 1
    assert high_mtbf.json()["detalle"][0]["criticidad"]["indice"] < baseline_high_mtbf

    values = {
        key: second["criticidad"][key]
        for key in (
            "impacto_clinico",
            "redundancia",
            "frecuencia_uso",
            "historial_fallas",
            "costo_tiempo",
        )
    }
    values["historial_fallas"] = 4
    adjusted = client.post(
        "/api/v1/criticidad/ajustar",
        headers=ADMIN_HEADERS,
        json={
            "equipo_id": "ACT-MTBF-2",
            "valores": values,
            "usuario": "biomedico",
            "justificacion": "Inspección reciente del equipo.",
        },
    )
    assert adjusted.status_code == 200
    omitted = client.post(
        "/api/v1/criticidad/mtbf",
        headers=ADMIN_HEADERS,
        json={"equipo_id": "ACT-MTBF-2", "mtbf_dias": 15},
    )
    assert omitted.status_code == 200
    assert omitted.json()["omitidos"] == 1
    assert omitted.json()["detalle"][0]["motivo"] == (
        "MTBF_OMITIDO_POR_AJUSTE_MANUAL_RECIENTE"
    )

    with sqlite3.connect(Config.CORRECTIONS_DB_PATH) as connection:
        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        connection.execute(
            "UPDATE criticidad_ajustes SET timestamp=? "
            "WHERE equipo_id=? AND origen='MANUAL'",
            (old_timestamp, "ACT-MTBF-2"),
        )
    updated = client.post(
        "/api/v1/criticidad/mtbf",
        headers=ADMIN_HEADERS,
        json={"equipo_id": "ACT-MTBF-2", "mtbf_dias": 15},
    )
    assert updated.status_code == 200
    assert updated.json()["actualizados"] == 1
    assert updated.json()["detalle"][0]["criticidad"]["historial_fallas"] == 5


def test_criticality_reports_and_admin_audit_filters(client):
    _classify_with_equipment_id(client, "ACT-REPORT-1")
    report = client.get("/api/v1/criticidad/reportes/distribucion")
    assert report.status_code == 200
    assert report.json()["total"] == 1
    assert sum(report.json()["por_nivel"].values()) == 1
    assert report.json()["top_criticos"][0]["equipo"] == "ACT-REPORT-1"

    unauthorized = client.get("/api/v1/criticidad/reportes/auditoria")
    assert unauthorized.status_code == 403
    audit = client.get(
        "/api/v1/criticidad/reportes/auditoria?equipo_id=ACT-REPORT-1",
        headers=ADMIN_HEADERS,
    )
    assert audit.status_code == 200
    assert any(row["origen"] == "DEFAULT" for row in audit.json())


def test_manual_category_correction_keeps_equipment_criticality_record(client):
    _classify_with_equipment_id(client, "ACT-CATEGORY-1")
    corrected = client.post(
        "/api/v1/recalcular",
        json={
            "nombre": "Ventilador mecánico",
            "categoria_forzada": "OTR-01",
            "cmms_equipment_id": "ACT-CATEGORY-1",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["categoria_propia"] == "OTR-01"
    profile = client.get("/api/v1/criticidad/ACT-CATEGORY-1")
    assert profile.status_code == 200
    assert profile.json()["categoria"] == "OTR-01"
    assert any(
        item["origen"] == "CORRECCION_CATEGORIA"
        for item in profile.json()["historial_ajustes"]
    )


def test_health_reports_runtime_resources(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["model_version"] == Config.MODEL_VERSION
    assert "emdn_available" in data


def test_classification_and_batch_endpoints(client):
    response = client.post(
        "/api/v1/clasificar",
        json={
            "nombre": "Ecógrafo portátil",
            "marca": "Samsung",
            "cmms_equipment_id": "ACT-1042",
        },
    )
    assert response.status_code == 200
    assert response.json()["categoria_propia"] == "IMG-03"
    assert response.json()["semaforo"]["color"] == "verde"
    assert response.json()["cmms_equipment_id"] == "ACT-1042"

    batch = client.post(
        "/api/v1/batch-clasificar",
        json={
            "equipos": [
                {"nombre": "Ecógrafo portátil"},
                {"nombre": "Ventilador mecánico", "cmms_equipment_id": "ACT-2042"},
            ]
        },
    )
    assert batch.status_code == 200
    assert batch.json()["total"] == 2
    assert len(batch.json()["resultados"]) == 2
    assert batch.json()["resultados"][1]["cmms_equipment_id"] == "ACT-2042"


def test_emdn_search_returns_relevant_results_and_expected_shape(client):
    response = client.get("/api/v1/buscar", params={"q": "ventilador"})

    assert response.status_code == 200
    results = response.json()
    assert results
    assert any(
        result["codigo_emdn"].startswith("Z120301")
        and result["categoria_propia"] == "RES-01"
        for result in results
    )
    assert set(results[0]) == {
        "codigo_emdn",
        "termino_emdn",
        "categoria_propia",
        "clase_mdr",
        "nivel_terminal",
        "similitud",
    }

def test_emdn_search_prioritizes_prefix_matches_for_autocomplete(client):
    response = client.get("/api/v1/buscar", params={"q": "vent"})

    assert response.status_code == 200
    results = response.json()
    assert results
    assert "VENTILATOR" in results[0]["termino_emdn"]


def test_emdn_search_prioritizes_main_tomography_devices_over_accessories(client):
    response = client.get("/api/v1/buscar", params={"q": "TOMOGR", "limit": 12})
    expanded_response = client.get(
        "/api/v1/buscar", params={"q": "TOMOGR", "limit": 50}
    )

    assert response.status_code == 200
    assert expanded_response.status_code == 200
    results = response.json()
    assert len(results) >= 12
    variable_mdr_terms = ("ACCESSORIES", "CONSUMABLES", "SOFTWARE", "OTHER", "PARTS", "COMPONENTS")
    is_variable_mdr = lambda result: any(re.search(
        rf"\b{term}\b", result["termino_emdn"], re.IGNORECASE
    ) for term in variable_mdr_terms)
    first_variable_result = next(
        (index for index, result in enumerate(results) if is_variable_mdr(result)),
        len(results),
    )
    assert all(not is_variable_mdr(result) for result in results[:first_variable_result])
    assert all(is_variable_mdr(result) for result in results[first_variable_result:])
    positions = {
        result["codigo_emdn"]: index
        for index, result in enumerate(results)
    }
    main_codes = ("Z11030601", "Z11030602", "Z11030603")
    accessory_codes = ("Z11030680", "Z11030682", "Z11030685", "Z11030699")
    assert all(code in positions for code in (*main_codes, *accessory_codes))
    assert positions["Z11030601"] < positions["Z11030602"] < positions["Z11030603"]
    assert max(positions[code] for code in main_codes) < min(
        positions[code] for code in accessory_codes
    )
    expanded_results = expanded_response.json()
    first_expanded_variable = next(
        (index for index, result in enumerate(expanded_results) if is_variable_mdr(result)),
        len(expanded_results),
    )
    assert all(
        not is_variable_mdr(result) for result in expanded_results[:first_expanded_variable]
    )
    assert all(
        is_variable_mdr(result) for result in expanded_results[first_expanded_variable:]
    )


def test_emdn_search_matches_code_prefix_and_respects_limit(client):
    response = client.get(
        "/api/v1/buscar", params={"q": "Z120301", "limit": 5}
    )

    assert response.status_code == 200
    results = response.json()
    assert 0 < len(results) <= 5
    assert all(result["codigo_emdn"].startswith("Z120301") for result in results)
    assert all(result["nivel_terminal"] is True for result in results)


def test_emdn_search_returns_empty_list_for_unmatched_query(client):
    response = client.get("/api/v1/buscar", params={"q": "xyz"})

    assert response.status_code == 200
    assert response.json() == []


def test_emdn_search_normalizes_accents_and_uses_category_keywords(client):
    response = client.get("/api/v1/buscar", params={"q": "ecógrafo"})

    assert response.status_code == 200
    assert response.json()
    assert all(result["categoria_propia"] == "IMG-03" for result in response.json())

def test_emdn_search_uses_medical_synonyms(client):
    response = client.get("/api/v1/buscar", params={"q": "bomba"})

    assert response.status_code == 200
    assert any("PUMP" in result["termino_emdn"] for result in response.json())


def test_recalculate_forces_category_and_cmms_id(client):
    response = client.post(
        "/api/v1/recalcular",
        json={
            "nombre": "Electroestimulador",
            "marca": "Enraf Nonius",
            "ubicacion": "Fisioterapia",
            "categoria_forzada": "TER-01",
            "cmms_equipment_id": "ACT-1042",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["categoria_propia"] == "TER-01"
    assert result["confidence"] == 0.95
    assert result["metodo"] == "CORRECCION_MANUAL"
    assert result["semaforo"]["color"] == "verde"
    assert result["semaforo"]["nivel"] == "ALTA"
    assert result["semaforo"]["mensaje"] == "Validado manualmente por experto biomédico"
    assert result["emdn_code"] == "Z120616"
    assert result["emdn_term"] == "ELECTROMECHANICAL SYSTEMS FOR PHYSICAL THERAPY"
    assert result["mdr_class"] == CATEGORÍAS["TER-01"]["mdr_default"]
    assert result["cmms_equipment_id"] == "ACT-1042"
    assert result["validacion_correccion"]["estado"] == "VALIDADA_AUTOMATICAMENTE"
    assert all(result["validacion_correccion"]["validaciones"].values())


def test_recalculate_returns_validation_review_and_rejection_states(client, monkeypatch):
    original_classifier = routes.classify_equipment

    def classify_with_inconsistent_mdr(*args, **kwargs):
        result = original_classifier(*args, **kwargs)
        result["mdr_class"] = "III"
        return result

    monkeypatch.setattr(routes, "classify_equipment", classify_with_inconsistent_mdr)
    pending = client.post(
        "/api/v1/recalcular",
        json={"nombre": "Electroestimulador", "categoria_forzada": "TER-01"},
    )
    assert pending.status_code == 200
    assert pending.json()["confidence"] == 0.95
    assert pending.json()["semaforo"]["color"] == "verde"
    assert pending.json()["semaforo"]["nivel"] == "ALTA"
    assert pending.json()["semaforo"]["mensaje"] == "Validado manualmente por experto biomédico"
    assert pending.json()["metodo"] == "CORRECCION_MANUAL"
    assert pending.json()["validacion_correccion"]["estado"] == "PENDIENTE_REVISION"

    def classify_with_invalid_emdn_and_mdr(*args, **kwargs):
        result = classify_with_inconsistent_mdr(*args, **kwargs)
        result["emdn_code"] = "CODIGO-INEXISTENTE"
        return result

    monkeypatch.setattr(routes, "classify_equipment", classify_with_invalid_emdn_and_mdr)
    rejected = client.post(
        "/api/v1/recalcular",
        json={"nombre": "Electroestimulador", "categoria_forzada": "TER-01"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["confidence"] == 0.95
    assert rejected.json()["semaforo"]["color"] == "verde"
    assert rejected.json()["semaforo"]["mensaje"] == "Validado manualmente por experto biomédico"
    assert rejected.json()["validacion_correccion"]["estado"] == "RECHAZADA"

    saved = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "Electroestimulador"},
            "categoria_correcta": "TER-01",
            "resultado_corregido": rejected.json(),
        },
    )
    assert saved.status_code == 200
    assert saved.json()["estado"] == "PENDIENTE_REVISION"
    assert saved.json()["resultado_corregido"]["confidence"] == 0.95
    assert corrections.load_training_examples() == []


def test_semantic_failure_stays_rejected_and_cannot_be_saved(client):
    recalculated = client.post(
        "/api/v1/recalcular",
        json={
            "nombre": "Nebulizador ultrasónico",
            "categoria_forzada": "NEO-01",
        },
    )
    assert recalculated.status_code == 200
    result = recalculated.json()
    assert result["confidence"] == 0.30
    assert result["validacion_correccion"]["confidence"] == 0.30
    assert result["validacion_correccion"]["estado"] == "RECHAZADA"
    assert result["validacion_correccion"]["validaciones"]["semantica_valida"] is False
    assert result["semaforo"]["color"] == "rojo"

    forged_result = {**result, "confidence": 0.95}
    saved = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "Nebulizador ultrasónico"},
            "categoria_correcta": "NEO-01",
            "resultado_corregido": forged_result,
        },
    )
    assert saved.status_code == 400
    assert "relación semántica" in saved.json()["detail"]
    assert corrections.list_corrections() == []
    assert corrections.load_training_examples() == []


def test_semantically_rejected_correction_cannot_be_approved_for_training(client):
    correction_id = corrections.save_correction(
        {"nombre": "Nebulizador ultrasónico"},
        "NEO-01",
        {
            "confidence": 0.30,
            "validacion_correccion": {
                "validaciones": {"semantica_valida": False}
            },
        },
    )

    response = client.post(
        f"/api/v1/correcciones/{correction_id}/aprobar",
        headers=ADMIN_HEADERS,
        json={},
    )

    assert response.status_code == 409
    assert "validación semántica fallida" in response.json()["detail"]
    assert corrections.validate_saved_corrections() == 0
    assert corrections.load_training_examples() == []


def test_register_correction_requires_approval_before_training(client):
    response = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {
                "nombre": "ENS para fisioterapia",
                "marca": "Enraf Nonius",
                "ubicacion": "Fisioterapia",
                "categoria_original": "ANE-01",
                "confidence_original": 0.2,
                "cmms_equipment_id": "ACT-1042",
            },
            "categoria_correcta": "TER-01",
            "resultado_corregido": {
                "categoria_propia": "TER-01",
                "confidence": 0.95,
            },
            "usuario": "biomedico",
        },
    )
    assert response.status_code == 200
    assert response.json()["source"] == "USER_CORRECTION"
    assert response.json()["cmms_equipment_id"] == "ACT-1042"
    correction_id = response.json()["correction_id"]
    polled = client.get(f"/api/v1/correcciones/{correction_id}")
    assert polled.status_code == 200
    assert polled.json()["categoria_corregida"] == "TER-01"
    assert polled.json()["confidence_original"] == 0.2
    assert polled.json()["resultado_corregido"]["categoria_propia"] == "TER-01"
    assert corrections.load_training_examples() == []

    pending = client.get(
        "/api/v1/correcciones/pendientes-revision", headers=ADMIN_HEADERS
    )
    assert pending.status_code == 200
    assert pending.json()[0]["id"] == correction_id
    approved = client.post(
        f"/api/v1/correcciones/{correction_id}/aprobar",
        headers=ADMIN_HEADERS,
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["estado"] == "APROBADA"
    assert corrections.validate_saved_corrections() == 1
    examples = corrections.load_training_examples()
    assert examples == [
        {
            "nombre": "ENS para fisioterapia",
            "marca": "Enraf Nonius",
            "ubicacion": "Fisioterapia",
            "categoria": "TER-01",
            "source": "USER_CORRECTION",
        }
    ]
    reviewed = client.get("/api/v1/correcciones/revisadas", headers=ADMIN_HEADERS)
    assert reviewed.status_code == 200
    assert reviewed.json()[0]["estado"] == "APROBADA"


def test_register_correction_rejects_category_mismatch(client):
    response = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "Equipo"},
            "categoria_correcta": "TER-01",
            "resultado_corregido": {"categoria_propia": "ANE-01", "confidence": 0.95},
        },
    )
    assert response.status_code == 400


def test_register_correction_rejects_low_confidence(client):
    response = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "ENS"},
            "categoria_correcta": "TER-01",
            "resultado_corregido": {"categoria_propia": "TER-01", "confidence": 0.30},
        },
    )
    assert response.status_code == 400
    assert "menos de 2 validaciones coherentes" in response.json()["detail"]
    assert corrections.list_corrections() == []
    assert corrections.load_training_examples() == []


def test_register_correction_accepts_two_checks_for_review_but_not_training(
    client, monkeypatch
):
    original_classifier = routes.classify_equipment

    def classify_with_inconsistent_mdr(*args, **kwargs):
        result = original_classifier(*args, **kwargs)
        result["mdr_class"] = "III"
        return result

    monkeypatch.setattr(routes, "classify_equipment", classify_with_inconsistent_mdr)
    response = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "Electroestimulador"},
            "categoria_correcta": "TER-01",
            "resultado_corregido": {"categoria_propia": "TER-01", "confidence": 0.75},
        },
    )

    assert response.status_code == 200
    assert response.json()["estado"] == "PENDIENTE_REVISION"
    assert response.json()["resultado_corregido"]["confidence"] == 0.75
    assert corrections.load_training_examples() == []
    assert corrections.validate_saved_corrections() == 0


def test_admin_routes_require_credentials_and_fail_closed_without_server_key(
    client, monkeypatch
):
    assert client.post("/api/v1/admin/auth").status_code == 403
    assert client.get("/api/v1/correcciones/pendientes-revision").status_code == 403
    assert client.get(
        "/api/v1/correcciones/pendientes-revision",
        headers={"X-Admin-User": "admin"},
    ).status_code == 403
    monkeypatch.setattr(Config, "ADMIN_API_KEY", "")
    unavailable = client.get(
        "/api/v1/correcciones/pendientes-revision", headers=ADMIN_HEADERS
    )
    assert unavailable.status_code == 503
    assert client.post("/api/v1/admin/auth", headers=ADMIN_HEADERS).status_code == 503


def test_admin_can_request_information_then_reject_and_audit(client):
    correction_id = corrections.save_correction(
        {"nombre": "Equipo de terapia"},
        "TER-01",
        {"categoria_propia": "TER-01", "confidence": 0.95},
    )
    asked = client.post(
        f"/api/v1/correcciones/{correction_id}/solicitar-informacion",
        headers=ADMIN_HEADERS,
        json={"nota": "Confirmar el modelo del equipo."},
    )
    assert asked.status_code == 200
    assert asked.json()["estado"] == "PENDIENTE"
    assert asked.json()["correccion"]["notas"] == "Confirmar el modelo del equipo."

    rejected = client.post(
        f"/api/v1/correcciones/{correction_id}/rechazar",
        headers=ADMIN_HEADERS,
        json={"motivo_rechazo": "El EMDN no corresponde al equipo."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["estado"] == "RECHAZADA"
    assert rejected.json()["correccion"]["motivo_rechazo"] == (
        "El EMDN no corresponde al equipo."
    )
    assert client.get(
        "/api/v1/correcciones/revisadas", headers=ADMIN_HEADERS
    ).json()[0]["estado"] == "RECHAZADA"
    actions = [entry["accion"] for entry in corrections.list_audit_logs()]
    assert "SOLICITAR_INFORMACION" in actions
    assert "RECHAZAR" in actions


def test_register_correction_rejects_forged_confidence(client, monkeypatch):
    monkeypatch.setattr(
        routes,
        "classify_equipment",
        lambda *args, **kwargs: {
            "categoria_propia": "IMG-01",
            "confidence": 0.35,
        },
    )
    response = client.post(
        "/api/v1/registrar-correccion",
        json={
            "entrada_original": {"nombre": "Equipo raro"},
            "categoria_correcta": "IMG-01",
            "resultado_corregido": {"categoria_propia": "IMG-01", "confidence": 0.99},
        },
    )
    assert response.status_code == 400
    assert "relación semántica" in response.json()["detail"]
    assert corrections.list_corrections() == []


def test_validation_endpoint_and_legacy_alias(client):
    for path in ("/api/v1/validar-emdn", "/api/v1/validar"):
        response = client.post(path, json={"emdn_code": "Z11040103"})
        assert response.status_code == 200
        assert response.json()["exists"] is True
        assert response.json()["term"] == "PORTABLE ULTRASOUND SCANNERS"

    missing = client.post(
        "/api/v1/validar-emdn", json={"emdn_code": "CODIGO_INVENTADO"}
    )
    assert missing.status_code == 200
    assert missing.json()["exists"] is False


def test_categories_search_and_metrics_endpoints(client):
    categories = client.get("/api/v1/categorias")
    assert categories.status_code == 200
    assert len(categories.json()) == len(CATEGORÍAS)

    search = client.post("/api/v1/buscar-emdn", json={"keyword": "portable ultrasound"})
    assert search.status_code == 200
    assert search.json()[0]["code"] == "Z11040103"

    metrics = client.get("/api/v1/metricas")
    assert metrics.status_code == 200
    with open(MODELS_DIR / f"metrics_{Config.MODEL_VERSION}.json", encoding="utf-8") as file:
        assert metrics.json() == json.load(file)


def test_metrics_endpoint_reports_missing_metrics(client, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "MODELS_DIR", tmp_path)
    response = client.get("/api/v1/metricas")
    assert response.status_code == 503
    assert "Ejecuta el pipeline" in response.json()["detail"]


def test_retrain_endpoint_returns_training_result(client, monkeypatch):
    monkeypatch.setattr(routes, "validate_saved_corrections", lambda: 10)
    monkeypatch.setattr(
        routes,
        "re_entrenar",
        lambda **kwargs: {
            "status": "ok",
            "version": 2,
            "modelo_activo": "v2",
            "nuevos_totales": 14,
            "accuracy": 0.88,
            "correcciones_validadas": 10,
        },
    )
    response = client.post(
        "/api/v1/reentrenar",
        json={
            "validar_correcciones": True,
            "nueva_version": "v2",
        },
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": 2,
        "modelo_activo": "v2",
        "nuevos_totales": 14,
        "accuracy": 0.88,
        "correcciones_validadas": 10,
    }


def test_retrain_rejects_client_supplied_training_examples(client):
    response = client.post(
        "/api/v1/reentrenar",
        headers=ADMIN_HEADERS,
        json={
            "validar_correcciones": True,
            "nueva_version": "v2",
            "nuevos_ejemplos": [{"nombre": "Ejemplo arbitrario", "categoria": "OTR-01"}],
        },
    )
    assert response.status_code == 400


def test_retrain_rejects_disabled_correction_validation(client):
    response = client.post(
        "/api/v1/reentrenar",
        json={"validar_correcciones": False, "nueva_version": "v2"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400
    assert "requiere validar" in response.json()["detail"]


def test_retrain_without_saved_corrections_returns_clear_error(client):
    response = client.post(
        "/api/v1/reentrenar",
        json={"validar_correcciones": True, "nueva_version": "v2"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "No hay correcciones guardadas para reentrenar."


def test_retrain_trains_and_activates_requested_version(
    client, monkeypatch, tmp_path
):
    from src import trainer

    monkeypatch.setattr(
        trainer,
        "load_validated_dataset",
        lambda _path=None: [
            {"nombre": "ecografo imagenologia", "categoria": "IMG-03"},
            {"nombre": "ultrasonido clinico", "categoria": "IMG-03"},
            {"nombre": "ventilador respiratorio", "categoria": "RES-01"},
            {"nombre": "respirador pulmonar", "categoria": "RES-01"},
        ],
    )
    monkeypatch.setattr(trainer, "preprocess_text", lambda text: text.lower())
    monkeypatch.setattr(Config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(Config, "MODEL_VERSION", "v1")
    for index in range(10):
        corrections.save_correction(
            {
                "nombre": f"Equipo de terapia corregido {index}",
                "categoria_original": "OTR-01",
            },
            "TER-01",
            {"categoria_propia": "TER-01", "confidence": 0.95},
        )
        corrections.review_correction(
            index + 1,
            action="APROBAR",
            user="test-admin",
        )

    result = trainer.re_entrenar(
        validar_correcciones=True,
        nueva_version="v2",
    )
    assert result["modelo_activo"] == "v2"
    assert result["nuevos_totales"] == 14
    assert result["correcciones_validadas"] == 10
    assert 0 <= result["accuracy"] <= 1
    assert Config.MODEL_VERSION == "v2"
    assert (Config.MODELS_DIR / "classifier_v2.pkl").exists()
    assert (Config.MODELS_DIR / "metrics_v2.json").exists()


def test_invalid_requests_return_clear_client_error(client):
    response = client.post("/api/v1/clasificar", json={"nombre": "   "})
    assert response.status_code == 400
    assert response.json()["detail"] == "Solicitud inválida."

    response = client.post("/api/v1/batch-clasificar", json={"equipos": []})
    assert response.status_code == 400

    response = client.post(
        "/api/v1/clasificar", json={"nombre": "x" * 501}
    )
    assert response.status_code == 400


def test_cors_preflight(client):
    response = client.options(
        "/api/v1/clasificar",
        headers={
            "Origin": Config.CORS_ORIGINS[0],
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-admin-key,x-admin-user",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == Config.CORS_ORIGINS[0]
    assert "x-admin-key" in response.headers["access-control-allow-headers"].lower()


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(Config, "RATE_LIMIT_REQUESTS", 1)
    monkeypatch.setattr(Config, "RATE_LIMIT_WINDOW_SECONDS", 60)

    assert client.get("/api/v1/health").status_code == 200
    limited = client.get("/api/v1/health")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0

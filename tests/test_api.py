import json

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api import routes
from api.main import app
from src import code_generator
from src.config import Config
from src.utils import CATEGORÍAS, MODELS_DIR


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(code_generator, "_SEQUENCE_PATH", tmp_path / "sequences.json")
    api_main._rate_windows.clear()
    with TestClient(app) as test_client:
        yield test_client


def test_root_redirects_to_docs(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"


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
        json={"nombre": "Ecógrafo portátil", "marca": "Samsung"},
    )
    assert response.status_code == 200
    assert response.json()["categoria_propia"] == "IMG-03"

    batch = client.post(
        "/api/v1/batch-clasificar",
        json={
            "equipos": [
                {"nombre": "Ecógrafo portátil"},
                {"nombre": "Ventilador mecánico"},
            ]
        },
    )
    assert batch.status_code == 200
    assert batch.json()["total"] == 2
    assert len(batch.json()["resultados"]) == 2


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
    monkeypatch.setattr(
        routes,
        "re_entrenar",
        lambda examples: {
            "status": "ok",
            "version": 2,
            "nuevos_totales": len(examples),
        },
    )
    response = client.post(
        "/api/v1/reentrenar",
        json={"nuevos_ejemplos": [{"nombre": "Equipo", "categoria": "OTR-01"}]},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": 2, "nuevos_totales": 1}


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
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == Config.CORS_ORIGINS[0]


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(Config, "RATE_LIMIT_REQUESTS", 1)
    monkeypatch.setattr(Config, "RATE_LIMIT_WINDOW_SECONDS", 60)

    assert client.get("/api/v1/health").status_code == 200
    limited = client.get("/api/v1/health")
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0

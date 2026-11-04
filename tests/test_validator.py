import json

from src.emdn_importer import load_emdn_database
from src.utils import PROCESSED_DIR
from sklearn.linear_model import LogisticRegression
from src.trainer import _cross_validated_predictions, deduplicate_training_examples
from src.validator import validate_equipment_dataset, validate_suggestions


def test_validate_equipment_dataset_returns_summary():
    report = validate_equipment_dataset()
    assert "resumen" in report
    assert report["resumen"]["total_equipos"] >= 1
    assert "detalles" in report


def test_validated_dataset_contains_only_official_terminal_codes():
    validate_equipment_dataset()
    database = load_emdn_database()
    with open(PROCESSED_DIR / "equipos_demo_nlp.json", "r", encoding="utf-8") as file:
        validated = json.load(file)

    assert all(
        record["emdn_code"] in database["flat"]
        and database["flat"][record["emdn_code"]]["terminal_level"] == "YES"
        for record in validated
        if record.get("emdn_code")
    )


def test_suggestion_validator_splits_sample_into_five_valid_and_five_discrepant(
    tmp_path,
):
    report = validate_suggestions(
        validated_output=tmp_path / "equipos_validados.json",
        discrepancies_output=tmp_path / "discrepancias.json",
    )
    with open(report["equipos_validados"], "r", encoding="utf-8") as file:
        validated = json.load(file)
    with open(report["discrepancias_path"], "r", encoding="utf-8") as file:
        discrepancies = json.load(file)

    assert report["total"] == 10
    assert report["validados"] == 5
    assert report["discrepancias"] == 5
    assert all(record["estado"] == "VALIDADO" for record in validated)
    assert all(record["categoria"] for record in validated)
    assert all(record["estado"] == "DISCREPANCIA" for record in discrepancies)
    assert any("no es terminal" in item["motivo"] for item in discrepancies)
    assert any("no existe" in item["motivo"] for item in discrepancies)
    assert any("no coincide" in item["motivo"] for item in discrepancies)


def test_suggestion_validator_accepts_official_emdn_category_and_description(
    tmp_path,
):
    suggestions_path = tmp_path / "sugerencias.json"
    suggestions_path.write_text(
        json.dumps(
            [
                {
                    "nombre_equipo": "Ecógrafo portátil",
                    "categoria_sugerida": "Z",
                    "emdn_sugerido": "Z11040103",
                },
                {
                    "nombre_equipo": "Tomógrafo",
                    "categoria_sugerida": (
                        "MEDICAL EQUIPMENT AND RELATED ACCESSORIES, SOFTWARE AND CONSUMABLES"
                    ),
                    "emdn_sugerido": "Z11030601",
                },
            ]
        ),
        encoding="utf-8",
    )
    report = validate_suggestions(
        input_path=suggestions_path,
        validated_output=tmp_path / "validos.json",
        discrepancies_output=tmp_path / "fallos.json",
    )
    with open(report["equipos_validados"], "r", encoding="utf-8") as file:
        validated = json.load(file)

    assert report["validados"] == 2
    assert report["discrepancias"] == 0
    assert {item["categoria"] for item in validated} == {"IMG-03", "IMG-02"}


def test_suggestion_validator_accepts_additional_category_prefixes(tmp_path):
    suggestions_path = tmp_path / "sugerencias_prefijos_adicionales.json"
    suggestions_path.write_text(
        json.dumps(
            [
                {
                    "nombre_equipo": "Bisturí armónico",
                    "categoria_sugerida": "CIR-02",
                    "emdn_sugerido": "K0202010201",
                },
                {
                    "nombre_equipo": "Resonador magnético",
                    "categoria_sugerida": "IMG-02",
                    "emdn_sugerido": "Z11050104",
                },
                {
                    "nombre_equipo": "Concentrador de oxígeno",
                    "categoria_sugerida": "GAS-01",
                    "emdn_sugerido": "Z12159004",
                },
            ]
        ),
        encoding="utf-8",
    )

    report = validate_suggestions(
        input_path=suggestions_path,
        validated_output=tmp_path / "validos_prefijos_adicionales.json",
        discrepancies_output=tmp_path / "fallos_prefijos_adicionales.json",
    )

    assert report["validados"] == 3
    assert report["discrepancias"] == 0


def test_duplicate_training_examples_prefer_approved_manual_correction():
    dataset = deduplicate_training_examples(
        [
            {"nombre": "Ecógrafo portátil", "marca": "Acme", "categoria": "IMG-03"},
            {"nombre": "Ventilador", "categoria": "RES-01"},
        ],
        [
            {
                "nombre": "ecografo PORTÁTIL",
                "marca": "Acme",
                "categoria": "IMG-02",
                "source": "EMDN_VALIDATED_SUGGESTION",
            },
            {
                "nombre": "Ecógrafo portátil",
                "marca": "Acme",
                "categoria": "IMG-03",
                "source": "USER_CORRECTION",
            },
        ],
    )

    assert len(dataset) == 2
    assert next(item for item in dataset if item["nombre"] == "Ecógrafo portátil")[
        "source"
    ] == "USER_CORRECTION"


def test_training_metrics_exclude_singleton_categories_from_cross_validation():
    from scipy.sparse import csr_matrix

    features = csr_matrix([[0, 1], [0, 2], [1, 0], [2, 0], [3, 0]])
    labels = ["IMG-03", "IMG-03", "RES-01", "RES-01", "DIA-01"]
    model = LogisticRegression(random_state=42)

    predictions, evaluated_labels, folds = _cross_validated_predictions(
        model, features, labels
    )

    assert len(predictions) == len(evaluated_labels) == 4
    assert folds == 2

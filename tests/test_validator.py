import json

from src.emdn_importer import load_emdn_database
from src.utils import PROCESSED_DIR
from src.validator import validate_equipment_dataset


def test_validate_equipment_dataset_returns_summary():
    report = validate_equipment_dataset()
    assert "resumen" in report
    assert report["resumen"]["total_equipos"] >= 1
    assert "detalles" in report


def test_validated_dataset_contains_only_official_terminal_codes():
    validate_equipment_dataset()
    database = load_emdn_database()
    with open(PROCESSED_DIR / "equipos_validados.json", "r", encoding="utf-8") as file:
        validated = json.load(file)

    assert all(
        record["emdn_code"] in database["flat"]
        and database["flat"][record["emdn_code"]]["terminal_level"] == "YES"
        for record in validated
        if record.get("emdn_code")
    )

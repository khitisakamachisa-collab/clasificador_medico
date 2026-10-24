import json

from src.emdn_importer import buscar_emdn, load_emdn_database, validar_codigo_emdn
from src.utils import PROCESSED_DIR


def test_load_emdn_database_contains_only_official_terminal_codes():
    db = load_emdn_database()
    assert db["available"] is True
    assert db["stats"]["total"] > 0
    assert all(item["terminal_level"] == "YES" for item in db["flat"].values())
    assert db["flat"]["Z11040103"]["name"] == "PORTABLE ULTRASOUND SCANNERS"
    assert "Z110401" not in db["flat"]
    assert any(item["code"] == "Z11040103" for item in db["prefix_index"]["Z1104"])
    with open(PROCESSED_DIR / "emdn_database.json", "r", encoding="utf-8") as file:
        saved = json.load(file)
    assert saved["prefix_index"]["Z1104"]


def test_buscar_emdn_returns_matches():
    db = load_emdn_database()
    matches = buscar_emdn(["portable ultrasound scanner", "ultrasound"], db)
    assert len(matches) >= 1
    assert matches[0][0] == "Z11040103"


def test_buscar_emdn_fuzzy_match_handles_typo():
    db = load_emdn_database()
    matches = buscar_emdn("portabl ultrasound", db, prefix="Z1104")
    assert matches
    assert matches[0][0] == "Z11040103"


def test_buscar_emdn_does_not_return_unrelated_fuzzy_matches():
    db = load_emdn_database()
    assert buscar_emdn("banana xylophone", db, prefix="Z1104") == []


def test_missing_excel_returns_empty_database(tmp_path, caplog):
    db = load_emdn_database(tmp_path / "missing.xlsx")
    assert db["available"] is False
    assert db["flat"] == {}
    assert "No se encontró el Excel EMDN 2026" in caplog.text


def test_validar_codigo_emdn_accepts_only_official_terminal_codes():
    db = load_emdn_database()
    assert validar_codigo_emdn("Z12090201", db)
    assert validar_codigo_emdn("Z12159004", db)
    assert not validar_codigo_emdn("CODIGO_INVENTADO", db)

import json

import pytest

from src import code_generator


def test_generates_code_after_existing_persisted_sequence(tmp_path, monkeypatch):
    sequence_path = tmp_path / "sequences.json"
    sequence_path.write_text(json.dumps({"IMG03": 7}), encoding="utf-8")
    monkeypatch.setattr(code_generator, "_SEQUENCE_PATH", sequence_path)

    assert code_generator.generar_codigo_interno("IMG-03") == "IMG03-008"


def test_generates_code_after_existing_codes_without_persistence():
    assert (
        code_generator.generar_codigo_interno(
            "IMG-03", ["IMG03-001", "IMG03-009", "OTHER-002"]
        )
        == "IMG03-010"
    )


def test_corrupt_sequence_file_is_reported(tmp_path, monkeypatch):
    sequence_path = tmp_path / "sequences.json"
    sequence_path.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr(code_generator, "_SEQUENCE_PATH", sequence_path)

    with pytest.raises(ValueError, match="JSON válido"):
        code_generator.generar_codigo_interno("IMG-03")

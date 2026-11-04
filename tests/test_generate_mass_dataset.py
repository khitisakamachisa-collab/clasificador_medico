import json
import sys

import pandas as pd

from scripts import generar_dataset_masivo
from src.emdn_importer import load_emdn_database


def test_find_name_column_recognizes_accents_and_explicit_names():
    frame = pd.DataFrame(
        columns=["Descripción del equipo", "fabricante"]
    )

    assert generar_dataset_masivo.find_name_column(frame) == "Descripción del equipo"
    assert (
        generar_dataset_masivo.find_name_column(frame, "fabricante")
        == "fabricante"
    )


def test_load_source_rows_supports_json_and_applies_limit(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            [{"nombre": f"Equipo {index}"} for index in range(5)],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert generar_dataset_masivo._load_source_rows(source, 3, "nombre") == [
        "Equipo 0",
        "Equipo 1",
        "Equipo 2",
    ]


def test_load_source_rows_supports_excel_and_explicit_column(tmp_path):
    source = tmp_path / "source.xlsx"
    pd.DataFrame({"EQUIPO": ["Ventilador", "Ecógrafo"]}).to_excel(
        source, index=False
    )

    assert generar_dataset_masivo._load_source_rows(source, 1, "EQUIPO") == [
        "Ventilador"
    ]


def test_prompt_requests_only_the_internal_category():
    messages = generar_dataset_masivo._prompt_for_equipment("Ventilador mecánico")

    assert '"categoria_sugerida"' in messages[0]["content"]
    assert "No incluyas ni inventes códigos EMDN" in messages[0]["content"]
    assert "emdn_sugerido" not in messages[0]["content"]


def test_generate_suggestions_ignores_llm_codes_and_uses_official_terminal(
    monkeypatch,
):
    monkeypatch.setattr(
        generar_dataset_masivo,
        "query_ollama",
        lambda *args: {
            "categoria_sugerida": "ANE-01",
            "emdn_sugerido": "0416",
        },
    )

    suggestions = generar_dataset_masivo.generate_suggestions(
        ["Máquina de anestesia con ventilador integrado"],
        provider="ollama",
        model="qwen2.5:7b",
        ollama_url="http://localhost:11434",
        api_base_url=None,
        api_key=None,
        timeout=1,
    )

    suggestion = suggestions[0]
    official = load_emdn_database()["flat"]
    assert suggestion["emdn_sugerido"] != "0416"
    assert suggestion["emdn_sugerido"] in official
    assert official[suggestion["emdn_sugerido"]]["terminal_level"] == "YES"
    assert suggestion["fuente_codigo"] == "BUSQUEDA_DIFUSA"
    assert suggestion["requiere_desambiguacion"] is False


def test_low_fuzzy_similarity_requires_manual_review(monkeypatch):
    monkeypatch.setattr(
        generar_dataset_masivo,
        "query_ollama",
        lambda *args: {"categoria_sugerida": "ANE-01"},
    )

    suggestions = generar_dataset_masivo.generate_suggestions(
        ["Objeto sin relación clínica"],
        provider="ollama",
        model="qwen2.5:7b",
        ollama_url="http://localhost:11434",
        api_base_url=None,
        api_key=None,
        timeout=1,
    )

    assert suggestions[0]["emdn_sugerido"] == ""
    assert suggestions[0]["requiere_desambiguacion"] is True


def test_terminal_search_supports_additional_category_prefixes():
    database = load_emdn_database()
    cases = (
        ("Bisturí armónico", "CIR-02", "K020201"),
        ("Resonador magnético", "IMG-02", "Z1105"),
        ("Concentrador de oxígeno", "GAS-01", "Z12159004"),
    )

    for name, category, expected_prefix in cases:
        code, term, similarity = generar_dataset_masivo.buscar_codigo_terminal(
            name, category, database
        )
        assert code.startswith(expected_prefix)
        assert database["flat"][code]["terminal_level"] == "YES"
        assert term
        assert similarity >= generar_dataset_masivo.MIN_EMDN_SIMILARITY


def test_main_generates_and_validates_mass_dataset(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.xlsx"
    pd.DataFrame(
        {
            "Nombre del equipo": [
                "Ecógrafo portátil",
                "Electrocirugía",
                "Tomógrafo",
            ]
        }
    ).to_excel(source, index=False)
    monkeypatch.setattr(generar_dataset_masivo, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(
        generar_dataset_masivo,
        "generate_suggestions",
        lambda names, **kwargs: [
            {
                "nombre_equipo": names[0],
                "categoria_sugerida": "IMG-03",
                "emdn_sugerido": "Z11040103",
            },
            {
                "nombre_equipo": names[1],
                "categoria_sugerida": "CIR-02",
                "emdn_sugerido": "Z120109",
            },
            {
                "nombre_equipo": names[2],
                "categoria_sugerida": "IMG-02",
                "emdn_sugerido": "Z11030601",
            },
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generar_dataset_masivo.py",
            "--input",
            str(source),
            "--limit",
            "100",
        ],
    )

    generar_dataset_masivo.main()

    processed = tmp_path / "processed"
    with (processed / "equipos_validados_masivo.json").open(
        "r", encoding="utf-8"
    ) as file:
        validated = json.load(file)
    with (processed / "discrepancias_masivo.json").open(
        "r", encoding="utf-8"
    ) as file:
        discrepancies = json.load(file)

    assert len(validated) == 2
    assert len(discrepancies) == 1
    assert "no es terminal" in discrepancies[0]["motivo"]
    assert "2 validados, 1 discrepancias para revisión manual" in capsys.readouterr().out


def test_source_row_limit_is_capped_by_cli_validation(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["generar_dataset_masivo.py", "--limit", "201"],
    )

    try:
        generar_dataset_masivo.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("El script debía rechazar más de 200 filas.")


def test_source_row_limit_must_be_positive(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["generar_dataset_masivo.py", "--limit", "0"],
    )

    try:
        generar_dataset_masivo.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("El script debía exigir al menos una fila.")

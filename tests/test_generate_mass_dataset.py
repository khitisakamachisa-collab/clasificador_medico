import json
import sys

import pandas as pd

from scripts import generar_dataset_masivo


def test_find_name_column_recognizes_accents_and_explicit_names():
    frame = pd.DataFrame(
        columns=["Descripción del equipo", "fabricante"]
    )

    assert generar_dataset_masivo.find_name_column(frame) == "Descripción del equipo"
    assert (
        generar_dataset_masivo.find_name_column(frame, "fabricante")
        == "fabricante"
    )


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


def test_source_row_limit_must_include_at_least_100(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["generar_dataset_masivo.py", "--limit", "99"],
    )

    try:
        generar_dataset_masivo.main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("El script debía exigir al menos 100 filas.")

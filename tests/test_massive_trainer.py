import json

import pytest

from src import classifier, trainer
from src.config import Config


def test_massive_training_uses_required_dataset_and_preserves_v2(
    tmp_path, monkeypatch, capsys
):
    processed_dir = tmp_path / "processed"
    models_dir = tmp_path / "models"
    processed_dir.mkdir()
    models_dir.mkdir()
    dataset = [
        {
            "nombre": f"Equipo {category} modelo {index}",
            "categoria": category,
            "estado": "VALIDADO",
        }
        for category in ("ANE-01", "CAR-01", "IMG-03")
        for index in range(20)
    ]
    (processed_dir / "equipos_validados_masivo.json").write_text(
        json.dumps(dataset), encoding="utf-8"
    )
    old_classifier = models_dir / "classifier_v2.pkl"
    old_metrics = models_dir / "metrics_v2.json"
    old_classifier.write_bytes(b"old model")
    old_metrics.write_text('{"accuracy": 1.0}', encoding="utf-8")
    monkeypatch.setattr(Config, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(Config, "MODELS_DIR", models_dir)
    monkeypatch.setattr(trainer, "ensure_directories", lambda: None)
    monkeypatch.setattr(trainer, "load_validated_dataset", lambda: [])
    monkeypatch.setattr(trainer, "preprocess_text", lambda text: text.lower())
    monkeypatch.setattr(
        "src.corrections.load_training_examples",
        lambda: [{"nombre": "Corrección aprobada", "categoria": "ANE-01"}],
    )
    classifier.load_model_assets.cache_clear()

    result = trainer.train_massive_model()
    output = capsys.readouterr().out

    assert "OPTIMIZACIÓN FINAL DEL MODELO NLP" in output
    assert "Dataset original: 61 ejemplos" in output
    assert "Dataset limpio (clases >= 3 ejemplos): 61 ejemplos" in output
    assert "Accuracy Promedio:" in output
    assert result["metrics"]["total_examples"] == 61
    assert result["metrics"]["total_examples_cleaned"] == 61
    assert result["metrics"]["cross_validation_folds"] == 5
    assert len(result["metrics"]["accuracy_by_fold"]) == 5
    assert len(result["metrics"]["f1_macro_by_fold"]) == 5
    assert len(result["metrics"]["test_examples_by_fold"]) == 5
    assert result["metrics"]["evaluation"] == "stratified_5_fold_grid_search"
    assert result["metrics"]["best_params"]["classifier__C"] in (0.1, 1.0, 10.0)
    assert (models_dir / "nlp_model_optimizado.pkl").is_file()
    assert (models_dir / "vectorizer_optimizado.pkl").is_file()
    assert (models_dir / "nlp_model_final.pkl").is_file()
    assert (models_dir / "vectorizer_final.pkl").is_file()
    assert (models_dir / "nlp_model_masivo.pkl").is_file()
    assert (models_dir / "vectorizer_masivo.pkl").is_file()
    metrics = json.loads((models_dir / "metrics_masivo.json").read_text(encoding="utf-8"))
    assert metrics["cross_validation_folds"] == 5
    assert metrics["accuracy_std"] >= 0
    assert old_classifier.read_bytes() == b"old model"
    assert old_metrics.read_text(encoding="utf-8") == '{"accuracy": 1.0}'

    loaded_model, loaded_vectorizer = classifier.load_model_assets()
    assert loaded_model.classes_.tolist() == result["model"].classes_.tolist()
    assert loaded_vectorizer.get_feature_names_out().tolist() == (
        result["vectorizer"].get_feature_names_out().tolist()
    )
    classifier.load_model_assets.cache_clear()


def test_massive_training_falls_back_when_all_categories_are_minor(
    tmp_path, monkeypatch, capsys
):
    processed_dir = tmp_path / "processed"
    models_dir = tmp_path / "models"
    processed_dir.mkdir()
    models_dir.mkdir()
    dataset = [
        {"nombre": "Equipo alfa", "categoria": "ANE-01", "estado": "VALIDADO"},
        {"nombre": "Equipo alfa dos", "categoria": "ANE-01", "estado": "VALIDADO"},
        {"nombre": "Equipo beta", "categoria": "CAR-01", "estado": "VALIDADO"},
        {"nombre": "Equipo beta dos", "categoria": "CAR-01", "estado": "VALIDADO"},
    ]
    (processed_dir / "equipos_validados_masivo.json").write_text(
        json.dumps(dataset), encoding="utf-8"
    )
    monkeypatch.setattr(Config, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(Config, "MODELS_DIR", models_dir)
    monkeypatch.setattr(trainer, "ensure_directories", lambda: None)
    monkeypatch.setattr(trainer, "preprocess_text", lambda text: text.lower())
    monkeypatch.setattr("src.corrections.load_training_examples", lambda: [])

    result = trainer.train_massive_model()
    output = capsys.readouterr().out

    assert "Se excluyeron 2 categorías minoritarias" in output
    assert "parámetros predeterminados" in output
    assert result["metrics"]["cleaning_fallback"] is True
    assert result["metrics"]["total_examples_cleaned"] == 0
    assert result["metrics"]["excluded_minor_examples"] == 4
    assert result["metrics"]["cross_validation_folds"] == 0
    assert result["metrics"]["accuracy"] is None
    assert set(result["model"].classes_) == {"ANE-01", "CAR-01"}
    assert (models_dir / "nlp_model_optimizado.pkl").is_file()


def test_massive_training_falls_back_for_single_minor_category(
    tmp_path, monkeypatch
):
    processed_dir = tmp_path / "processed"
    models_dir = tmp_path / "models"
    processed_dir.mkdir()
    models_dir.mkdir()
    dataset = [
        {"nombre": "Equipo alfa", "categoria": "ANE-01", "estado": "VALIDADO"},
        {"nombre": "Equipo alfa dos", "categoria": "ANE-01", "estado": "VALIDADO"},
    ]
    (processed_dir / "equipos_validados_masivo.json").write_text(
        json.dumps(dataset), encoding="utf-8"
    )
    monkeypatch.setattr(Config, "PROCESSED_DIR", processed_dir)
    monkeypatch.setattr(Config, "MODELS_DIR", models_dir)
    monkeypatch.setattr(trainer, "ensure_directories", lambda: None)
    monkeypatch.setattr(trainer, "preprocess_text", lambda text: text.lower())
    monkeypatch.setattr("src.corrections.load_training_examples", lambda: [])

    result = trainer.train_massive_model()

    assert result["metrics"]["cleaning_fallback"] is True
    assert result["metrics"]["cross_validation_folds"] == 0
    assert result["model"].classes_.tolist() == ["ANE-01"]


def test_massive_training_rejects_missing_or_empty_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(trainer, "ensure_directories", lambda: None)
    dataset_path = tmp_path / "equipos_validados_masivo.json"

    with pytest.raises(FileNotFoundError, match="dataset masivo obligatorio"):
        trainer._load_massive_dataset()

    dataset_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset masivo está vacío"):
        trainer._load_massive_dataset()


def test_massive_training_accepts_explicit_merged_dataset(tmp_path):
    dataset_path = tmp_path / "equipos_entrenamiento_final.json"
    dataset_path.write_text(
        json.dumps(
            [
                {
                    "nombre": "Equipo aprobado",
                    "categoria": "IMG-01",
                    "categoria_propia": "IMG-01",
                    "codigo_emdn": "Z110305",
                    "estado": "VALIDADO",
                }
            ]
        ),
        encoding="utf-8",
    )

    dataset = trainer._load_massive_dataset(dataset_path)

    assert len(dataset) == 1
    assert dataset[0]["nombre"] == "Equipo aprobado"

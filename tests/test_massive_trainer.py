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

    assert "ENTRENAMIENTO NLP - DATASET MASIVO" in output
    assert "Equipos validados masivo: 60 registros" in output
    assert "Correcciones aprobadas: 1 registros" in output
    assert "Total ejemplos: 61" in output
    assert "Accuracy:" in output
    assert result["metrics"]["total_examples"] == 61
    assert (models_dir / "nlp_model_masivo.pkl").is_file()
    assert (models_dir / "vectorizer_masivo.pkl").is_file()
    metrics = json.loads((models_dir / "metrics_masivo.json").read_text(encoding="utf-8"))
    assert metrics["test_examples"] > 0
    assert old_classifier.read_bytes() == b"old model"
    assert old_metrics.read_text(encoding="utf-8") == '{"accuracy": 1.0}'

    loaded_model, loaded_vectorizer = classifier.load_model_assets()
    assert loaded_model.classes_.tolist() == result["model"].classes_.tolist()
    assert loaded_vectorizer.get_feature_names_out().tolist() == (
        result["vectorizer"].get_feature_names_out().tolist()
    )
    classifier.load_model_assets.cache_clear()


def test_massive_training_rejects_missing_or_empty_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PROCESSED_DIR", tmp_path)
    monkeypatch.setattr(trainer, "ensure_directories", lambda: None)
    dataset_path = tmp_path / "equipos_validados_masivo.json"

    with pytest.raises(FileNotFoundError, match="dataset masivo obligatorio"):
        trainer._load_massive_dataset()

    dataset_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset masivo está vacío"):
        trainer._load_massive_dataset()

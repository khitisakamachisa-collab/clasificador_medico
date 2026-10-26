from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from .config import Config
from .utils import MODELS_DIR, PROCESSED_DIR, ensure_directories


logger = logging.getLogger(__name__)

try:
    nlp = spacy.load(Config.NLP_MODEL)
except OSError:
    logger.warning(
        "No está instalado el modelo spaCy %s; se usará el tokenizador en blanco. "
        "La aplicación no descargará recursos automáticamente.",
        Config.NLP_MODEL,
    )
    nlp = spacy.blank("es")


def preprocess_text(text: str) -> str:
    """Preprocesa el texto siguiendo el pipeline del proyecto."""
    if text is None:
        text = ""
    text = str(text).lower()
    text = re.sub(r"[\d+]{4,}", " ", text)
    text = re.sub(r"[A-Z0-9]{3,}", " ", text)
    text = re.sub(r"[^a-záéíóúñü\s]", " ", text)
    doc = nlp(text)
    tokens = []
    for token in doc:
        if token.is_stop or token.is_punct or token.is_space:
            continue
        lemma = token.lemma_.lower().strip()
        if lemma and lemma.isalpha():
            tokens.append(lemma)
    return " ".join(tokens)


def load_validated_dataset(path: str | Path | None = None):
    ensure_directories()
    target = Path(path) if path else PROCESSED_DIR / "equipos_validados.json"
    if not target.exists():
        from .validator import validate_equipment_dataset
        validate_equipment_dataset()
    with open(target, "r", encoding="utf-8") as file:
        return json.load(file)


def train_model(dataset_path: str | Path | None = None):
    """Entrena un modelo NLP con validación cruzada y guarda artefactos."""
    ensure_directories()
    dataset = load_validated_dataset(dataset_path)
    texts = []
    labels = []
    for record in dataset:
        label = record.get("categoria") or "OTR-01"
        texts.append(preprocess_text(f"{record.get('nombre', '')} {record.get('marca', '')} {record.get('ubicacion', '')}"))
        labels.append(label)

    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    X = vectorizer.fit_transform(texts)
    model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    y_pred = cross_val_predict(model, X, labels, cv=skf)

    metrics = {
        "accuracy": round(accuracy_score(labels, y_pred), 4),
        "precision_macro": round(precision_score(labels, y_pred, average="macro", zero_division=0), 4),
        "precision_weighted": round(precision_score(labels, y_pred, average="weighted", zero_division=0), 4),
        "recall_macro": round(recall_score(labels, y_pred, average="macro", zero_division=0), 4),
        "recall_weighted": round(recall_score(labels, y_pred, average="weighted", zero_division=0), 4),
        "f1_macro": round(f1_score(labels, y_pred, average="macro", zero_division=0), 4),
        "f1_weighted": round(f1_score(labels, y_pred, average="weighted", zero_division=0), 4),
    }

    model.fit(X, labels)
    joblib.dump(model, MODELS_DIR / f"classifier_{Config.MODEL_VERSION}.pkl")
    joblib.dump(vectorizer, MODELS_DIR / f"vectorizer_{Config.MODEL_VERSION}.pkl")

    cm = confusion_matrix(labels, y_pred, labels=sorted(set(labels)))
    plt.figure(figsize=(10, 8))
    plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.title("Matriz de confusión")
    plt.colorbar()
    plt.savefig(MODELS_DIR / f"confusion_matrix_{Config.MODEL_VERSION}.png")
    plt.close()

    with open(MODELS_DIR / f"metrics_{Config.MODEL_VERSION}.json", "w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)

    return {"model": model, "vectorizer": vectorizer, "metrics": metrics}


def re_entrenar(
    dataset_path: str | Path | None = None,
    *,
    validar_correcciones: bool = True,
    nueva_version: str | None = None,
):
    """Valida ejemplos, entrena métricas cruzadas y activa la versión solicitada."""
    if not validar_correcciones:
        raise ValueError("El reentrenamiento requiere validar las correcciones guardadas.")
    from .corrections import load_training_examples, validate_saved_corrections

    correction_count = validate_saved_corrections()
    if correction_count == 0:
        raise ValueError("No hay correcciones aprobadas para reentrenar.")
    if correction_count < 10:
        raise ValueError(
            "Se necesitan al menos 10 correcciones aprobadas para reentrenar. "
            f"Actualmente: {correction_count}"
        )
    dataset = load_validated_dataset(dataset_path)
    dataset.extend(load_training_examples())
    labels = [item.get("categoria") or "OTR-01" for item in dataset]
    counts = Counter(labels)
    if len(counts) < 2 or min(counts.values()) < 2:
        raise ValueError("Se requieren al menos dos ejemplos por categoría para validar el modelo.")

    if nueva_version is None:
        version_number = 2
        while (Config.MODELS_DIR / f"classifier_v{version_number}.pkl").exists():
            version_number += 1
        version_name = f"v{version_number}"
    else:
        version_name = nueva_version
        if not re.fullmatch(r"v[1-9][0-9]*", version_name):
            raise ValueError("La versión debe tener formato vN, por ejemplo v2.")
        version_number = int(version_name[1:])

    classifier_path = Config.MODELS_DIR / f"classifier_{version_name}.pkl"
    vectorizer_path = Config.MODELS_DIR / f"vectorizer_{version_name}.pkl"
    metrics_path = Config.MODELS_DIR / f"metrics_{version_name}.json"
    if any(path.exists() for path in (classifier_path, vectorizer_path, metrics_path)):
        raise FileExistsError(f"Ya existen artefactos para la versión {version_name}.")

    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    texts = [preprocess_text(f"{item.get('nombre','')} {item.get('marca','')} {item.get('ubicacion','')}") for item in dataset]
    X = vectorizer.fit_transform(texts)
    model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
    folds = min(5, min(counts.values()))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    predictions = cross_val_predict(model, X, labels, cv=cv)
    accuracy = round(accuracy_score(labels, predictions), 4)
    model.fit(X, labels)
    ensure_directories()
    Config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, classifier_path)
    joblib.dump(vectorizer, vectorizer_path)
    with open(metrics_path, "w", encoding="utf-8") as file:
        json.dump({"accuracy": accuracy}, file, ensure_ascii=False, indent=2)

    Config.MODEL_VERSION = version_name
    from . import classifier

    classifier.load_model_assets.cache_clear()
    return {
        "status": "ok",
        "version": version_number,
        "modelo_activo": version_name,
        "nuevos_totales": len(dataset),
        "correcciones_validadas": correction_count,
        "accuracy": accuracy,
    }

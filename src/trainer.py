from __future__ import annotations

import json
import logging
import re
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
    joblib.dump(model, MODELS_DIR / "classifier_v1.pkl")
    joblib.dump(vectorizer, MODELS_DIR / "vectorizer_v1.pkl")

    cm = confusion_matrix(labels, y_pred, labels=sorted(set(labels)))
    plt.figure(figsize=(10, 8))
    plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.title("Matriz de confusión")
    plt.colorbar()
    plt.savefig(MODELS_DIR / "confusion_matrix_v1.png")
    plt.close()

    with open(MODELS_DIR / "metrics_v1.json", "w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)

    return {"model": model, "vectorizer": vectorizer, "metrics": metrics}


def re_entrenar(nuevos_ejemplos: list[dict], dataset_path: str | Path | None = None):
    """Añade nuevos ejemplos y entrena una nueva versión del modelo."""
    dataset = load_validated_dataset(dataset_path)
    dataset.extend(nuevos_ejemplos)
    version = 2
    while (MODELS_DIR / f"classifier_v{version}.pkl").exists():
        version += 1

    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    texts = [preprocess_text(f"{item.get('nombre','')} {item.get('marca','')} {item.get('ubicacion','')}") for item in dataset]
    labels = [item.get("categoria", "OTR-01") for item in dataset]
    X = vectorizer.fit_transform(texts)
    model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)
    model.fit(X, labels)
    joblib.dump(model, MODELS_DIR / f"classifier_v{version}.pkl")
    joblib.dump(vectorizer, MODELS_DIR / f"vectorizer_v{version}.pkl")
    return {"status": "ok", "version": version, "nuevos_totales": len(dataset)}

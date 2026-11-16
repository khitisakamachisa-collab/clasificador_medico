from __future__ import annotations

import json
import logging
import random
import re
import unicodedata
from collections import Counter
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    make_scorer,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict

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


def deduplicate_training_examples(*datasets: list[dict]) -> list[dict]:
    """Conserva una sola etiqueta por equipo y prioriza correcciones aprobadas."""
    priorities = {
        "": 0,
        "EMDN_VALIDATED_SUGGESTION": 1,
        "USER_CORRECTION": 2,
    }
    selected: dict[tuple[str, str] | tuple[str, int], tuple[int, int, dict]] = {}
    order = 0
    for dataset in datasets:
        for record in dataset:
            order += 1
            name = record.get("nombre") or record.get("nombre_equipo") or ""
            brand = record.get("marca") or ""
            normalized = unicodedata.normalize("NFKD", f"{name} {brand}".casefold())
            identity_text = re.sub(
                r"\s+", " ", "".join(
                    char for char in normalized if not unicodedata.combining(char)
                )
            ).strip()
            identity = ("equipo", identity_text) if identity_text else ("registro", order)
            source = str(record.get("source") or "")
            candidate = (priorities.get(source, 0), order, record)
            current = selected.get(identity)
            if current is None or candidate[:2] >= current[:2]:
                selected[identity] = candidate
    return [item[2] for item in selected.values()]


def load_validated_dataset(path: str | Path | None = None):
    ensure_directories()
    if path:
        target = Path(path)
        with open(target, "r", encoding="utf-8") as file:
            return json.load(file)

    demo_target = PROCESSED_DIR / "equipos_demo_nlp.json"
    if not demo_target.exists():
        from .validator import validate_equipment_dataset

        validate_equipment_dataset()
    with open(demo_target, "r", encoding="utf-8") as file:
        datasets = [json.load(file)]

    validated_target = PROCESSED_DIR / "equipos_validados.json"
    if validated_target.exists():
        with open(validated_target, "r", encoding="utf-8") as file:
            validated = json.load(file)
        datasets.append(
            [record for record in validated if record.get("estado") == "VALIDADO"]
        )
    return deduplicate_training_examples(*datasets)


def _cross_validated_predictions(model, features, labels: list[str]):
    counts = Counter(labels)
    evaluable_indices = [
        index for index, label in enumerate(labels) if counts[label] >= 2
    ]
    evaluable_labels = [labels[index] for index in evaluable_indices]
    evaluable_counts = Counter(evaluable_labels)
    if len(evaluable_counts) < 2:
        raise ValueError(
            "Se requieren al menos dos categorías con dos ejemplos cada una "
            "para calcular métricas de validación cruzada."
        )

    folds = min(5, min(evaluable_counts.values()))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    predictions = cross_val_predict(
        model, features[evaluable_indices], evaluable_labels, cv=cv
    )
    return predictions, evaluable_labels, folds


def train_model(dataset_path: str | Path | None = None):
    """Entrena un modelo NLP con validación cruzada y guarda artefactos."""
    ensure_directories()
    from .corrections import load_training_examples

    dataset = deduplicate_training_examples(
        load_validated_dataset(dataset_path), load_training_examples()
    )
    texts = []
    labels = []
    for record in dataset:
        label = record.get("categoria") or "OTR-01"
        texts.append(preprocess_text(f"{record.get('nombre', '')} {record.get('marca', '')} {record.get('ubicacion', '')}"))
        labels.append(label)

    vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    X = vectorizer.fit_transform(texts)
    model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced", random_state=42)

    y_pred, evaluation_labels, folds = _cross_validated_predictions(model, X, labels)

    metrics = {
        "accuracy": round(accuracy_score(evaluation_labels, y_pred), 4),
        "precision_macro": round(precision_score(evaluation_labels, y_pred, average="macro", zero_division=0), 4),
        "precision_weighted": round(precision_score(evaluation_labels, y_pred, average="weighted", zero_division=0), 4),
        "recall_macro": round(recall_score(evaluation_labels, y_pred, average="macro", zero_division=0), 4),
        "recall_weighted": round(recall_score(evaluation_labels, y_pred, average="weighted", zero_division=0), 4),
        "f1_macro": round(f1_score(evaluation_labels, y_pred, average="macro", zero_division=0), 4),
        "f1_weighted": round(f1_score(evaluation_labels, y_pred, average="weighted", zero_division=0), 4),
        "validation_examples": len(evaluation_labels),
        "excluded_singleton_examples": len(labels) - len(evaluation_labels),
        "cross_validation_folds": folds,
    }

    model.fit(X, labels)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODELS_DIR / f"classifier_{Config.MODEL_VERSION}.pkl")
    joblib.dump(vectorizer, MODELS_DIR / f"vectorizer_{Config.MODEL_VERSION}.pkl")

    cm = confusion_matrix(evaluation_labels, y_pred, labels=sorted(set(evaluation_labels)))
    plt.figure(figsize=(10, 8))
    plt.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.title("Matriz de confusión")
    plt.colorbar()
    plt.savefig(MODELS_DIR / f"confusion_matrix_{Config.MODEL_VERSION}.png")
    plt.close()

    with open(MODELS_DIR / f"metrics_{Config.MODEL_VERSION}.json", "w", encoding="utf-8") as file:
        json.dump(metrics, file, ensure_ascii=False, indent=2)

    return {"model": model, "vectorizer": vectorizer, "metrics": metrics}


def _load_massive_dataset(dataset_path: str | Path | None = None) -> list[dict]:
    """Carga el dataset masivo obligatorio y verifica sus registros."""
    target = Path(dataset_path) if dataset_path else (
        Config.PROCESSED_DIR / "equipos_validados_masivo.json"
    )
    if not target.is_file():
        raise FileNotFoundError(
            "No se encontró el dataset masivo obligatorio: "
            f"{target}"
        )

    with target.open(encoding="utf-8") as file:
        dataset = json.load(file)
    if not isinstance(dataset, list):
        raise ValueError(f"El dataset masivo debe ser una lista JSON: {target}")

    validated = [
        record for record in dataset
        if isinstance(record, dict) and record.get("estado") == "VALIDADO"
    ]
    if not validated:
        raise ValueError(f"El dataset masivo está vacío: {target}")
    if len(validated) != len(dataset):
        raise ValueError(
            "El dataset masivo contiene registros inválidos o no validados: "
            f"{len(dataset) - len(validated)} registro(s)."
        )
    if any(
        not (record.get("nombre") or record.get("nombre_equipo"))
        or not isinstance(record.get("categoria"), str)
        or not record["categoria"].strip()
        for record in validated
    ):
        raise ValueError(
            "Cada equipo validado debe incluir nombre y categoría no vacíos."
        )
    return validated


def _massive_holdout_indices(labels: list[str]) -> tuple[list[int], list[int]]:
    """Separa por categoría manteniendo ejemplos únicos solo en entrenamiento."""
    indices_by_label: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        indices_by_label.setdefault(label, []).append(index)

    rng = random.Random(42)
    train_indices: list[int] = []
    test_indices: list[int] = []
    for indices in indices_by_label.values():
        shuffled = indices.copy()
        rng.shuffle(shuffled)
        if len(shuffled) == 1:
            train_indices.extend(shuffled)
            continue
        test_count = max(1, round(len(shuffled) * 0.2))
        test_count = min(test_count, len(shuffled) - 1)
        test_indices.extend(shuffled[:test_count])
        train_indices.extend(shuffled[test_count:])
    if not test_indices:
        raise ValueError(
            "No hay suficientes registros de categorías repetidas para "
            "crear el conjunto de prueba."
        )
    rng.shuffle(train_indices)
    rng.shuffle(test_indices)
    return train_indices, test_indices


def _massive_vectorizer() -> FeatureUnion:
    """Combina palabras y fragmentos de texto para nombres técnicos variables."""
    return FeatureUnion(
        [
            (
                "palabras",
                TfidfVectorizer(max_features=5000, ngram_range=(1, 2)),
            ),
            (
                "caracteres",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 5),
                    max_features=30000,
                    sublinear_tf=True,
                ),
            ),
        ]
    )


def train_massive_model(dataset_path: str | Path | None = None):
    """Optimiza hiperparámetros con CV estratificada y entrena el modelo final."""
    ensure_directories()
    from .corrections import load_training_examples

    if dataset_path is None:
        merged_dataset_path = (
            Config.PROCESSED_DIR / "equipos_entrenamiento_final.json"
        )
        dataset_path = (
            merged_dataset_path
            if merged_dataset_path.is_file()
            else Config.PROCESSED_DIR / "equipos_validados_masivo.json"
        )
    equipos_validados = _load_massive_dataset(dataset_path)
    correcciones = load_training_examples()
    dataset = deduplicate_training_examples(equipos_validados, correcciones)
    if not dataset:
        raise ValueError("No hay ejemplos disponibles para entrenar el modelo masivo.")

    total_original = len(dataset)
    original_labels = [str(record["categoria"]).strip() for record in dataset]
    original_counts = Counter(original_labels)
    excluded_categories = sorted(
        category for category, count in original_counts.items() if count < 3
    )
    clean_dataset = [
        record for record in dataset if original_counts[str(record["categoria"]).strip()] >= 3
    ]
    total_clean = len(clean_dataset)
    excluded_minor_examples = total_original - total_clean
    fallback = not clean_dataset or len(
        {str(record["categoria"]).strip() for record in clean_dataset}
    ) < 2
    if fallback:
        # Si la limpieza impide entrenar varias clases, conservar el dataset original.
        training_dataset = dataset
    else:
        training_dataset = clean_dataset

    labels = [str(record["categoria"]).strip() for record in training_dataset]
    texts = [
        preprocess_text(
            f"{record.get('nombre') or record.get('nombre_equipo', '')} "
            f"{record.get('marca') or ''} {record.get('ubicacion') or ''}"
        )
        for record in training_dataset
    ]
    folds = 5
    category_counts = Counter(labels)
    evaluation_indices = [
        index for index, label in enumerate(labels)
        if category_counts[label] >= folds
    ]
    excluded_indices = [
        index for index, label in enumerate(labels)
        if category_counts[label] < folds
    ]
    evaluation_labels = [labels[index] for index in evaluation_indices]
    evaluation_categories = sorted(set(evaluation_labels))
    cv_splits = []
    if len(evaluation_categories) >= 2:
        # Las clases de 3-4 ejemplos permanecen siempre en train y no puntúan como test.
        splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        for train_positions, test_positions in splitter.split(
            evaluation_indices, evaluation_labels
        ):
            train_indices = [
                evaluation_indices[position] for position in train_positions
            ]
            train_indices.extend(excluded_indices)
            test_indices = [
                evaluation_indices[position] for position in test_positions
            ]
            cv_splits.append((train_indices, test_indices))

    pipeline = Pipeline(
        [
            ("vectorizer", _massive_vectorizer()),
            (
                "classifier",
                LogisticRegression(
                    C=1.0, max_iter=1000, class_weight="balanced", random_state=42
                ),
            ),
        ]
    )
    parameter_grid = [
        {
            "vectorizer": [TfidfVectorizer(max_features=5000)],
            "vectorizer__ngram_range": [(1, 1), (1, 2)],
            "vectorizer__min_df": [1, 2],
            "vectorizer__max_df": [0.75, 1.0],
            "classifier__C": [0.1, 1.0, 10.0],
        },
        {
            "vectorizer": [
                TfidfVectorizer(
                    analyzer="char_wb", max_features=30000, sublinear_tf=True
                )
            ],
            "vectorizer__ngram_range": [(2, 4), (2, 5), (3, 5)],
            "vectorizer__min_df": [1, 2],
            "classifier__C": [0.1, 1.0, 10.0],
        },
        {
            "vectorizer": [_massive_vectorizer()],
            "vectorizer__palabras__ngram_range": [(1, 1), (1, 2)],
            "vectorizer__palabras__min_df": [1, 2],
            "vectorizer__palabras__max_df": [0.75, 1.0],
            "classifier__C": [0.1, 1.0, 10.0],
        },
    ]

    if cv_splits:
        f1_scorer = make_scorer(
            f1_score,
            average="macro",
            labels=evaluation_categories,
            zero_division=0,
        )
        search = GridSearchCV(
            estimator=pipeline,
            param_grid=parameter_grid,
            scoring={"accuracy": "accuracy", "f1_macro": f1_scorer},
            refit="accuracy",
            cv=cv_splits,
            n_jobs=1,
            error_score="raise",
        )
        search.fit(texts, labels)
        model = search.best_estimator_.named_steps["classifier"]
        vectorizer = search.best_estimator_.named_steps["vectorizer"]
        best_index = search.best_index_
        accuracies = [
            float(search.cv_results_[f"split{index}_test_accuracy"][best_index])
            for index in range(folds)
        ]
        f1_scores = [
            float(search.cv_results_[f"split{index}_test_f1_macro"][best_index])
            for index in range(folds)
        ]
        mean_accuracy = float(search.cv_results_["mean_test_accuracy"][best_index])
        std_accuracy = float(search.cv_results_["std_test_accuracy"][best_index])
        mean_f1 = float(search.cv_results_["mean_test_f1_macro"][best_index])
        best_params = {
            key: value
            for key, value in search.best_params_.items()
            if key != "vectorizer"
        }
        selected_vectorizer = search.best_params_["vectorizer"]
        if isinstance(selected_vectorizer, FeatureUnion):
            best_params["vectorizer"] = "palabras_y_caracteres"
        elif selected_vectorizer.get_params(deep=False).get("analyzer") == "char_wb":
            best_params["vectorizer"] = "caracteres"
        else:
            best_params["vectorizer"] = "palabras"
    else:
        logger.warning(
            "No hay suficientes categorías con cinco ejemplos para validación cruzada; "
            "se entrenará con parámetros predeterminados y métricas CV no disponibles."
        )
        vectorizer = pipeline.named_steps["vectorizer"]
        features = vectorizer.fit_transform(texts)
        if len(set(labels)) < 2:
            model = DummyClassifier(strategy="most_frequent")
            best_params = {
                "classifier": "DummyClassifier(strategy='most_frequent')",
                "vectorizer": "palabras_y_caracteres",
            }
        else:
            model = pipeline.named_steps["classifier"]
            best_params = {
                "vectorizer": "palabras_y_caracteres",
                "classifier__C": 1.0,
            }
        model.fit(features, labels)
        accuracies = []
        f1_scores = []
        mean_accuracy = None
        std_accuracy = None
        mean_f1 = None
    metrics = {
        "accuracy": round(mean_accuracy, 4) if mean_accuracy is not None else None,
        "accuracy_std": round(std_accuracy, 4) if std_accuracy is not None else None,
        "accuracy_by_fold": [round(score, 4) for score in accuracies],
        "f1_macro": round(mean_f1, 4) if mean_f1 is not None else None,
        "f1_macro_std": round(float(np.std(f1_scores, ddof=0)), 4)
        if f1_scores else None,
        "f1_macro_by_fold": [round(score, 4) for score in f1_scores],
        "total_examples": len(training_dataset),
        "total_examples_original": total_original,
        "total_examples_cleaned": total_clean,
        "excluded_minor_categories": excluded_categories,
        "excluded_minor_examples": excluded_minor_examples,
        "cleaning_fallback": fallback,
        "best_params": best_params,
        "train_examples_by_fold": [len(train) for train, _ in cv_splits],
        "test_examples_by_fold": [len(test) for _, test in cv_splits],
        "evaluation_examples": len(evaluation_indices),
        "excluded_rare_examples": len(excluded_indices),
        "excluded_rare_categories": sorted(
            label for label, count in category_counts.items() if count < folds
        ),
        "evaluated_categories": evaluation_categories,
        "cross_validation_folds": folds if cv_splits else 0,
        "validated_examples": len(equipos_validados),
        "approved_corrections": len(correcciones),
        "evaluation": "stratified_5_fold_grid_search" if cv_splits else "fallback_no_cv",
    }

    if cv_splits:
        print("=" * 60)
        print("OPTIMIZACIÓN FINAL DEL MODELO NLP")
        print("=" * 60)
        print(f"Dataset original: {total_original} ejemplos")
        print(f"Dataset limpio (clases >= 3 ejemplos): {total_clean} ejemplos")
        print(
            "Se excluyeron "
            f"{len(excluded_categories)} categorías minoritarias con menos de "
            "3 ejemplos para mejorar la robustez del modelo"
        )
        print(f"Mejores parámetros encontrados: {best_params}")
        print()
        print("MÉTRICAS FINALES (5-Fold Cross-Validation):")
        print(f"  Accuracy Promedio: {mean_accuracy:.4f} (± {std_accuracy:.4f})")
        print(f"  F1-Score (macro):  {mean_f1:.4f}")
        print("=" * 60)
    else:
        print("=" * 60)
        print("OPTIMIZACIÓN FINAL DEL MODELO NLP")
        print("=" * 60)
        print(f"Dataset original: {total_original} ejemplos")
        print(f"Dataset limpio (clases >= 3 ejemplos): {total_clean} ejemplos")
        print(
            "Se excluyeron "
            f"{len(excluded_categories)} categorías minoritarias con menos de "
            "3 ejemplos para mejorar la robustez del modelo"
        )
        print(
            "AVISO: no hay suficientes ejemplos por clase para validación "
            "cruzada de 5 pliegues; se usaron parámetros predeterminados."
        )
        print("MÉTRICAS FINALES (5-Fold Cross-Validation): no disponibles")
        print("=" * 60)

    models_dir = Config.MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, models_dir / "nlp_model_optimizado.pkl")
    joblib.dump(vectorizer, models_dir / "vectorizer_optimizado.pkl")
    joblib.dump(model, models_dir / "nlp_model_final.pkl")
    joblib.dump(vectorizer, models_dir / "vectorizer_final.pkl")
    joblib.dump(model, models_dir / "nlp_model_masivo.pkl")
    joblib.dump(vectorizer, models_dir / "vectorizer_masivo.pkl")
    for metrics_path in (
        models_dir / "metrics_final.json",
        models_dir / "metrics_masivo.json",
    ):
        with metrics_path.open("w", encoding="utf-8") as file:
            json.dump(metrics, file, ensure_ascii=False, indent=2)

    print("Modelo optimizado guardado en: data/models/nlp_model_optimizado.pkl")
    print("Modelo final guardado en: data/models/nlp_model_final.pkl")
    print("Métricas guardadas en: data/models/metrics_final.json")
    print("=" * 60)
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
    dataset = deduplicate_training_examples(
        load_validated_dataset(dataset_path), load_training_examples()
    )
    labels = [item.get("categoria") or "OTR-01" for item in dataset]

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
    predictions, evaluation_labels, _ = _cross_validated_predictions(model, X, labels)
    accuracy = round(accuracy_score(evaluation_labels, predictions), 4)
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


if __name__ == "__main__":
    train_massive_model()

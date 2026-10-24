from __future__ import annotations

import logging
import json
import re
import unicodedata
from zipfile import BadZipFile
from pathlib import Path
from Levenshtein import ratio

import pandas as pd

from .config import Config
from .utils import PROCESSED_DIR, RAW_DIR, ensure_directories


logger = logging.getLogger(__name__)
_DATABASE_CACHE: dict[tuple[str, int | None], dict] = {}


def _normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _empty_database(source: Path) -> dict:
    return {
        "hierarchy": {},
        "flat": {},
        "stats": {"total": 0, "by_level": {}},
        "prefix_index": {},
        "available": False,
        "source": str(source),
        "_search_frame": pd.DataFrame(columns=["code", "name", "normalized_name"]),
    }


def _find_column(columns: dict[str, object], predicate) -> object | None:
    return next((column for normalized, column in columns.items() if predicate(normalized)), None)


def _save_database(database: dict, output_path: str | Path | None = None) -> None:
    if not database.get("available"):
        return
    ensure_directories()
    target = Path(output_path) if output_path else PROCESSED_DIR / "emdn_database.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in database.items() if not key.startswith("_")}
    temporary = target.with_suffix(target.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    temporary.replace(target)


def load_emdn_database(
    path: str | Path | None = None, output_path: str | Path | None = None
) -> dict:
    """Carga en memoria únicamente los códigos terminales del Excel oficial EMDN."""
    target = Path(path) if path else Config.EMDN_EXCEL_PATH
    target = target.resolve()
    modified = target.stat().st_mtime_ns if target.exists() else None
    cache_key = (str(target), modified)
    if cache_key in _DATABASE_CACHE:
        database = _DATABASE_CACHE[cache_key]
        if output_path is not None:
            _save_database(database, output_path)
        return database

    if modified is None:
        logger.warning(
            "No se encontró el Excel EMDN 2026 en %s; la clasificación EMDN queda pendiente.",
            target,
        )
        database = _empty_database(target)
        _DATABASE_CACHE[cache_key] = database
        return database

    try:
        frame = pd.read_excel(target, header=1)
        columns = {_normalize_header(column): column for column in frame.columns}
        code_column = _find_column(columns, lambda name: name == "code" or name.endswith(" code"))
        term_column = _find_column(columns, lambda name: name.startswith("term emdn"))
        terminal_column = _find_column(columns, lambda name: name.startswith("terminal level"))
        level_column = _find_column(columns, lambda name: name == "level")
        category_column = _find_column(columns, lambda name: name == "category")
        category_description_column = _find_column(
            columns, lambda name: name.startswith("category description")
        )

        if code_column is None or term_column is None or terminal_column is None:
            raise ValueError("Faltan las columnas CODE, TERM EMDN o TERMINAL LEVEL en el Excel.")

        frame = frame.loc[
            frame[terminal_column].fillna("").astype(str).str.strip().str.upper().eq("YES")
        ].copy()
        frame[code_column] = frame[code_column].fillna("").astype(str).str.strip()
        frame[term_column] = frame[term_column].fillna("").astype(str).str.strip()
        frame = frame.loc[frame[code_column].ne("") & frame[term_column].ne("")]

        flat = {}
        for _, row in frame.iterrows():
            code = row[code_column]
            level_value = row[level_column] if level_column is not None else None
            flat[code] = {
                "name": row[term_column],
                "term": row[term_column],
                "parent": None,
                "level": int(level_value) if pd.notna(level_value) else None,
                "terminal_level": "YES",
                "category": str(row[category_column]).strip() if category_column is not None else None,
                "category_description": (
                    str(row[category_description_column]).strip()
                    if category_description_column is not None
                    else None
                ),
            }

        search_frame = pd.DataFrame(
            {
                "code": list(flat),
                "name": [item["name"] for item in flat.values()],
                "normalized_name": [_normalize_text(item["name"]) for item in flat.values()],
            }
        )
        prefix_index: dict[str, list[dict[str, str]]] = {}
        for code, item in flat.items():
            for prefix_length in range(2, len(code) + 1):
                prefix_index.setdefault(code[:prefix_length], []).append(
                    {"code": code, "term": item["term"]}
                )
        levels = [item["level"] for item in flat.values() if item["level"] is not None]
        database = {
            "hierarchy": {},
            "flat": flat,
            "prefix_index": prefix_index,
            "stats": {
                "total": len(flat),
                "by_level": {str(level): levels.count(level) for level in sorted(set(levels))},
            },
            "available": True,
            "source": str(target),
            "_search_frame": search_frame,
        }
    except (BadZipFile, OSError, TypeError, ValueError, KeyError) as exc:
        logger.warning("No se pudo cargar el Excel EMDN 2026 (%s): %s", target, exc)
        database = _empty_database(target)

    _DATABASE_CACHE[cache_key] = database
    _save_database(database, output_path)
    return database


def import_emdn_excel(excel_path: str | Path | None = None, output_path: str | Path | None = None):
    """Carga el Excel oficial en memoria; no genera ni conserva códigos sintéticos."""
    return load_emdn_database(excel_path, output_path)


def validar_codigo_emdn(codigo: str, database: dict | None = None) -> bool:
    """Comprueba que el código existe y es terminal en el Excel oficial cargado."""
    database = database if database is not None else load_emdn_database()
    item = database.get("flat", {}).get(str(codigo).strip())
    return bool(item and item.get("terminal_level") == "YES")


def buscar_emdn(
    keyword: str | list[str],
    database: dict | None = None,
    limit: int = 5,
    prefix: str | None = None,
):
    """Busca términos entre los códigos terminales oficiales y devuelve los más cercanos."""
    database = database if database is not None else load_emdn_database()
    flat = database.get("flat", {})
    if not flat or limit <= 0:
        return []

    keywords = keyword if isinstance(keyword, list) else [keyword]
    normalized_keywords = [_normalize_text(term) for term in keywords if _normalize_text(term)]
    if not normalized_keywords:
        return []

    search_frame = database.get("_search_frame")
    if not isinstance(search_frame, pd.DataFrame):
        search_frame = pd.DataFrame(
            {
                "code": list(flat),
                "name": [item.get("name", "") for item in flat.values()],
                "normalized_name": [_normalize_text(item.get("name", "")) for item in flat.values()],
            }
        )

    if prefix:
        indexed_codes = {
            item["code"] for item in database.get("prefix_index", {}).get(prefix, [])
        }
        if not indexed_codes:
            indexed_codes = {code for code in flat if code.startswith(prefix)}
        search_frame = search_frame.loc[search_frame["code"].isin(indexed_codes)]
        if search_frame.empty:
            return []

    tokens = sorted(
        {token for term in normalized_keywords for token in term.split()},
        key=len,
        reverse=True,
    )
    token_pattern = r"(?:^|\s)(?:" + "|".join(re.escape(token) for token in tokens) + r")"
    candidate_frame = search_frame.loc[
        search_frame["normalized_name"].str.contains(token_pattern, regex=True, na=False)
    ]
    if candidate_frame.empty:
        candidate_frame = search_frame

    scored = []
    for row in candidate_frame.itertuples(index=False):
        name = row.normalized_name
        name_tokens = set(name.split())
        name_tokens |= {
            token[:-1] for token in name_tokens if token.endswith("s") and len(token) > 3
        }
        best_score = 0.0
        for term in normalized_keywords:
            term_tokens = set(term.split())
            overlap = len(term_tokens & name_tokens) / len(term_tokens)
            phrase_match = 0.25 if term in name else 0.0
            specificity = min(len(term_tokens), 4) / 4
            lexical_score = (
                0.65 * overlap + 0.1 * specificity + phrase_match if overlap else 0.0
            )
            similarity = ratio(term, name)
            fuzzy_score = similarity * 0.75 if similarity >= 0.6 else 0.0
            score = max(lexical_score, fuzzy_score)
            best_score = max(best_score, score)
        if best_score > 0:
            scored.append((row.code, round(best_score, 4), row.name))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
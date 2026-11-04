from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.emdn_importer import load_emdn_database
from src.rules_dictionary import (
    EMDN_ADDITIONAL_CATEGORY_PREFIXES,
    EMDN_PREFIXES,
)
from src.utils import CATEGORÍAS, PROCESSED_DIR

DEFAULT_INPUT = ROOT / "data" / "raw" / "equipos_medicos_emdn_2026_corregido.xlsx"
DEFAULT_MODEL = "qwen2.5:7b"
MAX_ROWS = 200
MIN_ROWS = 1
MIN_EMDN_SIMILARITY = 0.40
_SPANISH_TO_ENGLISH_TERMS = {
    "anestesia": "anaesthesia",
    "vaporizador": "vaporizer",
    "ventilador": "ventilator",
    "electrocardiografo": "electrocardiograph",
    "ecografo": "ultrasound",
    "ecografia": "ultrasound",
    "ultrasonido": "ultrasound",
    "portatil": "portable",
    "registrador": "recorder",
    "marcapasos": "pacemaker",
    "bomba": "pump",
    "jeringa": "syringe",
    "infusion": "infusion",
    "desfibrilador": "defibrillator",
    "incubadora": "incubator",
    "fototerapia": "phototherapy",
    "autoclave": "autoclave",
    "monitor": "monitor",
    "cama": "bed",
    "silla": "chair",
    "rayos": "x ray",
    "tomografo": "tomograph",
    "resonador": "resonance",
    "centrifuga": "centrifuge",
    "microscopio": "microscope",
    "analizador": "analyser",
    "estacion": "station",
    "trabajo": "work",
    "presion": "pressure",
    "concentrador": "concentrator",
    "oxigeno": "oxygen",
    "magnetico": "magnetic",
    "magnetica": "magnetic",
}
_SPANISH_TO_ENGLISH_PHRASES = {
    "bisturi armonico": "ultrasonic open surgery handpieces",
}
_ANCILLARY_TERM_MARKERS = {
    "accessories",
    "consumables",
    "software",
    "parts",
    "leads",
    "probes",
    "receivers",
    "transmitters",
}

# Se reutilizan los prefijos oficiales compartidos con el validador.
MAPEO_CATEGORIAS_A_PREFIJOS = {
    category: (prefix,) for category, prefix in EMDN_PREFIXES.items()
}
for category, prefixes in EMDN_ADDITIONAL_CATEGORY_PREFIXES.items():
    MAPEO_CATEGORIAS_A_PREFIJOS[category] = (
        *MAPEO_CATEGORIAS_A_PREFIJOS.get(category, ()),
        *prefixes,
    )
# OTR-01 no identifica una familia EMDN única; no se asigna un código automático.
MAPEO_CATEGORIAS_A_PREFIJOS["OTR-01"] = ()


def _normalize_header(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized.casefold()).strip()


def find_name_column(frame: pd.DataFrame, requested: str | None = None):
    """Identifica la columna del nombre del equipo o valida la indicada."""
    if requested:
        for column in frame.columns:
            if str(column) == requested:
                return column
        raise ValueError(f"No existe la columna indicada: {requested}")

    normalized_columns = {
        _normalize_header(column): column for column in frame.columns
    }
    candidates = (
        "nombre equipo",
        "nombre del equipo",
        "equipo medico",
        "nombre",
        "descripcion equipo",
        "descripcion del equipo",
        "descripcion",
        "device name",
        "equipment name",
        "device description",
        "equipment description",
    )
    for candidate in candidates:
        if candidate in normalized_columns:
            return normalized_columns[candidate]

    raise ValueError(
        "No se identificó la columna del nombre del equipo. "
        "Indícala con --name-column."
    )


def _prompt_for_equipment(name: str) -> list[dict[str, str]]:
    category_list = "\n".join(
        f"- {code}: {details['nombre']}"
        for code, details in CATEGORÍAS.items()
    )
    return [
        {
            "role": "system",
            "content": (
                "Eres un asistente de preclasificación de dispositivos médicos. "
                "Responde exclusivamente con un objeto JSON válido que contenga "
                "la clave categoria_sugerida. Solo debes sugerir el código de "
                "categoría propia que corresponda al equipo. No incluyas ni "
                "inventes códigos EMDN; esos códigos se buscarán después en el "
                "catálogo oficial. Formato de respuesta: "
                '{"categoria_sugerida": "ANE-01"}.\n'
                f"Categorías internas permitidas:\n{category_list}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Devuelve solo la categoría propia para este equipo, sin códigos "
                f"EMDN: "
                f"{json.dumps(name, ensure_ascii=False)}"
            ),
        },
    ]


def _decode_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("El modelo no devolvió un objeto JSON válido.") from exc
    if not isinstance(decoded, dict):
        raise ValueError("La respuesta del modelo debe ser un objeto JSON.")
    return decoded


def query_ollama(
    messages: list[dict[str, str]], model: str, base_url: str, timeout: int
) -> dict:
    """Consulta un servidor Ollama local y devuelve la sugerencia JSON."""
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/api/chat"):
        endpoint += "/api/chat"
    payload = json.dumps(
        {"model": model, "messages": messages, "stream": False, "format": "json"}
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Ollama respondió HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(
            "No se pudo conectar con Ollama. Verifica que el servicio local esté activo."
        ) from exc
    content = body.get("message", {}).get("content")
    if not isinstance(content, str):
        raise ValueError("Ollama no devolvió contenido de mensaje.")
    return _decode_json_object(content)


def query_openai_compatible(
    messages: list[dict[str, str]],
    model: str,
    base_url: str,
    api_key: str | None,
    timeout: int,
) -> dict:
    """Consulta un endpoint OpenAI-compatible configurado explícitamente."""
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"El endpoint de lenguaje respondió HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError("No se pudo conectar con el endpoint de lenguaje.") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("El endpoint no devolvió una respuesta de chat válida.") from exc
    if not isinstance(content, str):
        raise ValueError("El endpoint no devolvió contenido de texto.")
    return _decode_json_object(content)


def _load_source_rows(
    input_path: Path, limit: int, name_column: str | None
) -> list[str]:
    if not input_path.is_file():
        raise FileNotFoundError(f"No se encontró el archivo de equipos: {input_path}")
    extension = input_path.suffix.casefold()
    if extension == ".json":
        frame = pd.read_json(input_path).head(limit)
    elif extension in {".xlsx", ".xls"}:
        frame = pd.read_excel(input_path, nrows=limit)
    else:
        raise ValueError(
            f"Formato de archivo no compatible: {extension or '(sin extensión)'}. "
            "Usa JSON, XLSX o XLS."
        )

    # La misma detección de columna se aplica a los archivos JSON y Excel.
    column = find_name_column(frame, name_column)
    names = []
    for value in frame[column].tolist():
        if pd.isna(value):
            continue
        name = str(value).strip()
        if name:
            names.append(name)
    if not names:
        raise ValueError("No se encontraron nombres de equipos en las filas iniciales.")
    return names


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def buscar_codigo_terminal(
    nombre_equipo: str, categoria_propia: str, emdn_database: dict
) -> tuple[str, str, float]:
    """Busca el término EMDN terminal más parecido dentro de la categoría."""
    prefixes = MAPEO_CATEGORIAS_A_PREFIJOS.get(categoria_propia, ())
    if not prefixes:
        return "", "", 0.0

    normalized_name = _normalize_search_text(nombre_equipo)
    translated_tokens = [
        _SPANISH_TO_ENGLISH_TERMS.get(token, token)
        for token in normalized_name.split()
    ]
    translated_name = " ".join(translated_tokens)
    for spanish_phrase, english_phrase in _SPANISH_TO_ENGLISH_PHRASES.items():
        translated_name = translated_name.replace(
            _normalize_search_text(spanish_phrase),
            _normalize_search_text(english_phrase),
        )
    best_code = ""
    best_term = ""
    best_similarity = 0.0
    for code, item in emdn_database.get("flat", {}).items():
        if not code.startswith(prefixes):
            continue
        term = str(item.get("term") or item.get("name") or "")
        normalized_term = _normalize_search_text(term)
        term_tokens = set(normalized_term.split())
        if (
            term_tokens & _ANCILLARY_TERM_MARKERS
            and not term_tokens.intersection(translated_tokens)
        ):
            continue
        if (
            {"blood", "pressure"}.issubset(term_tokens)
            and not {"blood", "pressure"}.intersection(translated_tokens)
        ):
            continue
        similarity = max(
            SequenceMatcher(None, normalized_name, normalized_term).ratio(),
            SequenceMatcher(None, translated_name, normalized_term).ratio(),
        )
        if similarity > best_similarity:
            best_code = code
            best_term = term
            best_similarity = similarity

    return best_code, best_term, best_similarity


def generate_suggestions(
    names: list[str],
    *,
    provider: str,
    model: str,
    ollama_url: str,
    api_base_url: str | None,
    api_key: str | None,
    timeout: int,
) -> list[dict[str, str | float | bool]]:
    emdn_database = load_emdn_database()
    if not emdn_database.get("available"):
        raise RuntimeError(
            "No se pudo cargar el catálogo oficial EMDN; no es posible sugerir códigos."
        )

    suggestions = []
    for index, name in enumerate(names, start=1):
        messages = _prompt_for_equipment(name)
        try:
            if provider == "ollama":
                response = query_ollama(messages, model, ollama_url, timeout)
            else:
                if not api_base_url:
                    raise ValueError(
                        "Configura LLM_API_BASE_URL o indica --api-base-url."
                    )
                response = query_openai_compatible(
                    messages, model, api_base_url, api_key, timeout
                )
            category = str(response.get("categoria_sugerida") or "").strip().upper()
            code, term, similarity = buscar_codigo_terminal(
                name, category, emdn_database
            )
            category_is_valid = category in CATEGORÍAS
            has_match = bool(code) and similarity >= MIN_EMDN_SIMILARITY
            suggestions.append(
                {
                    "nombre_equipo": name,
                    "categoria_sugerida": category,
                    "emdn_sugerido": code if has_match else "",
                    "termino_emdn": term,
                    "similitud": round(similarity, 4),
                    "fuente_codigo": "BUSQUEDA_DIFUSA",
                    "requiere_desambiguacion": not (category_is_valid and has_match),
                }
            )
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"No se pudo preclasificar el registro {index} ({name!r}): {exc}"
            ) from exc
    return suggestions


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preclasifica equipos con un modelo de lenguaje y valida cada sugerencia "
            "contra el Excel EMDN oficial."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--name-column")
    parser.add_argument(
        "--limit",
        type=int,
        default=150,
        help=f"Filas iniciales a leer ({MIN_ROWS}-{MAX_ROWS}; por defecto 150).",
    )
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai-compatible"),
        default="ollama",
        help="Ollama local (predeterminado) o API OpenAI-compatible configurada.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or DEFAULT_MODEL,
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    parser.add_argument(
        "--api-base-url",
        default=os.getenv("LLM_API_BASE_URL"),
        help="URL base del endpoint configurado (no se usa con Ollama).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        help="Clave opcional para el endpoint OpenAI-compatible.",
    )
    parser.add_argument("--timeout", type=int, default=120)
    arguments = parser.parse_args()

    if not MIN_ROWS <= arguments.limit <= MAX_ROWS:
        parser.error(f"--limit debe estar entre {MIN_ROWS} y {MAX_ROWS}.")
    if arguments.timeout < 1:
        parser.error("--timeout debe ser mayor que cero.")
    if arguments.provider == "openai-compatible" and not arguments.api_base_url:
        parser.error(
            "El proveedor openai-compatible requiere --api-base-url o LLM_API_BASE_URL."
        )

    names = _load_source_rows(
        arguments.input, arguments.limit, arguments.name_column
    )
    suggestions = generate_suggestions(
        names,
        provider=arguments.provider,
        model=arguments.model,
        ollama_url=arguments.ollama_url,
        api_base_url=arguments.api_base_url,
        api_key=arguments.api_key,
        timeout=arguments.timeout,
    )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    suggestions_path = PROCESSED_DIR / "sugerencias_ia_masivo.json"
    suggestions_path.write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    validated_path = PROCESSED_DIR / "equipos_validados_masivo.json"
    discrepancies_path = PROCESSED_DIR / "discrepancias_masivo.json"
    validator_script = ROOT / "scripts" / "validator.py"
    command = [
        sys.executable,
        str(validator_script),
        "--input",
        str(suggestions_path),
        "--valid-output",
        str(validated_path),
        "--discrepancies-output",
        str(discrepancies_path),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    with validated_path.open("r", encoding="utf-8") as file:
        validated = json.load(file)
    with discrepancies_path.open("r", encoding="utf-8") as file:
        discrepancies = json.load(file)
    print(
        f"{len(validated)} validados, {len(discrepancies)} discrepancias para revisión manual"
    )


if __name__ == "__main__":
    main()

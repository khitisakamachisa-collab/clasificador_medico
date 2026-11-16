from __future__ import annotations

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "discrepancias_masivo.json"
DEFAULT_EXCEL = ROOT / "data" / "raw" / "emdn_codes_2026.xlsx"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "propuestas_correccion.json"
MIN_SIMILARITY = 0.25


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def normalize_header(value: object) -> str:
    return normalize(value)


def find_column(columns: list[object], expected: str) -> object:
    return next(
        (column for column in columns if normalize_header(column) == expected),
        None,
    )


def load_catalog(path: Path) -> tuple[dict[str, dict], list[dict]]:
    frame = pd.read_excel(path, sheet_name=0, header=1, dtype=str)
    code_column = find_column(list(frame.columns), "code")
    term_column = next(
        (
            column
            for column in frame.columns
            if normalize_header(column).startswith("term emdn")
        ),
        None,
    )
    terminal_column = next(
        (
            column
            for column in frame.columns
            if normalize_header(column).startswith("terminal level")
        ),
        None,
    )
    if code_column is None or term_column is None or terminal_column is None:
        raise ValueError(
            "El Excel debe incluir las columnas CODE, TERM EMDN y TERMINAL LEVEL."
        )

    catalog: dict[str, dict] = {}
    entries = []
    for _, row in frame.iterrows():
        code_value = row[code_column]
        term_value = row[term_column]
        terminal_level_value = row[terminal_column]
        code = "" if pd.isna(code_value) else str(code_value).strip()
        term = "" if pd.isna(term_value) else str(term_value).strip()
        terminal_value = (
            "" if pd.isna(terminal_level_value) else str(terminal_level_value).strip().upper()
        )
        if not code or not term:
            continue
        entry = {
            "code": code,
            "term": term,
            "normalized_term": normalize(term),
            "terminal": terminal_value == "YES",
        }
        catalog[code] = entry
        entries.append(entry)
    if not catalog:
        raise ValueError(f"No se encontraron códigos EMDN en {path}.")
    return catalog, entries


# The target terms are exact terms from the official Excel. A match is accepted
# only when it is unique in the catalog; fuzzy similarity alone is not clinical
# evidence for assigning a code.
RECOMMENDATIONS = {
    "tomografo computarizado": {
        "term": "COMPUTED TOMOGRAPHS (CT)",
        "requires_disambiguation": True,
        "justification": (
            "El nombre identifica la familia de tomografía computarizada, pero "
            "no indica el número de cortes. Se propone el nodo común "
            "COMPUTED TOMOGRAPHS (CT); se requiere la ficha del fabricante para "
            "seleccionar una hoja terminal."
        ),
    },
    "balon de contrapulsacion intraaortico": {
        "term": "AORTIC PUMPS",
        "justification": (
            "La contrapulsación intraaórtica utiliza un balón sincronizado para "
            "apoyar temporalmente la función circulatoria. El término EMDN "
            "AORTIC PUMPS identifica esta familia; el Excel confirma el código "
            "como terminal."
        ),
    },
    "mesa de operaciones para neurocirugia": {
        "term": "OPERATING TABLES",
        "justification": (
            "Es una mesa diseñada para posicionar al paciente durante una "
            "intervención quirúrgica. La especialidad de neurocirugía no crea "
            "una subcategoría EMDN distinta en el nombre disponible."
        ),
    },
    "generador de plasma de argon": {
        "term": "DIATHERMOCOAGULATORS",
        "justification": (
            "La coagulación con plasma de argón aplica energía de alta frecuencia "
            "para hemostasia. Por su función terapéutica corresponde a "
            "DIATHERMOCOAGULATORS, no a equipos de diagnóstico por imagen."
        ),
    },
    "autoclave de vapor de mesa": {
        "term": "SMALL LOAD AUTOCLAVES WITH A CHAMBER SMALLER THAN 1 STANDARD STERILISATION UNIT",
        "justification": (
            "La esterilización por vapor y el formato de mesa identifican un "
            "autoclave de carga pequeña. El término corresponde a una hoja "
            "terminal EMDN; se debe confirmar el volumen de cámara con la ficha "
            "técnica antes de cerrar la clasificación."
        ),
    },
    "esterilizador de baja temperatura con peroxido de hidrogeno": {
        "term": "CLEANING, DISINFECTION AND STERILISATION INSTRUMENTS",
        "requires_disambiguation": True,
        "justification": (
            "El proceso de baja temperatura con peróxido de hidrógeno puede "
            "corresponder a tecnologías EMDN distintas según utilice plasma u "
            "otro proceso químico. Se propone el nodo común "
            "CLEANING, DISINFECTION AND STERILISATION INSTRUMENTS hasta conocer "
            "el ciclo y la tecnología exactos del fabricante."
        ),
    },
    "manifold automatico para cilindros de oxigeno": {
        "term": "MEDICAL/MEDICINAL GAS PIPELINE SYSTEMS AND RELATED ACCESSORIES",
        "justification": (
            "El manifold conmuta y suministra oxígeno desde cilindros a la red "
            "de gases medicinales. El término EMDN cubre los sistemas de "
            "distribución de gases y sus accesorios."
        ),
    },
    "arco en c movil para fluoroscopia": {
        "term": "FLUOROSCOPY DEVICES",
        "justification": (
            "El arco en C obtiene imágenes dinámicas mediante rayos X durante "
            "procedimientos. La función principal es fluoroscopia; la movilidad "
            "no cambia el término EMDN identificado."
        ),
    },
    "mastografo digital": {
        "term": "DIGITAL MAMMOGRAPHY SYSTEMS",
        "justification": (
            "El nombre especifica mamografía digital, lo que permite seleccionar "
            "la hoja terminal digital y distinguirla de los sistemas "
            "convencionales."
        ),
    },
    "fluoroscopio digital para procedimientos": {
        "term": "FLUOROSCOPY DEVICES",
        "justification": (
            "El equipo produce imágenes fluoroscópicas en tiempo real para guiar "
            "procedimientos. El nombre no aporta un subtipo EMDN adicional "
            "respecto de los dispositivos de fluoroscopia."
        ),
    },
    "congelador para plasma sanguineo": {
        "term": "BLOOD AND BLOOD COMPONENTS FREEZERS",
        "justification": (
            "El equipo conserva plasma sanguíneo congelado; el término EMDN "
            "distingue los congeladores para sangre y sus componentes de los "
            "refrigeradores de banco de sangre."
        ),
    },
    "centrifuga refrigerada para bolsas de sangre": {
        "term": "CENTRIFUGES",
        "justification": (
            "La función principal es separar componentes sanguíneos por "
            "centrifugación. El catálogo ofrece CENTRIFUGES como hoja terminal "
            "general; la refrigeración y el uso de bolsas describen "
            "características técnicas, no una hoja específica encontrada."
        ),
    },
    "sistema de aferesis terapeutica": {
        "term": "THERAPEUTIC APHERESIS EQUIPMENT",
        "justification": (
            "El nombre especifica aféresis terapéutica, que se diferencia de la "
            "aféresis para donación. El término EMDN coincide con el propósito "
            "clínico indicado."
        ),
    },
    "bilirrubinometro transcutaneo neonatal": {
        "term": "TRANSCUTANEOUS BILIRUBINOMETERS",
        "justification": (
            "Mide bilirrubina neonatal de forma transcutánea y no invasiva. El "
            "catálogo contiene una hoja terminal específica para "
            "bilirrubinómetros transcutáneos."
        ),
    },
    "bascula electronica para recien nacido": {
        "term": "NEONATAL SCALES",
        "justification": (
            "Es una báscula destinada a pesar recién nacidos. La aplicación "
            "neonatal determina la hoja terminal específica; el mecanismo "
            "electrónico no modifica esa clasificación."
        ),
    },
    "aspirador de secreciones portatil": {
        "term": "MUCOUS ASPIRATORS",
        "requires_disambiguation": True,
        "justification": (
            "La aspiración de secreciones respiratorias corresponde a la familia "
            "EMDN de aspiradores de mucosidad. Como el catálogo divide las hojas "
            "por configuración de cámara y el nombre no la especifica, se "
            "propone MUCOUS ASPIRATORS como nodo padre hasta verificar el "
            "diseño del recipiente."
        ),
    },
    "espirometro diagnostico de consultorio": {
        "term": "CLINICAL/DIAGNOSTIC SPIROMETERS",
        "justification": (
            "El equipo mide parámetros ventilatorios para evaluación clínica. "
            "El uso diagnóstico indicado coincide con la hoja terminal de "
            "espirómetros clínico-diagnósticos."
        ),
    },
    "unidad de traccion cervical y lumbar": {
        "term": "TRACTION SYSTEMS",
        "justification": (
            "El equipo aplica tracción terapéutica musculoesquelética. El "
            "catálogo incluye TRACTION SYSTEMS como hoja terminal general; la "
            "región anatómica especificada no requiere elegir otro subtipo."
        ),
    },
    "camilla de emergencia hidraulica": {
        "term": "EMERGENCY AND TRAUMATOLOGY STRETCHERS",
        "justification": (
            "El uso para atención de emergencia identifica la hoja terminal "
            "EMERGENCY AND TRAUMATOLOGY STRETCHERS. El accionamiento hidráulico "
            "es una característica mecánica, no un subtipo EMDN."
        ),
    },
    "camilla de transporte para ambulancia": {
        "term": "PATIENT TRANSFER STRETCHERS",
        "requires_disambiguation": True,
        "justification": (
            "El término identifica una camilla para traslado de pacientes, pero "
            "no especifica si es auto-cargable, de emergencia u otra variante. "
            "Se asigna PATIENT TRANSFER STRETCHERS como nodo padre hasta "
            "confirmar el mecanismo y uso previsto."
        ),
    },
}

MANUAL_REASONS = {
    "calentador de mantas quirurgicas": (
        "El catálogo revisado no permite confirmar una hoja EMDN para un "
        "calentador de mantas quirúrgicas. Los términos cercanos describen "
        "mantas/cobertores o calentamiento de fluidos, que no son equivalentes."
    ),
    "lampara de exploracion movil": (
        "No se puede equiparar una lámpara móvil de exploración con una lámpara "
        "cialítica quirúrgica sin confirmar su uso previsto y diseño óptico."
    ),
    "escaner intraoral odontologico": (
        "Un escáner óptico intraoral para impresiones digitales no equivale a "
        "un sistema de videorradiografía intraoral. Se requiere confirmar la "
        "tecnología y el uso previsto del fabricante."
    ),
    "incubadora de indicadores biologicos": (
        "No se identificó un término EMDN específico que confirme la función "
        "combinada de incubación y lectura de indicadores biológicos. Revisar "
        "si el fabricante la clasifica como equipo de laboratorio o de control "
        "de esterilización."
    ),
    "sistema robotizado de preparacion de dosis": (
        "La preparación automatizada de dosis puede abarcar dispensación, "
        "fraccionamiento o reenvasado. El nombre no determina cuál de esas "
        "funciones EMDN corresponde."
    ),
    "refrigerador de farmacia con puerta de vidrio": (
        "No se debe asignar el término de refrigeradores de banco de sangre a "
        "un refrigerador farmacéutico. No se confirmó una hoja EMDN específica "
        "para este uso."
    ),
    "empacadora de dosis unitarias": (
        "El catálogo no ofrece una coincidencia específica confirmada para una "
        "empacadora farmacéutica de dosis unitarias. Verificar si el producto "
        "es un dispositivo médico o equipo auxiliar de farmacia."
    ),
    "regulador de presion para cilindro de oxigeno": (
        "Un regulador de presión para cilindro no debe confundirse con un "
        "concentrador de oxígeno ni con un regulador genérico de flujo sin "
        "confirmar la función y el uso previsto EMDN."
    ),
    "computadora todo en uno para consultorio": (
        "El nombre describe una computadora de uso general. No se confirmó que "
        "sea un dispositivo médico ni un equipo EMDN de soporte médico."
    ),
    "impresora laser para expediente clinico": (
        "La impresión de expedientes clínicos es una función administrativa; "
        "no se identificó una categoría EMDN específica para la impresora."
    ),
    "impresora de etiquetas para laboratorio": (
        "La impresora de etiquetas es un periférico auxiliar y no debe "
        "confundirse con impresoras de casetes o portaobjetos de laboratorio."
    ),
    "lector de codigo de barras para identificacion clinica": (
        "El lector de códigos de barras es un periférico de identificación. "
        "No se confirmó una hoja EMDN específica que describa ese uso."
    ),
    "impresora de brazaletes de identificacion hospitalaria": (
        "La impresión de brazaletes hospitalarios es una función administrativa "
        "y no corresponde a una categoría EMDN de dispositivos clínicos "
        "confirmada."
    ),
    "equipo cpap para apnea del sueno": (
        "Las coincidencias EMDN directas identifican mascarillas y circuitos "
        "CPAP, que son accesorios y no el equipo generador de presión. Se "
        "requiere confirmar el término específico del dispositivo principal."
    ),
    "paralelas para entrenamiento de marcha": (
        "El catálogo revisado no confirma un término EMDN específico para "
        "paralelas de rehabilitación. Revisar si corresponde a mobiliario "
        "terapéutico o a otro equipo de rehabilitación."
    ),
    "carro rojo para reanimacion cardiopulmonar": (
        "El carro rojo es un medio de almacenamiento y transporte cuyo contenido "
        "puede variar; no equivale por sí mismo a un desfibrilador ni a otro "
        "dispositivo de reanimación."
    ),
    "aspirador portatil para emergencias": (
        "El nombre no especifica si es un aspirador respiratorio de secreciones "
        "o un aspirador quirúrgico. Se necesita confirmar la indicación clínica "
        "antes de asignar una familia EMDN."
    ),
}


def exhaustive_similarities(name: str, entries: list[dict]) -> list[tuple[float, dict]]:
    normalized_name = normalize(name)
    matches = []
    for entry in entries:
        score = SequenceMatcher(
            None, normalized_name, entry["normalized_term"]
        ).ratio()
        if score > MIN_SIMILARITY:
            matches.append((score, entry))
    matches.sort(key=lambda result: result[0], reverse=True)
    return matches


def make_proposal(
    discrepancy: dict, catalog: dict[str, dict], entries: list[dict]
) -> dict:
    name = str(discrepancy.get("nombre_equipo") or "").strip()
    normalized_name = normalize(name)
    if not name:
        raise ValueError("Cada discrepancia debe incluir un nombre_equipo no vacío.")
    similar_terms = exhaustive_similarities(name, entries)
    recommendation = RECOMMENDATIONS.get(normalized_name)
    code = None
    description = None
    terminal = False
    requires_disambiguation = False
    action = "REVISAR MANUALMENTE"

    if recommendation:
        normalized_target = normalize(recommendation["term"])
        target_matches = [
            entry
            for entry in catalog.values()
            if entry["normalized_term"] == normalized_target
        ]
        codes = {entry["code"] for entry in target_matches}
        if len(codes) == 1:
            target_code = next(iter(codes))
            # A >25% text match is preferred when it confirms the curated
            # clinical target; unrelated fuzzy hits never override that target.
            prioritized = next(
                (
                    entry
                    for score, entry in similar_terms
                    if score > MIN_SIMILARITY and entry["code"] == target_code
                ),
                None,
            )
            code = prioritized["code"] if prioritized else target_code
            entry = catalog.get(code)
            if entry is not None:
                description = entry["term"]
                terminal = entry["terminal"]
                requires_disambiguation = recommendation.get(
                    "requires_disambiguation", False
                )
                action = "APROBAR"
                justification = recommendation["justification"]
                if requires_disambiguation and terminal:
                    code = None
                    description = None
                    terminal = False
                    action = "REVISAR MANUALMENTE"
                    justification = (
                        "El código común configurado aparece como terminal en "
                        "el catálogo; no es válido usarlo como nodo padre "
                        "ambiguo. Se requiere revisión manual."
                    )
            else:
                justification = (
                    "El código propuesto no aparece en el catálogo oficial."
                )
        else:
            justification = (
                "El término objetivo no tiene una correspondencia única en el "
                "Excel EMDN; se requiere revisión manual."
            )
    else:
        justification = MANUAL_REASONS.get(
            normalized_name,
            (
                "No se encontró una correspondencia clínica y técnica "
                "suficientemente sustentada. Se requiere revisión manual."
            ),
        )

    if action == "REVISAR MANUALMENTE" and recommendation:
        requires_disambiguation = recommendation.get(
            "requires_disambiguation", False
        )
    if code is not None and code not in catalog:
        code = None
        description = None
        terminal = False
        requires_disambiguation = False
        action = "REVISAR MANUALMENTE"
        justification = "El código propuesto no existe en el Excel EMDN."

    return {
        "nombre_equipo": name,
        "categoria_actual_sugerida": discrepancy.get("categoria_sugerida"),
        "emdn_propuesto": code,
        "descripcion_emdn": description,
        "es_terminal": terminal,
        "requiere_desambiguacion": requires_disambiguation,
        "justificacion": justification,
        "accion_recomendada": action,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analiza discrepancias y genera propuestas EMDN para revisión."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    discrepancies = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(discrepancies, list):
        raise ValueError("El archivo de discrepancias debe contener una lista JSON.")
    if any(not isinstance(discrepancy, dict) for discrepancy in discrepancies):
        raise ValueError("Cada elemento de discrepancias_masivo.json debe ser un objeto.")
    catalog, entries = load_catalog(args.excel)
    proposals = [
        make_proposal(discrepancy, catalog, entries)
        for discrepancy in discrepancies
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    approved = sum(
        proposal["accion_recomendada"] == "APROBAR" for proposal in proposals
    )
    print(
        f"Propuestas generadas: {len(proposals)} "
        f"({approved} con código; {len(proposals) - approved} para revisión manual). "
        f"Archivo: {args.output}"
    )


if __name__ == "__main__":
    main()

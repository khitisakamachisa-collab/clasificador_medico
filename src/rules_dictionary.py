from __future__ import annotations

from .config import Config
from .utils import CATEGORÍAS, CATEGORY_KEYWORDS


# Prefijos confirmados contra los códigos terminales del libro EMDN 2026.
EMDN_PREFIXES = {
    "ANE-01": "Z12030101",
    "CAR-01": "Z1205",
    "CAR-02": "J01",
    "CIR-01": "Z1201",
    "CIR-02": "Z120109",
    "DEN-01": "Z1211",
    "DIA-01": "Z1209",
    "END-01": "Z1202",
    "EST-01": "Z120113",
    "GAS-01": "Z120309",
    "IMG-01": "Z1103",
    "IMG-02": "Z110306",
    "IMG-03": "Z1104",
    "LAB-01": "W0201",
    "LAB-02": "Z1217",
    "MON-01": "Z120302",
    "NEO-01": "Z120804",
    "OFI-01": "V08",
    "RES-01": "Z120301",
    "TER-01": "Z1206",
    "URG-01": "Z120305",
    "INF-01": "Z120303",
    "FRM-01": "V08",
    "MOB-01": "V0806",
    "OTR-01": "Z12",
}

EMDN_SUBCATEGORY_PREFIXES = {
    "CIR-01": {"scialytic_fixed": "Z12010701", "scialytic_mobile": "Z12010702"},
    "EST-01": {"small_load_autoclave": "Z12011305", "large_autoclave": "Z12011304"},
    "IMG-01": {"radiography": "Z110305"},
    "IMG-02": {"ct": "Z110306", "mri": "Z1105", "pet": "Z110204"},
    "IMG-03": {"portable": "Z11040103", "cardiology": "Z11040102", "obstetric": "Z11040105"},
    "INF-01": {"infusion": "Z12030301", "syringe": "Z12030302", "enteral": "Z12030303"},
    "DIA-01": {"peritoneal": "Z12090101", "haemodialysis": "Z12090201"},
    "GAS-01": {"oxygen_concentrator": "Z12159004", "gas_pipeline": "Z120309"},
    "RES-01": {
        "hospital": "Z12030105",
        "non_hospital": "Z12030103",
        "portable": "Z12030104",
    },
    "MON-01": {"bedside": "Z1203020201", "portable": "Z1203020202"},
    "URG-01": {"manual": "Z12030502", "automatic": "Z12030503", "semi": "Z12030501"},
}

REGLAS_ADICIONALES = {
    "ANE-01": ["anesthesia", "anaesthesia", "vaporizer", "vaporizador"],
    "CAR-01": ["holter", "electrocardiograph", "electrocardiograma", "prueba de esfuerzo"],
    "CAR-02": ["implantable defibrillator", "desfibrilador implantable"],
    "CIR-01": ["operating table", "mesa quirúrgica", "lámpara cialítica", "lampara cialitica", "lampara quirurgica", "lámpara quirúrgica", "cialitica", "cialítica", "lampara movil", "lámpara móvil"],
    "CIR-02": ["electrosurgical", "diathermocoagulator", "electrobisturí"],
    "DEN-01": ["dental unit", "unidad dental", "odontológico"],
    "DIA-01": ["dialisis", "diálisis", "hemodialysis", "haemodialysis", "hemodialisis", "hemodiálisis", "maquina de dialisis", "máquina de diálisis", "equipo de dialisis", "equipo de diálisis", "dialisis peritoneal", "diálisis peritoneal", "nefrologia", "nefrología"],
    "END-01": ["gastroscope", "colonoscope", "bronchoscope", "gastroscopio", "colonoscopio"],
    "EST-01": ["autoclave", "autoclave de mesa", "autoclave pequeño", "autoclave pequeno", "autoclave grande", "autoclave odontologico", "autoclave dental", "small load autoclave", "sterilizer", "steriliser", "esterilizador"],
    "GAS-01": ["oxygen concentrator", "concentrador oxigeno", "concentrador oxígeno", "concentrador de oxigeno", "concentrador de oxígeno"],
    "IMG-01": ["x ray", "x-ray", "rayos x", "radiography", "fluoroscopy", "mammography", "angiograph"],
    "IMG-02": ["computed tomography", "ct scan", "ct", "tomógrafo", "tomografo", "tomografía", "tomografia", "tomografía computarizada", "tomografia computarizada", "mri", "rm", "magnet", "resonador", "resonador magnético", "resonador magnetico", "resonancia", "resonancia magnética", "resonancia magnetica", "magnetic resonance", "pet scanner", "pet ct"],
    "IMG-03": ["portable ultrasound scanner", "ultrasound scanner", "ultrasound", "ecógrafo", "ecografía", "ultrasonido"],
    "LAB-01": ["analyzer", "analyser", "centrifuge", "microscope", "analizador", "centrífuga", "microscopio"],
    "LAB-02": ["blood bank", "apheresis", "banco de sangre"],
    "MON-01": ["monitor de signos vitales", "vital signs monitor", "patient monitor", "monitor multiparámetro", "telemetry"],
    "NEO-01": ["neonatal incubator", "incubadora neonatal", "phototherapy", "fototerapia neonatal"],
    "OFI-01": ["office equipment", "printer", "computer", "equipo de oficina", "impresora"],
    "RES-01": ["ventilator", "respirator", "ventilador", "respirador", "cpap", "bipap", "pulmonary ventilation"],
    "TER-01": ["physiotherapy", "rehabilitation", "fisioterapia", "rehabilitación", "tens"],
    "URG-01": ["defibrillator", "desfibrilador", "aed", "cardiac compressor"],
    "INF-01": ["infusion pump", "syringe pump", "bomba de infusión", "bomba de jeringa"],
    "FRM-01": ["pharmacy refrigerator", "refrigerador de farmacia", "medication dispenser"],
    "MOB-01": ["hospital bed", "wheelchair", "stretcher", "cama hospitalaria", "silla de ruedas", "camilla"],
    "OTR-01": ["other medical equipment", "other medical devices", "medical equipment"],
}

REGLAS_CLASIFICACION = {
    keyword: {
        "categoria": category,
        "emdn_prefix": EMDN_PREFIXES[category],
        "mdr_class": CATEGORÍAS[category]["mdr_default"],
        "confidence": 0.96,
    }
    for category in CATEGORÍAS
    for keyword in dict.fromkeys(CATEGORY_KEYWORDS[category] + REGLAS_ADICIONALES[category])
}

# Reglas específicas con términos terminales confirmados en el catálogo EMDN.
REGLAS_CLASIFICACION.update(
    {
        "mesa de cirugias": {
            "categoria": "CIR-01",
            "emdn_code": "Z12011202",
            "emdn_prefix": EMDN_PREFIXES["CIR-01"],
            "mdr_class": "IIa",
            "confidence": 0.96,
        },
        "mesa de cirugia": {
            "categoria": "CIR-01",
            "emdn_code": "Z12011202",
            "emdn_prefix": EMDN_PREFIXES["CIR-01"],
            "mdr_class": "IIa",
            "confidence": 0.96,
        },
        "bisturi quirurgico reutilizable": {
            "categoria": "CIR-01",
            "emdn_code": "L010101",
            "emdn_prefix": "L0101",
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "bisturi": {
            "categoria": "CIR-01",
            "emdn_code": "L010101",
            "emdn_prefix": "L0101",
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama uci": {
            "categoria": "MOB-01",
            "emdn_code": "V08060102",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama electrica uci": {
            "categoria": "MOB-01",
            "emdn_code": "V08060102",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama de cuidados intensivos": {
            "categoria": "MOB-01",
            "emdn_code": "V08060102",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama para uci": {
            "categoria": "MOB-01",
            "emdn_code": "V08060102",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama hospitalaria": {
            "categoria": "MOB-01",
            "emdn_code": "V08060101",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.96,
        },
        "cama": {
            "categoria": "MOB-01",
            "emdn_code": "V08060101",
            "emdn_prefix": EMDN_PREFIXES["MOB-01"],
            "mdr_class": "I",
            "confidence": 0.90,
        },
        "monitor de signos vitales": {
            "categoria": "MON-01",
            "emdn_code": "Z1203020201",
            "emdn_prefix": EMDN_PREFIXES["MON-01"],
            "mdr_class": "IIa",
            "confidence": 0.96,
        },
    }
)


def agregar_regla(
    keyword: str,
    categoria: str,
    emdn_code: str | None = None,
    mdr_class: str | None = None,
    confidence: float = 0.90,
) -> None:
    """Agrega o reemplaza una regla de clasificación en memoria."""
    normalized_keyword = keyword.strip().lower()
    if not normalized_keyword:
        raise ValueError("La palabra clave no puede estar vacía.")
    if categoria not in CATEGORÍAS:
        raise ValueError(f"Categoría desconocida: {categoria}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("La confianza debe estar entre 0 y 1.")
    if mdr_class is not None and mdr_class not in {"I", "IIa", "IIb", "III"}:
        raise ValueError(f"Clase MDR desconocida: {mdr_class}")

    REGLAS_CLASIFICACION[normalized_keyword] = {
        "categoria": categoria,
        "emdn_code": emdn_code.strip() if emdn_code else None,
        "emdn_prefix": EMDN_PREFIXES[categoria],
        "mdr_class": mdr_class or CATEGORÍAS[categoria]["mdr_default"],
        "confidence": confidence,
    }


HOSPITAL_LOCATIONS = Config.HOSPITAL_LOCATIONS
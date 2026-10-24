from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", override=False)
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT_DIR / "data")))
RAW_DIR = Path(os.getenv("RAW_DIR", str(DATA_DIR / "raw")))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", str(DATA_DIR / "processed")))
MODELS_DIR = Path(os.getenv("MODELS_DIR", str(DATA_DIR / "models")))

CATEGORÍAS = {
    "ANE-01": {"nombre": "Anestesia", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "CAR-01": {"nombre": "Cardiología Diagnóstica", "mdr_default": "IIa", "defaults": {"impacto_clinico": 3, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 2}},
    "CAR-02": {"nombre": "Cardiología Terapéutica", "mdr_default": "III", "defaults": {"impacto_clinico": 5, "redundancia": 5, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 5}},
    "CIR-01": {"nombre": "Quirófano General", "mdr_default": "IIa", "defaults": {"impacto_clinico": 4, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 4}},
    "CIR-02": {"nombre": "Electrocirugía", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 3}},
    "DEN-01": {"nombre": "Odontología", "mdr_default": "IIa", "defaults": {"impacto_clinico": 2, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3}},
    "DIA-01": {"nombre": "Diálisis", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "END-01": {"nombre": "Endoscopía", "mdr_default": "IIa", "defaults": {"impacto_clinico": 4, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "EST-01": {"nombre": "Esterilización", "mdr_default": "IIa", "defaults": {"impacto_clinico": 2, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3}},
    "GAS-01": {"nombre": "Gases Medicinales", "mdr_default": "IIa", "defaults": {"impacto_clinico": 5, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 2}},
    "IMG-01": {"nombre": "Imagenología Rayos X", "mdr_default": "IIb", "defaults": {"impacto_clinico": 4, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "IMG-02": {"nombre": "Tomografía/Resonancia", "mdr_default": "IIb", "defaults": {"impacto_clinico": 4, "redundancia": 5, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 5}},
    "IMG-03": {"nombre": "Ultrasonido", "mdr_default": "IIa", "defaults": {"impacto_clinico": 3, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3}},
    "LAB-01": {"nombre": "Laboratorio Análisis", "mdr_default": "IIa", "defaults": {"impacto_clinico": 4, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "LAB-02": {"nombre": "Banco de Sangre", "mdr_default": "IIa", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 3}},
    "MON-01": {"nombre": "Monitoreo Vital", "mdr_default": "IIa", "defaults": {"impacto_clinico": 4, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3}},
    "NEO-01": {"nombre": "Neonatología", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "OFI-01": {"nombre": "Oficina/General", "mdr_default": "I", "defaults": {"impacto_clinico": 1, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 1}},
    "RES-01": {"nombre": "Respiratorio", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 4}},
    "TER-01": {"nombre": "Terapia Física", "mdr_default": "IIa", "defaults": {"impacto_clinico": 2, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 2}},
    "URG-01": {"nombre": "Emergencia", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 4, "frecuencia_uso": 4, "historial_fallas": 2, "costo_tiempo": 4}},
    "INF-01": {"nombre": "Infusión", "mdr_default": "IIb", "defaults": {"impacto_clinico": 5, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 3}},
    "FRM-01": {"nombre": "Farmacia", "mdr_default": "I", "defaults": {"impacto_clinico": 3, "redundancia": 3, "frecuencia_uso": 5, "historial_fallas": 2, "costo_tiempo": 2}},
    "MOB-01": {"nombre": "Mobiliario Clínico", "mdr_default": "I", "defaults": {"impacto_clinico": 2, "redundancia": 2, "frecuencia_uso": 5, "historial_fallas": 3, "costo_tiempo": 2}},
    "OTR-01": {"nombre": "Otros Equipos", "mdr_default": "I", "defaults": {"impacto_clinico": 2, "redundancia": 2, "frecuencia_uso": 4, "historial_fallas": 3, "costo_tiempo": 2}},
}

# Palabras clave bilingües para clasificar equipos y consultar términos oficiales EMDN.
CATEGORY_KEYWORDS = {
    "ANE-01": ["anesthesia machine", "anaesthesia machine", "máquina de anestesia", "anestesia"],
    "CAR-01": ["electrocardiograph", "electrocardiogram", "electrocardiógrafo", "electrocardiograma", "ecg"],
    "CAR-02": ["pacemaker", "cardiac ablation", "marcapasos", "ablación cardíaca"],
    "CIR-01": ["operating table", "surgical table", "mesa quirúrgica", "quirófano"],
    "CIR-02": ["electrosurgical unit", "electrocautery", "electrocirugía", "electrobisturí"],
    "DEN-01": ["dental unit", "dental chair", "unidad dental", "odontológico", "odontología"],
    "DIA-01": ["dialysis machine", "hemodialysis", "máquina de diálisis", "hemodiálisis"],
    "END-01": ["endoscope", "endoscopy", "endoscopio", "endoscopía"],
    "EST-01": ["sterilizer", "autoclave", "esterilizador", "esterilización"],
    "GAS-01": ["medical gas", "oxygen concentrator", "gases medicinales", "concentrador de oxígeno"],
    "IMG-01": ["x ray", "x-ray", "radiography", "rayos x", "radiografía"],
    "IMG-02": ["ct scanner", "computed tomography", "mri scanner", "magnetic resonance", "tomógrafo", "resonancia magnética"],
    "IMG-03": ["portable ultrasound scanner", "ultrasound scanner", "ultrasound", "ecógrafo portátil", "ecógrafo", "ultrasonido"],
    "LAB-01": ["laboratory analyzer", "clinical analyzer", "blood gas analyzer", "analizador de laboratorio", "analizador clínico"],
    "LAB-02": ["blood bank", "blood component", "banco de sangre", "hemocomponentes"],
    "MON-01": ["patient monitor", "multiparameter monitor", "vital signs monitor", "monitor de paciente", "monitor multiparámetro"],
    "NEO-01": ["neonatal incubator", "infant incubator", "incubadora neonatal", "incubadora de recién nacidos"],
    "OFI-01": ["office equipment", "administrative equipment", "equipo de oficina", "equipo administrativo"],
    "RES-01": ["pulmonary ventilator", "ventilator", "respirator", "ventilador", "respirador", "respiratorio"],
    "TER-01": ["physiotherapy", "physical therapy", "rehabilitation equipment", "fisioterapia", "terapia física", "rehabilitación"],
    "URG-01": ["defibrillator", "automated external defibrillator", "aed", "desfibrilador", "carro de paro"],
    "INF-01": ["infusion pump", "syringe pump", "bomba de infusión", "bomba de jeringa"],
    "FRM-01": ["pharmacy refrigerator", "medication dispensing", "refrigerador de farmacia", "dispensador de medicamentos"],
    "MOB-01": ["hospital bed", "clinical bed", "wheelchair", "cama hospitalaria", "silla de ruedas", "camilla"],
    "OTR-01": ["other medical equipment", "other medical devices", "medical equipment"],
}


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: str | Path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str | Path, payload):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

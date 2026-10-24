import pytest

from src import classifier
from src import code_generator
from src.classifier import clasificar_equipo, classify_equipment
from src.criticality import ajustar_por_mdr, calcular_criticidad
from src.rules_dictionary import EMDN_PREFIXES, EMDN_SUBCATEGORY_PREFIXES, agregar_regla
from src.utils import CATEGORÍAS, CATEGORY_KEYWORDS


@pytest.fixture(autouse=True)
def isolate_internal_code_sequences(monkeypatch, tmp_path):
    monkeypatch.setattr(code_generator, "_SEQUENCE_PATH", tmp_path / "sequences.json")


def test_classify_equipment_returns_expected_keys():
    result = clasificar_equipo("Ecógrafo portátil Samsung WS80A", "Samsung", "Imagenología")
    assert "categoria" in result
    assert result["categoria_propia"] == "IMG-03"
    assert result["metodo"] == "REGLAS"
    assert result["emdn_code"] == "Z11040103"
    assert result["emdn_term"] == "PORTABLE ULTRASOUND SCANNERS"
    assert result["emdn_verified"] is True
    assert result["confidence"] >= 0.90
    assert result["codigo_interno"].startswith("IMG03-")
    assert "mdr_class" in result
    assert "criticidad" in result
    assert result["criticidad"]["indice"] >= 0


def test_classify_equipment_keeps_english_api_alias():
    result = classify_equipment("Ventilador respiratorio")
    assert result["categoria_propia"] == "RES-01"
    assert result["metodo"] == "REGLAS"


def test_internal_code_is_unique_and_sequential():
    first = clasificar_equipo("ecógrafo portátil")
    second = clasificar_equipo("ecógrafo portátil")
    assert first["codigo_interno"] == "IMG03-001"
    assert second["codigo_interno"] == "IMG03-002"


def test_keyword_map_covers_all_internal_categories():
    assert set(CATEGORY_KEYWORDS) == set(CATEGORÍAS)
    assert all(CATEGORY_KEYWORDS.values())


def test_classification_without_excel_marks_emdn_pending(monkeypatch):
    monkeypatch.setattr(classifier, "load_emdn_database", lambda: {"flat": {}})
    result = clasificar_equipo("Ecógrafo portátil")
    assert result["categoria_propia"] == "IMG-03"
    assert result["emdn_code"] == "PENDIENTE_DE_VALIDACION"
    assert result["emdn_verified"] is False


def test_unmatched_name_uses_nlp_category(monkeypatch):
    class FakeClassifier:
        def predict(self, _features):
            return ["RES-01"]

        def predict_proba(self, _features):
            return [[0.82]]

    class FakeVectorizer:
        def transform(self, _texts):
            return [[1]]

    monkeypatch.setattr(classifier, "_category_from_rules", lambda _name: None)
    monkeypatch.setattr(
        classifier, "load_model_assets", lambda: (FakeClassifier(), FakeVectorizer())
    )
    result = classifier.classify_equipment("dispositivo clínico sin regla")
    assert result["categoria_propia"] == "RES-01"
    assert result["metodo"] == "NLP"
    assert result["confidence"] == 0.82


def test_nlp_failure_returns_manual_review_result(monkeypatch):
    monkeypatch.setattr(classifier, "_category_from_rules", lambda _name: None)
    monkeypatch.setattr(
        classifier,
        "load_model_assets",
        lambda: (_ for _ in ()).throw(OSError("artefactos ausentes")),
    )

    result = classify_equipment("dispositivo experimental")

    assert result["categoria_propia"] == "OTR-01"
    assert result["metodo"] == "MANUAL"
    assert result["confidence"] == 0.0
    assert "revisión manual" in result["advertencia"]


def test_dynamic_rule_is_applied():
    agregar_regla(
        "equipo de prueba dinámico",
        "IMG-03",
        emdn_code="Z11040105",
        mdr_class="IIb",
        confidence=0.91,
    )
    result = classify_equipment("Equipo de prueba dinámico modelo ABC")
    assert result["categoria_propia"] == "IMG-03"
    assert result["confidence"] == 0.91
    assert result["emdn_code"] == "Z11040105"
    assert result["mdr_class"] == "IIb"


def test_dynamic_rule_rejects_unknown_category():
    with pytest.raises(ValueError, match="Categoría desconocida"):
        agregar_regla("equipo inválido", "UNKNOWN")


def test_dynamic_rule_rejects_unknown_mdr_class():
    with pytest.raises(ValueError, match="Clase MDR desconocida"):
        agregar_regla("equipo inválido mdr", "IMG-03", mdr_class="IV")


@pytest.mark.parametrize(
    ("nombre", "marca", "ubicacion", "categoria", "emdn_code"),
    [
        ("resonador siemens imagenologia", "Siemens", "Imagenología", "IMG-02", "Z11050104"),
        ("Resonador magnético (RM) Siemens Healthineers Imagenología", "Siemens Healthineers", "Imagenología", "IMG-02", "Z11050104"),
        ("Ventilador mecánico Hamilton Medical Quirófano", "Hamilton Medical", "Quirófano", "RES-01", "Z1203010502"),
        ("tomografo siemens imagenologia", "Siemens", "Imagenología", "IMG-02", "Z11030601"),
        ("respirador drager uci", "Dräger", "UCI", "RES-01", "Z1203010502"),
        ("Equipo de diálisis Baxter, Nefrología", "Baxter", "Nefrología", "DIA-01", "Z12090201"),
        ("Concentrador de oxígeno Inogen, Neumología", "Inogen", "Neumología", "GAS-01", "Z12159004"),
        ("Lampara cialitica Maquet Quirófano", "Maquet", "Quirófano", "CIR-01", "Z12010701"),
        ("Autoclave de mesa Tuttnauer Central esterilización", "Tuttnauer", "Central esterilización", "EST-01", "Z12011305"),
        ("Autoclave grande Getinge Central esterilización", "Getinge", "Central esterilización", "EST-01", "Z12011304"),
        ("Autoclave odontologico Woson Odontología", "Woson", "Odontología", "EST-01", "Z12011305"),
        ("Lampara movil Maquet Quirófano", "Maquet", "Quirófano", "CIR-01", "Z12010702"),
        ("ecógrafo samsung imagenología", "Samsung", "Imagenología", "IMG-03", "Z11040103"),
        ("ecógrafo siemens imagenología", "Siemens", "Imagenología", "IMG-03", "Z11040103"),
        ("respirador dräger uci", "Dräger", "UCI", "RES-01", "Z1203010502"),
        ("respirador portátil hamilton", "Hamilton", "Domicilio", "RES-01", "Z12030104"),
        ("rayos x siemens imagenología", "Siemens", "Imagenología", "IMG-01", "Z11030506"),
        ("tomógrafo siemens imagenología", "Siemens", "Imagenología", "IMG-02", "Z11030601"),
        ("monitor de signos vitales philips uci", "Philips", "UCI", "MON-01", "Z1203020201"),
        ("bomba de infusión braun", "Braun", "Infusión", "INF-01", "Z12030301"),
        ("desfibrilador zoll", "Zoll", "Urgencias", "URG-01", "Z12030502"),
        ("máquina de anestesia dräger", "Dräger", "Quirófano", "ANE-01", "Z1203010101"),
        ("Peritoneal dialysis machine Baxter", "Baxter", "Nephrology", "DIA-01", "Z12090101"),
        ("Syringe pump Braun", "Braun", "ICU", "INF-01", "Z12030302"),
        ("Obstetric ultrasound GE", "GE", "Obstetrics", "IMG-03", "Z11040105"),
        ("Automatic defibrillator Zoll", "Zoll", "Emergency", "URG-01", "Z12030503"),
    ],
)
def test_required_equipment_examples_use_category_prefix_and_official_terminal(
    nombre, marca, ubicacion, categoria, emdn_code
):
    result = clasificar_equipo(nombre, marca, ubicacion)

    assert result["categoria_propia"] == categoria
    assert result["metodo"] == "REGLAS"
    assert result["emdn_code"] == emdn_code
    assert result["emdn_verified"] is True
    assert result["confidence"] >= 0.90
    assert result["codigo_interno"].startswith(categoria.replace("-", "") + "-")
    valid_prefixes = [EMDN_PREFIXES[categoria], *EMDN_SUBCATEGORY_PREFIXES.get(categoria, {}).values()]
    assert any(result["emdn_code"].startswith(prefix) for prefix in valid_prefixes)
    assert all(
        any(candidate["emdn_code"].startswith(prefix) for prefix in valid_prefixes)
        for candidate in result["emdn_candidates"]
    )
    category_data = CATEGORÍAS[categoria]
    defaults = ajustar_por_mdr(category_data["defaults"], category_data["mdr_default"])
    expected_criticality = calcular_criticidad(
        defaults["impacto_clinico"],
        defaults["redundancia"],
        defaults["frecuencia_uso"],
        defaults["historial_fallas"],
        defaults["costo_tiempo"],
    )
    assert result["criticidad"]["indice"] == expected_criticality["indice"]

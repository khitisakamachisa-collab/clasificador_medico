import pytest

from src import classifier
from src import code_generator
from src import correction_validation
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
    assert result["semaforo"]["color"] == "verde"
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
    assert result["semaforo"]["color"] == "amarillo"


def test_tens_for_physiotherapy_has_high_confidence_green_light():
    result = classify_equipment(
        "TENS para fisioterapia Enraf Nonius Fisioterapia",
        "Enraf Nonius",
        "Fisioterapia",
    )
    assert result["categoria_propia"] == "TER-01"
    assert result["confidence"] == 0.96
    assert result["emdn_code"] == "Z120616"
    assert result["semaforo"]["color"] == "verde"
    assert result["semaforo"]["requiere_revision"] is False


def test_master_rules_match_exploration_lamp_before_nlp():
    result = classify_equipment("Lámpara exploración móvil")

    assert result["categoria_propia"] == "CIR-01"
    assert result["emdn_code"] == "Z129004"
    assert result["mdr_class"] == "I"
    assert result["metodo"] == "REGLAS"
    assert result["confidence"] == 0.96
    assert result["semaforo"]["color"] == "verde"


@pytest.mark.parametrize(
    ("name", "category", "emdn_code", "mdr_class"),
    [
        ("Monitor secuencial", "MON-01", "Z1203020201", "IIa"),
        ("Bisturí armónico", "CIR-02", "K0202010201", "IIb"),
        ("Bisturí armónico (Harmonic)", "CIR-02", "K0202010201", "IIb"),
        ("Harmonic scalpel", "CIR-02", "K0202010201", "IIb"),
        ("Cama UCI", "MOB-01", "V08060102", "I"),
        ("Equipo de resucitación", "MOB-01", "V08060102", "I"),
    ],
)
def test_master_rules_override_legacy_classification(name, category, emdn_code, mdr_class):
    result = classify_equipment(name)

    assert result["categoria_propia"] == category
    assert result["emdn_code"] == emdn_code
    assert result["mdr_class"] == mdr_class
    assert result["metodo"] == "REGLAS"
    assert result["semaforo"]["color"] == "verde"
    assert result["emdn_verified"] is True
    assert result["emdn_code"] != "Z12030202"


def test_typo_context_preserves_fisioterapia_rule():
    result = classify_equipment(
        "ENS para fisioterapia Enraf Nonius Fisioterapia",
        "Enraf Nonius",
        "Fisioterapia",
    )
    assert result["categoria_propia"] == "TER-01"
    assert result["confidence"] == 0.96
    assert result["semaforo"]["color"] == "verde"


def test_low_confidence_nlp_result_can_be_corrected_to_green(monkeypatch):
    class LowConfidenceClassifier:
        classes_ = ["ANE-01"]

        def predict(self, _features):
            return ["ANE-01"]

        def predict_proba(self, _features):
            return [[0.20]]

    class HighConfidenceCorrectionClassifier:
        classes_ = ["ANE-01", "TER-01", "IMG-01"]

        def predict(self, _features):
            return ["ANE-01"]

        def predict_proba(self, _features):
            return [[0.02, 0.95, 0.03]]

    class FakeVectorizer:
        def transform(self, _texts):
            return [[1]]

    monkeypatch.setattr(classifier, "_category_from_rules", lambda _name: None)
    monkeypatch.setattr(
        classifier,
        "load_model_assets",
        lambda: (LowConfidenceClassifier(), FakeVectorizer()),
    )
    original = classify_equipment("TENS para fisioterapia")
    monkeypatch.setattr(
        classifier,
        "load_model_assets",
        lambda: (HighConfidenceCorrectionClassifier(), FakeVectorizer()),
    )
    corrected = classify_equipment(
        "TENS para fisioterapia",
        categoria_forzada="TER-01",
    )
    assert original["categoria_propia"] == "ANE-01"
    assert original["confidence"] == 0.2
    assert original["semaforo"]["color"] == "rojo"
    assert corrected["categoria_propia"] == "TER-01"
    assert corrected["confidence"] == 0.95
    assert corrected["metodo"] == "CORRECCION_MANUAL"
    assert corrected["semaforo"]["color"] == "verde"


def test_forced_category_uses_expert_confidence_without_nlp(monkeypatch):
    def unexpected_model_load():
        raise AssertionError("Una categoría validada manualmente no debe consultar el modelo NLP")

    monkeypatch.setattr(classifier, "_category_from_rules", lambda _name: None)
    monkeypatch.setattr(classifier, "load_model_assets", unexpected_model_load)
    result = classify_equipment(
        "Ecógrafo portátil",
        categoria_forzada="IMG-03",
    )
    assert result["categoria_propia"] == "IMG-03"
    assert result["confidence"] == 0.95
    assert result["metodo"] == "CORRECCION_MANUAL"
    assert result["semaforo"]["color"] == "verde"
    assert result["validacion_correccion"]["estado"] == "VALIDADA_AUTOMATICAMENTE"


def test_correction_validation_passes_all_three_checks():
    result = classify_equipment("Electroestimulador", categoria_forzada="TER-01")

    assert result["confidence"] == 0.95
    assert result["validacion_correccion"] == {
        "confidence": 0.95,
        "estado": "VALIDADA_AUTOMATICAMENTE",
        "validaciones": {
            "emdn_valido": True,
            "mdr_coherente": True,
            "criticidad_razonable": True,
            "semantica_valida": True,
        },
        "mensaje": (
            "✅ Corrección validada automáticamente. EMDN, MDR, criticidad y "
            "coherencia semántica verificadas."
        ),
    }


def test_correction_validation_functions_check_emdn_and_criticality_details():
    result = classify_equipment("Electroestimulador", categoria_forzada="TER-01")

    assert correction_validation.verificar_emdn_en_excel("TER-01", "Z120616")
    assert not correction_validation.verificar_emdn_en_excel("IMG-03", "Z120616")
    assert correction_validation.verificar_criticidad_categoria("TER-01", result["criticidad"])

    inconsistent = {**result["criticidad"], "indice": 1.0}
    assert not correction_validation.verificar_criticidad_categoria("TER-01", inconsistent)


def test_correction_validation_requires_review_when_two_checks_pass():
    result = classify_equipment("Electroestimulador", categoria_forzada="TER-01")
    result["mdr_class"] = "III"

    validation = correction_validation.validar_correccion_automaticamente(
        result, nombre_equipo="Electroestimulador"
    )

    assert validation["confidence"] == 0.75
    assert validation["estado"] == "PENDIENTE_REVISION"
    assert validation["validaciones"] == {
        "emdn_valido": True,
        "mdr_coherente": False,
        "criticidad_razonable": True,
        "semantica_valida": True,
    }


def test_correction_validation_rejects_when_fewer_than_two_checks_pass():
    result = classify_equipment("Electroestimulador", categoria_forzada="TER-01")
    result["emdn_code"] = "CODIGO-INEXISTENTE"
    result["mdr_class"] = "III"

    validation = correction_validation.validar_correccion_automaticamente(
        result, nombre_equipo="Electroestimulador"
    )

    assert validation["confidence"] == 0.30
    assert validation["estado"] == "RECHAZADA"
    assert validation["validaciones"] == {
        "emdn_valido": False,
        "mdr_coherente": False,
        "criticidad_razonable": True,
        "semantica_valida": True,
    }


def test_semantic_check_rejects_unrelated_emdn_term_even_if_structure_matches():
    result = classify_equipment("Cama UCI", categoria_forzada="MOB-01")
    result["emdn_code"] = "V08060102"
    assert correction_validation.verificar_emdn_en_excel("MOB-01", result["emdn_code"])
    result["emdn_code"] = "Z12062892"

    validation = correction_validation.validar_correccion_automaticamente(
        result, nombre_equipo="Cama UCI"
    )

    assert validation["confidence"] == 0.0
    assert validation["estado"] == "RECHAZADA"
    assert validation["validaciones"]["semantica_valida"] is False


@pytest.mark.parametrize(
    ("name", "category", "emdn_code"),
    [
        ("Mesa de cirugias", "CIR-01", "Z12011202"),
        ("Bisturi quirurgico reutilizable", "CIR-01", "L010101"),
        ("Cama electrica UCI", "MOB-01", "V08060102"),
        ("Monitor de signos vitales", "MON-01", "Z1203020201"),
    ],
)
def test_targeted_device_rules_use_verified_emdn_term(name, category, emdn_code):
    result = classify_equipment(name)

    assert result["categoria_propia"] == category
    assert result["emdn_code"] == emdn_code
    assert result["emdn_verified"] is True


@pytest.mark.parametrize(
    ("name", "category", "emdn_code"),
    [
        ("Mesa de cirugia", "CIR-01", "Z12011202"),
        ("Bisturi quirurgico reutilizable", "CIR-01", "L010101"),
        ("Cama electrica UCI", "MOB-01", "V08060102"),
    ],
)
def test_manual_correction_reuses_matching_emdn_rule_without_nlp(
    name, category, emdn_code
):
    result = classify_equipment(name, categoria_forzada=category)

    assert result["metodo"] == "CORRECCION_MANUAL"
    assert result["categoria_propia"] == category
    assert result["emdn_code"] == emdn_code
    assert result["confidence"] == 0.95
    assert result["semaforo"]["color"] == "verde"


def test_mdr_validation_accepts_classes_within_one_level():
    assert correction_validation.verificar_mdr_categoria("TER-01", "I")
    assert correction_validation.verificar_mdr_categoria("TER-01", "IIb")
    assert not correction_validation.verificar_mdr_categoria("TER-01", "III")
    assert not correction_validation.verificar_mdr_categoria("INVALIDA", "IIa")


def test_unknown_equipment_with_low_nlp_confidence_requires_red_review(monkeypatch):
    class FakeClassifier:
        def predict(self, _features):
            return ["OTR-01"]

        def predict_proba(self, _features):
            return [[0.65]]

    class FakeVectorizer:
        def transform(self, _texts):
            return [[1]]

    monkeypatch.setattr(classifier, "_category_from_rules", lambda _name: None)
    monkeypatch.setattr(
        classifier, "load_model_assets", lambda: (FakeClassifier(), FakeVectorizer())
    )
    result = classify_equipment("Equipo raro desconocido")
    assert result["metodo"] == "NLP"
    assert result["confidence"] < 0.70
    assert result["semaforo"]["color"] == "rojo"


@pytest.mark.parametrize(
    ("confidence", "color", "hex_color", "level", "message", "icon", "revision"),
    [
        (0.90, "verde", "#10B981", "ALTA", "Clasificación de alta confianza", "✅", False),
        (0.70, "amarillo", "#F59E0B", "MEDIA", "Confianza media. Verificar si es correcto.", "⚠️", True),
        (0.69, "rojo", "#EF4444", "BAJA", "Baja confianza. Requiere revisión manual.", "❌", True),
    ],
)
def test_semaforo_confidence_thresholds(
    confidence, color, hex_color, level, message, icon, revision
):
    result = classifier.obtener_semaforo(confidence)
    assert result["color"] == color
    assert result["hex"] == hex_color
    assert result["nivel"] == level
    assert result["mensaje"] == message
    assert result["icono"] == icon
    assert result["requiere_revision"] is revision


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

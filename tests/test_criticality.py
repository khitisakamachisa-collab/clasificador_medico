import pytest

from src.criticality import (
    ajustar_por_mdr,
    calcular_criticidad,
    cargar_criticidad_defaults,
    obtener_valores_por_defecto,
)
from src.utils import CATEGORÍAS


def test_criticality_weighted_formula_and_high_level():
    result = calcular_criticidad(5, 4, 5, 3, 4)
    assert result["indice"] == 4.4
    assert result["nivel"] == "ALTA"


def test_criticality_levels():
    assert calcular_criticidad(3, 3, 3, 3, 3)["nivel"] == "MEDIA"
    assert calcular_criticidad(1, 1, 1, 1, 1)["nivel"] == "BAJA"


def test_criticality_factors_must_be_in_range():
    with pytest.raises(ValueError, match="entre 1 y 5"):
        calcular_criticidad(0, 2, 3, 4, 5)


@pytest.mark.parametrize(
    ("mdr_class", "expected_impact"),
    [("III", 5), ("IIb", 4), ("IIa", 3), ("I", 2)],
)
def test_mdr_adjustment(mdr_class, expected_impact):
    adjusted = ajustar_por_mdr(
        {
            "impacto_clinico": 2,
            "redundancia": 2,
            "frecuencia_uso": 2,
            "historial_fallas": 2,
            "costo_tiempo": 2,
        },
        mdr_class,
    )
    assert adjusted["impacto_clinico"] == expected_impact


def test_default_criticality_values_are_copied():
    category = next(iter(CATEGORÍAS))
    first = obtener_valores_por_defecto(category)
    first["impacto_clinico"] = 1
    assert CATEGORÍAS[category]["defaults"]["impacto_clinico"] != 1


def test_criticality_weights_configuration_requires_one_total():
    from src.config import _load_criticality_weights

    assert sum(_load_criticality_weights().values()) == pytest.approx(1.0)


def test_criticality_weights_reject_invalid_total(monkeypatch):
    monkeypatch.setenv(
        "CRITICALITY_WEIGHTS_JSON",
        '{"impacto_clinico":0.15,"redundancia":0.15,"frecuencia_uso":0.15,'
        '"historial_fallas":0.15,"costo_tiempo":0.15}',
    )
    from src.config import _load_criticality_weights

    with pytest.raises(ValueError, match="sumar 1"):
        _load_criticality_weights()


def test_criticality_weight_tolerance_is_one_thousandth(monkeypatch):
    from src.config import _load_criticality_weights

    monkeypatch.setenv(
        "CRITICALITY_WEIGHTS_JSON",
        '{"impacto_clinico":0.4009,"redundancia":0.20,"frecuencia_uso":0.15,'
        '"historial_fallas":0.15,"costo_tiempo":0.10}',
    )
    assert sum(_load_criticality_weights().values()) == pytest.approx(1.0009)
    monkeypatch.setenv(
        "CRITICALITY_WEIGHTS_JSON",
        '{"impacto_clinico":0.4011,"redundancia":0.20,"frecuencia_uso":0.15,'
        '"historial_fallas":0.15,"costo_tiempo":0.10}',
    )
    with pytest.raises(ValueError, match="tolerancia 0.001"):
        _load_criticality_weights()


@pytest.mark.parametrize(
    ("values", "index", "level"),
    [
        ((5, 4, 5, 3, 4), 4.40, "ALTA"),
        ((5, 3, 5, 3, 3), 4.10, "ALTA"),
        ((4, 3, 5, 2, 4), 3.65, "MEDIA"),
        ((3, 2, 5, 3, 3), 3.10, "MEDIA"),
        ((1, 2, 5, 2, 1), 1.95, "BAJA"),
        ((1, 1, 1, 1, 1), 1.00, "BAJA"),
        ((5, 5, 5, 5, 5), 5.00, "ALTA"),
    ],
)
def test_required_criticality_profiles(values, index, level):
    result = calcular_criticidad(*values)
    assert result["indice"] == index
    assert result["nivel"] == level


def test_external_defaults_cover_and_validate_all_categories():
    defaults = cargar_criticidad_defaults()
    assert len(defaults) == 25
    assert defaults["RES-01"]["indice"] == 4.40
    assert defaults["INF-01"]["indice"] == 4.10
    assert defaults["CIR-01"]["indice"] == 3.65
    assert defaults["IMG-03"]["indice"] == 3.10
    assert defaults["OFI-01"]["indice"] == 1.95


def test_context_modifiers_are_only_applied_when_equipment_is_created(
    monkeypatch, tmp_path
):
    from src.config import Config
    from src.criticality_store import asegurar_equipo, listar_ajustes

    monkeypatch.setattr(Config, "CORRECTIONS_DB_PATH", tmp_path / "criticidad.sqlite")
    first = asegurar_equipo("EQ-1", "OTR-01", "Equipo backup", "UCI")
    assert first["frecuencia_uso"] == 5
    assert first["impacto_clinico"] == 1
    audit = listar_ajustes(equipment_id="EQ-1")
    assert audit[0]["origen"] == "DEFAULT"
    assert "ubicación crítica" in audit[0]["justificacion"]
    assert "respaldo/reserva" in audit[0]["justificacion"]

    repeated = asegurar_equipo("EQ-1", "OTR-01", "Equipo común", "Oficina")
    assert repeated["frecuencia_uso"] == first["frecuencia_uso"]
    assert repeated["impacto_clinico"] == first["impacto_clinico"]
    assert len(listar_ajustes(equipment_id="EQ-1")) == 1


@pytest.mark.parametrize(
    ("mtbf_days", "expected_failures"),
    [
        (0, 5),
        (30, 5),
        (31, 4),
        (90, 4),
        (91, 3),
        (180, 3),
        (181, 2),
        (365, 2),
        (366, 1),
    ],
)
def test_mtbf_mapping_boundaries(monkeypatch, tmp_path, mtbf_days, expected_failures):
    from src.config import Config
    from src.criticality_store import asegurar_equipo, recalcular_por_mtbf

    monkeypatch.setattr(Config, "CORRECTIONS_DB_PATH", tmp_path / "mtbf.sqlite")
    asegurar_equipo("EQ-MTBF", "RES-01")
    result = recalcular_por_mtbf("EQ-MTBF", mtbf_days)
    assert result["criticidad"]["historial_fallas"] == expected_failures
    assert result["criticidad"]["origen_historial"] == "MTBF_REAL"

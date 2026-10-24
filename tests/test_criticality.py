import pytest

from src.criticality import (
    ajustar_por_mdr,
    calcular_criticidad,
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

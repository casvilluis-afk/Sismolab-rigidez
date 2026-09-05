"""Núcleo de cálculo para la rigidez lateral de columnas de concreto armado.

El módulo no depende del navegador. Puede reutilizarse más adelante en análisis
matricial, una API o aplicaciones de escritorio sin cambiar las ecuaciones base.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, pi, sqrt
from typing import Literal


UnitSystem = Literal["SI", "MKS"]
SectionShape = Literal["square", "circle"]
JointType = Literal["fixed", "pinned"]

MPA_TO_KGF_CM2 = 10.1971621298


@dataclass(slots=True)
class ColumnGroup:
    id: str
    quantity: int
    shape: SectionShape
    dimension: float
    fc: float
    base: JointType
    top: JointType


@dataclass(slots=True)
class GroupCalculation:
    factor: float
    elastic_modulus: float
    inertia: float
    stiffness_per_column: float
    contribution: float
    stiffness_unit: str
    modulus_unit: str
    inertia_unit: str
    length_unit: str
    height_in_length_unit: float

    def to_dict(self) -> dict[str, float | str]:
        return asdict(self)


def _positive_number(value: float, field_name: str) -> float:
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{field_name} debe ser mayor que cero.")
    return number


def validate_group(group: ColumnGroup) -> None:
    if not 1 <= int(group.quantity) <= 100:
        raise ValueError("La cantidad debe estar entre 1 y 100.")
    if group.shape not in ("square", "circle"):
        raise ValueError("La sección debe ser cuadrada o circular.")
    if group.base not in ("fixed", "pinned") or group.top not in ("fixed", "pinned"):
        raise ValueError("La condición de apoyo no es válida.")
    _positive_number(group.dimension, "La dimensión")
    _positive_number(group.fc, "f′c")


def boundary_factor(base: JointType, top: JointType) -> float:
    """Factor c de k = cEI/h³ para las condiciones idealizadas."""
    if base == "pinned" and top == "pinned":
        return 0.0
    if base == "fixed" and top == "fixed":
        return 12.0
    return 3.0


def boundary_description(base: JointType, top: JointType) -> str:
    if base == "fixed" and top == "fixed":
        return "Doble curvatura · giros impedidos"
    if base == "pinned" and top == "pinned":
        return "Biela · sin rigidez lateral por flexión"
    return "Curvatura simple · un giro liberado"


def section_inertia(shape: SectionShape, dimension: float) -> float:
    dimension = _positive_number(dimension, "La dimensión")
    if shape == "square":
        return dimension**4 / 12.0
    if shape == "circle":
        return pi * dimension**4 / 64.0
    raise ValueError("La sección debe ser cuadrada o circular.")


def elastic_modulus(fc: float, units: UnitSystem) -> float:
    fc = _positive_number(fc, "f′c")
    if units == "SI":
        return 4_700.0 * sqrt(fc)
    if units == "MKS":
        return 15_000.0 * sqrt(fc)
    raise ValueError("El sistema de unidades debe ser SI o MKS.")


def calculate_group(
    group: ColumnGroup,
    story_height_m: float,
    units: UnitSystem,
) -> GroupCalculation:
    validate_group(group)
    story_height_m = _positive_number(story_height_m, "La altura de entrepiso")
    if units not in ("SI", "MKS"):
        raise ValueError("El sistema de unidades debe ser SI o MKS.")

    factor = boundary_factor(group.base, group.top)
    modulus = elastic_modulus(group.fc, units)
    inertia = section_inertia(group.shape, group.dimension)
    height = story_height_m * (1_000.0 if units == "SI" else 100.0)
    raw_stiffness = factor * modulus * inertia / height**3

    # En SI, N/mm equivale numéricamente a kN/m. En MKS, kgf/cm
    # se convierte a tonf/m multiplicando por 0.1.
    stiffness = raw_stiffness if units == "SI" else raw_stiffness * 0.1
    quantity = int(group.quantity)

    return GroupCalculation(
        factor=factor,
        elastic_modulus=modulus,
        inertia=inertia,
        stiffness_per_column=stiffness,
        contribution=stiffness * quantity,
        stiffness_unit="kN/m" if units == "SI" else "tonf/m",
        modulus_unit="MPa" if units == "SI" else "kgf/cm²",
        inertia_unit="mm⁴" if units == "SI" else "cm⁴",
        length_unit="mm" if units == "SI" else "cm",
        height_in_length_unit=height,
    )


def calculate_story(
    groups: list[ColumnGroup],
    story_height_m: float,
    units: UnitSystem,
) -> dict[str, object]:
    if not 1 <= len(groups) <= 8:
        raise ValueError("Debe existir entre 1 y 8 grupos de columnas.")
    results = [calculate_group(group, story_height_m, units) for group in groups]
    return {
        "total": sum(result.contribution for result in results),
        "unit": "kN/m" if units == "SI" else "tonf/m",
        "groups": [result.to_dict() for result in results],
    }


def convert_group_units(group: ColumnGroup, source: UnitSystem, target: UnitSystem) -> ColumnGroup:
    validate_group(group)
    if source == target:
        return ColumnGroup(**asdict(group))
    if source == "SI" and target == "MKS":
        dimension = group.dimension / 10.0
        fc = group.fc * MPA_TO_KGF_CM2
    elif source == "MKS" and target == "SI":
        dimension = group.dimension * 10.0
        fc = group.fc / MPA_TO_KGF_CM2
    else:
        raise ValueError("El sistema de unidades debe ser SI o MKS.")
    return ColumnGroup(**{**asdict(group), "dimension": dimension, "fc": fc})

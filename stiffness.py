"""Núcleo de cálculo para la rigidez lateral de columnas de concreto armado,
acero estructural o albañilería.

El módulo no depende del navegador. Puede reutilizarse más adelante en análisis
matricial, una API o aplicaciones de escritorio sin cambiar las ecuaciones base.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, isfinite, pi, radians, sin, sqrt
from typing import Literal


UnitSystem = Literal["SI", "MKS"]
SectionShape = Literal["square", "circle"]
JointType = Literal["fixed", "pinned"]
MaterialType = Literal["concrete", "steel"]
Direction = Literal["X", "Y"]

MPA_TO_KGF_CM2 = 10.1971621298

# Módulo elástico del acero: prácticamente constante en el rango elástico,
# a diferencia del concreto (no depende de una resistencia ingresada por
# el usuario).
STEEL_MODULUS_SI = 200_000.0  # MPa
STEEL_MODULUS_MKS = 2_039_000.0  # kgf/cm² (≈ 200 000 MPa)

MATERIAL_LABELS: dict[MaterialType, str] = {
    "concrete": "Concreto armado",
    "steel": "Acero estructural",
}

DIRECTION_LABELS: dict[Direction, str] = {
    "X": "Dirección X",
    "Y": "Dirección Y",
}


@dataclass(slots=True)
class ColumnGroup:
    id: str
    quantity: int
    shape: SectionShape
    dimension: float
    fc: float
    base: JointType
    top: JointType
    material: MaterialType = "concrete"
    direction: Direction = "X"
    axis: str = "1"
    x0: float = 0.0
    y0: float = 0.0
    beta: float = 0.0


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
    if group.material not in ("concrete", "steel"):
        raise ValueError("El material debe ser concreto o acero.")
    if group.direction not in ("X", "Y"):
        raise ValueError("La dirección debe ser X o Y.")
    axis = str(group.axis).strip()
    if not axis:
        raise ValueError("Cada grupo debe indicar un eje estructural.")
    if len(axis) > 12:
        raise ValueError("El nombre del eje no puede superar 12 caracteres.")
    if not all(isfinite(float(value)) for value in (group.x0, group.y0, group.beta)):
        raise ValueError("La posición y el ángulo del eje deben ser números válidos.")
    _positive_number(group.dimension, "La dimensión")
    _positive_number(group.fc, "La resistencia")


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


def material_label(material: MaterialType) -> str:
    return MATERIAL_LABELS.get(material, material)


def direction_label(direction: Direction) -> str:
    return DIRECTION_LABELS.get(direction, direction)


def resistance_label(material: MaterialType) -> str:
    """Nombre del parámetro de resistencia según el material."""
    if material == "steel":
        return "fy (referencial)"
    return "f′c"


def resistance_bounds(material: MaterialType, units: UnitSystem) -> tuple[str, str, str]:
    """(min, max, step) sugeridos para el campo de resistencia, como texto."""
    if material == "steel":
        return ("100", "600", "1") if units == "SI" else ("1000", "6000", "10")
    return ("10", "100", "0.1") if units == "SI" else ("100", "1000", "1")


def section_inertia(shape: SectionShape, dimension: float) -> float:
    dimension = _positive_number(dimension, "La dimensión")
    if shape == "square":
        return dimension**4 / 12.0
    if shape == "circle":
        return pi * dimension**4 / 64.0
    raise ValueError("La sección debe ser cuadrada o circular.")


def elastic_modulus(material: MaterialType, fc: float, units: UnitSystem) -> float:
    if units not in ("SI", "MKS"):
        raise ValueError("El sistema de unidades debe ser SI o MKS.")
    if material == "steel":
        # El módulo del acero es prácticamente constante en el rango elástico.
        return STEEL_MODULUS_SI if units == "SI" else STEEL_MODULUS_MKS
    fc = _positive_number(fc, "La resistencia")
    if material == "concrete":
        return (4_700.0 if units == "SI" else 15_000.0) * sqrt(fc)
    raise ValueError("El material debe ser concreto o acero.")


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
    modulus = elastic_modulus(group.material, group.fc, units)
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
    totals_by_direction: dict[Direction, float] = {"X": 0.0, "Y": 0.0}
    for group, result in zip(groups, results):
        totals_by_direction[group.direction] += result.contribution
    return {
        "total": sum(result.contribution for result in results),
        "totals": totals_by_direction,
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


# ---------------------------------------------------------------------------
# Análisis pseudotridimensional de diafragma rígido
# ---------------------------------------------------------------------------

KN_PER_TONF = 9.80665


def _zero_matrix(rows: int, columns: int) -> list[list[float]]:
    return [[0.0 for _ in range(columns)] for _ in range(rows)]


def _transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*matrix)]


def _matmul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    if not left or not right or len(left[0]) != len(right):
        raise ValueError("Las dimensiones de las matrices no son compatibles.")
    result = _zero_matrix(len(left), len(right[0]))
    for i in range(len(left)):
        for k in range(len(right)):
            if left[i][k] == 0.0:
                continue
            for j in range(len(right[0])):
                result[i][j] += left[i][k] * right[k][j]
    return result


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(value * vector[j] for j, value in enumerate(row)) for row in matrix]


def local_shear_matrix(story_stiffnesses: list[float]) -> list[list[float]]:
    """Matriz de un pórtico modelado como resortes de corte apilados."""
    if not story_stiffnesses:
        raise ValueError("El análisis necesita al menos un nivel.")
    matrix = _zero_matrix(len(story_stiffnesses), len(story_stiffnesses))
    for story, stiffness in enumerate(story_stiffnesses):
        stiffness = _positive_number(stiffness, f"La rigidez del nivel {story + 1}")
        matrix[story][story] += stiffness
        if story > 0:
            matrix[story - 1][story - 1] += stiffness
            matrix[story][story - 1] -= stiffness
            matrix[story - 1][story] -= stiffness
    return matrix


def frame_transformation(
    levels: int,
    beta_degrees: float,
    lever_arm_m: float,
) -> list[list[float]]:
    """Relaciona {ux, uy, theta} del diafragma con el desplazamiento del eje."""
    beta = radians(float(beta_degrees))
    direction_cosine = cos(beta)
    direction_sine = sin(beta)
    matrix = _zero_matrix(levels, 3 * levels)
    for level in range(levels):
        offset = 3 * level
        matrix[level][offset] = direction_cosine
        matrix[level][offset + 1] = direction_sine
        matrix[level][offset + 2] = float(lever_arm_m)
    return matrix


def solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Eliminación de Gauss con pivoteo parcial y detección de inestabilidad."""
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix) or len(vector) != size:
        raise ValueError("El sistema global debe ser cuadrado y compatible.")
    augmented = [list(map(float, row)) + [float(vector[i])] for i, row in enumerate(matrix)]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1e-10, scale * 1e-12)

    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise ValueError(
                "La matriz global es singular. Agrega ejes resistentes en X y Y, "
                "separados en planta, para controlar traslación y torsión."
            )
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]

        pivot_value = augmented[column][column]
        for row in range(column + 1, size):
            factor = augmented[row][column] / pivot_value
            if factor == 0.0:
                continue
            for item in range(column, size + 1):
                augmented[row][item] -= factor * augmented[column][item]

    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        residual = augmented[row][size] - sum(
            augmented[row][column] * solution[column]
            for column in range(row + 1, size)
        )
        solution[row] = residual / augmented[row][row]
    return solution


def analyze_pseudotridimensional(
    groups: list[ColumnGroup],
    story_heights_m: list[float],
    floor_forces_kn: list[float],
    alpha_degrees: float,
    center_mass_x_m: float,
    center_mass_y_m: float,
    accidental_eccentricity_x_m: float,
    accidental_eccentricity_y_m: float,
    units: UnitSystem,
) -> dict[str, object]:
    """Resuelve un edificio de diafragmas rígidos con 3 GDL por nivel.

    Cada grupo de columnas se interpreta como un eje resistente vertical con
    igual geometría en todos los niveles. Las fuerzas se ingresan en kN y la
    matriz global se devuelve en unidades coherentes kN, m y radianes.
    """
    levels = len(story_heights_m)
    if not 1 <= levels <= 12:
        raise ValueError("El análisis admite entre 1 y 12 niveles.")
    if len(floor_forces_kn) != levels:
        raise ValueError("Debe existir una fuerza sísmica para cada nivel.")
    if len(groups) < 2:
        raise ValueError("Agrega más ejes resistentes antes de iniciar el análisis global.")

    heights = [
        _positive_number(value, f"La altura del nivel {index + 1}")
        for index, value in enumerate(story_heights_m)
    ]
    forces = [float(value) for value in floor_forces_kn]
    scalar_inputs = (
        float(alpha_degrees),
        float(center_mass_x_m),
        float(center_mass_y_m),
        float(accidental_eccentricity_x_m),
        float(accidental_eccentricity_y_m),
    )
    if not all(isfinite(value) for value in (*forces, *scalar_inputs)):
        raise ValueError("Las fuerzas, coordenadas y excentricidades deben ser números válidos.")

    dofs = 3 * levels
    global_matrix = _zero_matrix(dofs, dofs)
    frame_results: list[dict[str, object]] = []

    for group in groups:
        validate_group(group)
        beta = radians(float(group.beta))
        lever_arm = (
            -(float(group.x0) - float(center_mass_x_m)) * sin(beta)
            + (float(group.y0) - float(center_mass_y_m)) * cos(beta)
        )
        story_stiffnesses = []
        for height in heights:
            stiffness = calculate_group(group, height, units).contribution
            if units == "MKS":
                stiffness *= KN_PER_TONF
            story_stiffnesses.append(stiffness)
        local_matrix = local_shear_matrix(story_stiffnesses)
        transformation = frame_transformation(levels, group.beta, lever_arm)
        contribution = _matmul(_matmul(_transpose(transformation), local_matrix), transformation)
        for row in range(dofs):
            for column in range(dofs):
                global_matrix[row][column] += contribution[row][column]
        frame_results.append(
            {
                "id": group.id,
                "axis": group.axis,
                "beta": float(group.beta),
                "x0": float(group.x0),
                "y0": float(group.y0),
                "lever_arm": lever_arm,
                "story_stiffnesses": story_stiffnesses,
                "local_matrix": local_matrix,
                "transformation": transformation,
            }
        )

    alpha = radians(float(alpha_degrees))
    force_vector: list[float] = []
    floor_loads: list[dict[str, float]] = []
    for force in forces:
        force_x = force * cos(alpha)
        force_y = force * sin(alpha)
        moment_z = (
            float(accidental_eccentricity_x_m) * force_y
            - float(accidental_eccentricity_y_m) * force_x
        )
        force_vector.extend((force_x, force_y, moment_z))
        floor_loads.append({"fx": force_x, "fy": force_y, "mz": moment_z})

    displacement_vector = solve_linear_system(global_matrix, force_vector)

    # Centro de rigidez en planta. Se obtiene desplazando el origen hasta
    # anular los acoplamientos traslación-giro de la matriz de un nivel.
    a_xx = a_xy = a_yy = b_x = b_y = 0.0
    for frame in frame_results:
        beta = radians(float(frame["beta"]))
        direction_x, direction_y = cos(beta), sin(beta)
        stiffness = float(frame["story_stiffnesses"][0])
        lever_arm = float(frame["lever_arm"])
        a_xx += stiffness * direction_x * direction_x
        a_xy += stiffness * direction_x * direction_y
        a_yy += stiffness * direction_y * direction_y
        b_x += stiffness * direction_x * lever_arm
        b_y += stiffness * direction_y * lever_arm
    determinant = a_xx * a_yy - a_xy * a_xy
    center_rigidity = None
    if abs(determinant) > max(1e-12, (abs(a_xx) + abs(a_yy)) ** 2 * 1e-12):
        q_x = (-b_x * a_yy + a_xy * b_y) / determinant
        q_y = (a_xy * b_x - a_xx * b_y) / determinant
        center_rigidity = {
            "x": float(center_mass_x_m) + q_y,
            "y": float(center_mass_y_m) - q_x,
        }

    displacements = []
    previous_x = 0.0
    previous_y = 0.0
    for level, height in enumerate(heights):
        ux, uy, theta = displacement_vector[3 * level : 3 * level + 3]
        relative_x = ux - previous_x
        relative_y = uy - previous_y
        displacements.append(
            {
                "level": level + 1,
                "ux": ux,
                "uy": uy,
                "theta": theta,
                "drift_x": relative_x / height,
                "drift_y": relative_y / height,
            }
        )
        previous_x, previous_y = ux, uy

    for frame, group in zip(frame_results, groups):
        local_displacements = _matvec(frame["transformation"], displacement_vector)
        floor_actions = _matvec(frame["local_matrix"], local_displacements)
        story_shears = [sum(floor_actions[level:]) for level in range(levels)]
        column_shears = [value / int(group.quantity) for value in story_shears]
        if group.base == "fixed" and group.top == "fixed":
            end_moments = [
                column_shears[level] * heights[level] / 2.0
                for level in range(levels)
            ]
        else:
            end_moments = [None for _ in range(levels)]
        frame.update(
            {
                "local_displacements": local_displacements,
                "floor_actions": floor_actions,
                "story_shears": story_shears,
                "column_shears": column_shears,
                "end_moments": end_moments,
            }
        )

    return {
        "levels": levels,
        "global_matrix": global_matrix,
        "force_vector": force_vector,
        "displacement_vector": displacement_vector,
        "floor_loads": floor_loads,
        "center_rigidity": center_rigidity,
        "displacements": displacements,
        "frames": frame_results,
        "units": {"force": "kN", "length": "m", "rotation": "rad"},
    }

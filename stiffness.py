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
MAX_COLUMN_GROUPS = 20

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
    # Pórticos generados (proyecto DD): matriz lateral condensada en kN/m,
    # rigidez de entrepiso equivalente en kN/m y columnas por entrepiso.
    lateral_matrix: list | None = None
    equivalent_story: list | None = None
    level_quantities: list | None = None
    modulus: float = 0.0  # E dado directamente (MPa en SI, kgf/cm² en MKS)


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


def elastic_modulus(material: MaterialType, fc: float, units: UnitSystem, modulus: float = 0.0) -> float:
    if units not in ("SI", "MKS"):
        raise ValueError("El sistema de unidades debe ser SI o MKS.")
    if material == "steel":
        # El módulo del acero es prácticamente constante en el rango elástico.
        return STEEL_MODULUS_SI if units == "SI" else STEEL_MODULUS_MKS
    if modulus and modulus > 0:
        return float(modulus)
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
    modulus = elastic_modulus(group.material, group.fc, units, group.modulus)
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
    if not 1 <= len(groups) <= MAX_COLUMN_GROUPS:
        raise ValueError(f"Debe existir entre 1 y {MAX_COLUMN_GROUPS} grupos de columnas.")
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
        modulus = group.modulus * MPA_TO_KGF_CM2
    elif source == "MKS" and target == "SI":
        dimension = group.dimension * 10.0
        fc = group.fc / MPA_TO_KGF_CM2
        modulus = group.modulus / MPA_TO_KGF_CM2
    else:
        raise ValueError("El sistema de unidades debe ser SI o MKS.")
    return ColumnGroup(**{**asdict(group), "dimension": dimension, "fc": fc, "modulus": modulus})


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
        stiffness = float(stiffness)
        if not isfinite(stiffness) or stiffness < 0:
            raise ValueError(f"La rigidez del nivel {story + 1} no puede ser negativa.")
        matrix[story][story] += stiffness
        if story > 0:
            matrix[story - 1][story - 1] += stiffness
            matrix[story][story - 1] -= stiffness
            matrix[story - 1][story] -= stiffness
    return matrix


def frame_transformation(
    levels: int,
    beta_degrees: float,
    lever_arm_m: float | list[float],
) -> list[list[float]]:
    """Relaciona {ux, uy, theta} del diafragma con el desplazamiento del eje."""
    if isinstance(lever_arm_m, (list, tuple)):
        if len(lever_arm_m) != levels:
            raise ValueError("Debe existir un brazo de palanca por nivel.")
        lever_arms = [float(value) for value in lever_arm_m]
    else:
        lever_arms = [float(lever_arm_m)] * levels
    if not all(isfinite(value) for value in lever_arms):
        raise ValueError("Los brazos de palanca deben ser números válidos.")
    beta = radians(float(beta_degrees))
    direction_cosine = cos(beta)
    direction_sine = sin(beta)
    matrix = _zero_matrix(levels, 3 * levels)
    for level in range(levels):
        offset = 3 * level
        matrix[level][offset] = direction_cosine
        matrix[level][offset + 1] = direction_sine
        matrix[level][offset + 2] = lever_arms[level]
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


def _level_values(value: float | list[float], levels: int, field_name: str) -> list[float]:
    if isinstance(value, (list, tuple)):
        if len(value) != levels:
            raise ValueError(f"{field_name} debe tener un valor por nivel.")
        values = [float(item) for item in value]
    else:
        values = [float(value)] * levels
    if not all(isfinite(item) for item in values):
        raise ValueError(f"{field_name} debe contener números válidos.")
    return values


def analyze_pseudotridimensional(
    groups: list[ColumnGroup],
    story_heights_m: list[float],
    floor_forces_kn: list[float],
    alpha_degrees: float,
    center_mass_x_m: float | list[float],
    center_mass_y_m: float | list[float],
    accidental_eccentricity_x_m: float | list[float],
    accidental_eccentricity_y_m: float | list[float],
    units: UnitSystem,
    story_stiffness_overrides: dict[str, list[float]] | None = None,
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
    scalar_inputs = (float(alpha_degrees),)
    if not all(isfinite(value) for value in (*forces, *scalar_inputs)):
        raise ValueError("Las fuerzas, coordenadas y excentricidades deben ser números válidos.")
    centers_x = _level_values(center_mass_x_m, levels, "El centro de masa X")
    centers_y = _level_values(center_mass_y_m, levels, "El centro de masa Y")
    eccentricities_x = _level_values(
        accidental_eccentricity_x_m, levels, "La excentricidad accidental en X"
    )
    eccentricities_y = _level_values(
        accidental_eccentricity_y_m, levels, "La excentricidad accidental en Y"
    )

    override_values = {"X": [0.0] * levels, "Y": [0.0] * levels}
    if story_stiffness_overrides:
        for direction in ("X", "Y"):
            if direction not in story_stiffness_overrides:
                continue
            values = _level_values(
                story_stiffness_overrides[direction],
                levels,
                f"La rigidez de control en {direction}",
            )
            if any(value < 0 for value in values):
                raise ValueError("Las rigideces de control no pueden ser negativas.")
            override_values[direction] = values

    raw_stiffnesses: list[list[float]] = []
    direction_totals = {"X": [0.0] * levels, "Y": [0.0] * levels}
    for group in groups:
        validate_group(group)
        group_stiffnesses = []
        if group.lateral_matrix is not None:
            if len(group.lateral_matrix) != levels or len(group.equivalent_story or []) != levels:
                raise ValueError(f"La matriz del pórtico {group.axis} no corresponde a {levels} niveles.")
            group_stiffnesses = [float(value) for value in group.equivalent_story]
        else:
            for height in heights:
                stiffness = calculate_group(group, height, units).contribution
                if units == "MKS":
                    stiffness *= KN_PER_TONF
                group_stiffnesses.append(stiffness)
        raw_stiffnesses.append(group_stiffnesses)
        for level, stiffness in enumerate(group_stiffnesses):
            direction_totals[group.direction][level] += stiffness

    direction_scales = {"X": [1.0] * levels, "Y": [1.0] * levels}
    for direction in ("X", "Y"):
        for level, override in enumerate(override_values[direction]):
            if override <= 0:
                continue
            total = direction_totals[direction][level]
            if total <= 0:
                raise ValueError(
                    f"No existe rigidez base en {direction} para aplicar el control del nivel {level + 1}."
                )
            direction_scales[direction][level] = override / total

    dofs = 3 * levels
    global_matrix = _zero_matrix(dofs, dofs)
    frame_results: list[dict[str, object]] = []

    for group, raw_group_stiffnesses in zip(groups, raw_stiffnesses):
        beta = radians(float(group.beta))
        # Giro θ positivo antihorario: un punto (x, y) del diafragma se mueve
        # u = ux − θ·(y − y_CM), v = uy + θ·(x − x_CM). Proyectado sobre la
        # dirección del eje (cos β, sin β) da d = ux·cos β + uy·sin β + r·θ.
        lever_arms = [
            (float(group.x0) - centers_x[level]) * sin(beta)
            - (float(group.y0) - centers_y[level]) * cos(beta)
            for level in range(levels)
        ]
        scales = [direction_scales[group.direction][level] for level in range(levels)]
        story_stiffnesses = [
            stiffness * scales[level]
            for level, stiffness in enumerate(raw_group_stiffnesses)
        ]
        if group.lateral_matrix is not None:
            # Pórtico con vigas flexibles: matriz condensada, escalada por nivel
            # de forma simétrica si se impuso una rigidez de control.
            root = [sqrt(value) for value in scales]
            local_matrix = [
                [float(group.lateral_matrix[i][j]) * root[i] * root[j] for j in range(levels)]
                for i in range(levels)
            ]
        else:
            local_matrix = local_shear_matrix(story_stiffnesses)
        transformation = frame_transformation(levels, group.beta, lever_arms)
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
                "lever_arm": lever_arms[0],
                "lever_arms": lever_arms,
                "story_stiffnesses": story_stiffnesses,
                "local_matrix": local_matrix,
                "transformation": transformation,
            }
        )

    alpha = radians(float(alpha_degrees))
    force_vector: list[float] = []
    floor_loads: list[dict[str, float]] = []
    for level, force in enumerate(forces):
        force_x = force * cos(alpha)
        force_y = force * sin(alpha)
        moment_z = (
            eccentricities_x[level] * force_y
            - eccentricities_y[level] * force_x
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
        lever_arm = float(frame["lever_arms"][0])
        a_xx += stiffness * direction_x * direction_x
        a_xy += stiffness * direction_x * direction_y
        a_yy += stiffness * direction_y * direction_y
        b_x += stiffness * direction_x * lever_arm
        b_y += stiffness * direction_y * lever_arm
    determinant = a_xx * a_yy - a_xy * a_xy
    center_rigidity = None
    if abs(determinant) > max(1e-12, (abs(a_xx) + abs(a_yy)) ** 2 * 1e-12):
        # Punto (x_CM + dx, y_CM + dy) donde una fuerza traslacional no genera giro.
        offset_x = (a_xx * b_y - a_xy * b_x) / determinant
        offset_y = (a_xy * b_y - a_yy * b_x) / determinant
        center_rigidity = {
            "x": centers_x[0] + offset_x,
            "y": centers_y[0] + offset_y,
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
        quantities = (
            [int(value) for value in group.level_quantities]
            if group.level_quantities is not None and len(group.level_quantities) == levels
            else [int(group.quantity)] * levels
        )
        column_shears = [
            value / quantities[level] if quantities[level] > 0 else 0.0
            for level, value in enumerate(story_shears)
        ]
        # Momento máximo de extremo: doble curvatura (empotrado-rígido) Vh/2;
        # con un extremo articulado todo el momento Vh se concentra en el otro.
        if group.base == "fixed" and group.top == "fixed":
            moment_factor = 0.5
        elif group.base == "pinned" and group.top == "pinned":
            moment_factor = None
        else:
            moment_factor = 1.0
        end_moments = [
            None if moment_factor is None else column_shears[level] * heights[level] * moment_factor
            for level in range(levels)
        ]
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


def assess_torsional_irregularity(
    groups: list[ColumnGroup],
    story_heights_m: list[float],
    floor_forces_kn: list[float],
    center_mass_x_m: float | list[float],
    center_mass_y_m: float | list[float],
    plan_x_m: list[float],
    plan_y_m: list[float],
    drift_limit: float,
    units: UnitSystem,
    story_stiffness_overrides: dict[str, list[float]] | None = None,
    displacement_scale: float = 1.0,
) -> dict[str, object]:
    """Control torsional de la Tabla 12 usando los dos signos de 5% accidental."""

    levels = len(story_heights_m)
    if len(plan_x_m) != levels or len(plan_y_m) != levels:
        raise ValueError("Las dimensiones de planta deben corresponder a todos los niveles.")
    if drift_limit <= 0:
        raise ValueError("El límite de deriva debe ser mayor que cero.")
    if not isfinite(float(displacement_scale)) or displacement_scale <= 0:
        raise ValueError("El factor de amplificación de desplazamientos debe ser positivo.")
    plan_x = [_positive_number(value, f"La dimensión X del nivel {index + 1}") for index, value in enumerate(plan_x_m)]
    plan_y = [_positive_number(value, f"La dimensión Y del nivel {index + 1}") for index, value in enumerate(plan_y_m)]

    cases: list[dict[str, float | int | str | bool]] = []
    for direction, alpha in (("X", 0.0), ("Y", 90.0)):
        for sign in (-1.0, 1.0):
            ecc_x = [sign * 0.05 * value if direction == "Y" else 0.0 for value in plan_x]
            ecc_y = [sign * 0.05 * value if direction == "X" else 0.0 for value in plan_y]
            result = analyze_pseudotridimensional(
                groups,
                story_heights_m,
                floor_forces_kn,
                alpha,
                center_mass_x_m,
                center_mass_y_m,
                ecc_x,
                ecc_y,
                units,
                story_stiffness_overrides,
            )
            previous_translation = 0.0
            previous_rotation = 0.0
            for level in range(levels):
                ux, uy, rotation = result["displacement_vector"][3 * level : 3 * level + 3]
                translation = ux if direction == "X" else uy
                relative_translation = translation - previous_translation
                relative_rotation = rotation - previous_rotation
                half_span = 0.5 * (plan_y[level] if direction == "X" else plan_x[level])
                if direction == "X":
                    edge_a = relative_translation - half_span * relative_rotation
                    edge_b = relative_translation + half_span * relative_rotation
                else:
                    edge_a = relative_translation + half_span * relative_rotation
                    edge_b = relative_translation - half_span * relative_rotation
                maximum = max(abs(edge_a), abs(edge_b)) * displacement_scale
                average = 0.5 * (abs(edge_a) + abs(edge_b)) * displacement_scale
                ratio = maximum / average if average > 1e-15 else 1.0
                drift = maximum / float(story_heights_m[level])
                applicable = drift > 0.5 * drift_limit
                cases.append(
                    {
                        "direction": direction,
                        "sign": int(sign),
                        "level": level + 1,
                        "delta_max": maximum,
                        "delta_average": average,
                        "ratio": ratio,
                        "drift": drift,
                        "applicable": applicable,
                    }
                )
                previous_translation = translation
                previous_rotation = rotation

    return {
        "torsional": any(bool(case["applicable"]) and float(case["ratio"]) > 1.30 for case in cases),
        "extreme_torsional": any(bool(case["applicable"]) and float(case["ratio"]) > 1.50 for case in cases),
        "cases": cases,
    }


# ---------------------------------------------------------------------------
# Matriz de flexibilidad y análisis modal
# ---------------------------------------------------------------------------


def invert_matrix(matrix: list[list[float]]) -> list[list[float]]:
    """Inversa por Gauss-Jordan con pivoteo parcial (matriz de flexibilidad)."""
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        raise ValueError("Sólo se puede invertir una matriz cuadrada.")
    augmented = [
        [float(value) for value in row] + [1.0 if i == j else 0.0 for j in range(size)]
        for i, row in enumerate(matrix)
    ]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1e-10, scale * 1e-12)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= tolerance:
            raise ValueError("La matriz es singular y no tiene inversa.")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        augmented[column] = [value / pivot_value for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            pivot_row = augmented[column]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], pivot_row)]
    return [row[size:] for row in augmented]


def _cholesky(matrix: list[list[float]]) -> list[list[float]]:
    size = len(matrix)
    lower = _zero_matrix(size, size)
    for i in range(size):
        for j in range(i + 1):
            total = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if total <= 0:
                    raise ValueError("La matriz de masas debe ser definida positiva.")
                lower[i][j] = sqrt(total)
            else:
                lower[i][j] = total / lower[j][j]
    return lower


def _lower_inverse(lower: list[list[float]]) -> list[list[float]]:
    size = len(lower)
    inverse = _zero_matrix(size, size)
    for column in range(size):
        for row in range(column, size):
            total = 1.0 if row == column else 0.0
            total -= sum(lower[row][k] * inverse[k][column] for k in range(column, row))
            inverse[row][column] = total / lower[row][row]
    return inverse


def symmetric_eigen(matrix: list[list[float]], tolerance: float = 1e-12, max_sweeps: int = 100):
    """Valores y vectores propios de una matriz simétrica (método de Jacobi cíclico)."""
    size = len(matrix)
    a = [list(map(float, row)) for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    scale = max((abs(a[i][i]) for i in range(size)), default=1.0) or 1.0
    for _ in range(max_sweeps):
        off = sum(a[i][j] ** 2 for i in range(size) for j in range(i + 1, size))
        if off <= (tolerance * scale) ** 2:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if abs(a[p][q]) <= 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + sqrt(theta * theta + 1.0))
                c = 1.0 / sqrt(t * t + 1.0)
                s = t * c
                for k in range(size):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(size):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(size):
                    vkp, vkq = vectors[k][p], vectors[k][q]
                    vectors[k][p] = c * vkp - s * vkq
                    vectors[k][q] = s * vkp + c * vkq
    values = [a[i][i] for i in range(size)]
    columns = [[vectors[k][i] for k in range(size)] for i in range(size)]
    return values, columns


def diaphragm_mass_matrix(level_masses: list[dict[str, float]]) -> list[list[float]]:
    """Matriz de masas con 3 GDL por nivel referidos al punto del análisis.

    Cada nivel recibe {"mass": t, "inertia": t·m² respecto a su propio CM,
    "dx", "dy": posición de su CM respecto al punto de referencia}. Con giro
    antihorario, el CM se mueve u = ux − θ·dy, v = uy + θ·dx.
    """
    levels = len(level_masses)
    matrix = _zero_matrix(3 * levels, 3 * levels)
    for level, item in enumerate(level_masses):
        mass = float(item["mass"])
        inertia = float(item["inertia"])
        dx = float(item.get("dx", 0.0))
        dy = float(item.get("dy", 0.0))
        if not all(isfinite(value) for value in (mass, inertia, dx, dy)):
            raise ValueError(f"La masa del nivel {level + 1} debe contener números válidos.")
        if mass <= 0 or inertia <= 0:
            raise ValueError(f"El nivel {level + 1} necesita masa e inercia rotacional positivas.")
        o = 3 * level
        matrix[o][o] = mass
        matrix[o + 1][o + 1] = mass
        matrix[o][o + 2] = matrix[o + 2][o] = -mass * dy
        matrix[o + 1][o + 2] = matrix[o + 2][o + 1] = mass * dx
        matrix[o + 2][o + 2] = inertia + mass * (dx * dx + dy * dy)
    return matrix


def modal_analysis(
    global_matrix: list[list[float]],
    level_masses: list[dict[str, float]],
) -> dict[str, object]:
    """Resuelve [K]{φ} = ω²[M]{φ} y calcula la participación de masa por modo.

    K en kN/m (kN·m/rad en giros) y M en t (t·m² en giros) entregan ω en rad/s.
    """
    size = len(global_matrix)
    if size != 3 * len(level_masses):
        raise ValueError("Debe existir una masa por cada nivel del modelo.")
    mass_matrix = diaphragm_mass_matrix(level_masses)
    lower = _cholesky(mass_matrix)
    lower_inv = _lower_inverse(lower)
    reduced = _matmul(_matmul(lower_inv, global_matrix), _transpose(lower_inv))
    reduced = [
        [0.5 * (reduced[i][j] + reduced[j][i]) for j in range(size)] for i in range(size)
    ]
    eigenvalues, eigenvectors = symmetric_eigen(reduced)
    lower_inv_t = _transpose(lower_inv)

    influence = {
        "X": [1.0 if dof % 3 == 0 else 0.0 for dof in range(size)],
        "Y": [1.0 if dof % 3 == 1 else 0.0 for dof in range(size)],
        "RZ": [1.0 if dof % 3 == 2 else 0.0 for dof in range(size)],
    }

    # Modos repetidos (p. ej. X e Y con igual periodo): cualquier combinación
    # es solución. Se rota cada grupo para alinear los modos con X, luego Y.
    order = sorted(range(size), key=lambda index: eigenvalues[index])
    eigenvalues = [eigenvalues[index] for index in order]
    eigenvectors = [eigenvectors[index] for index in order]
    lower_t = _transpose(lower)
    load_x = _matvec(lower_t, influence["X"])
    load_y = _matvec(lower_t, influence["Y"])
    start = 0
    while start < size:
        end = start + 1
        while end < size and abs(eigenvalues[end] - eigenvalues[start]) <= 1e-7 * max(abs(eigenvalues[start]), 1e-30):
            end += 1
        if end - start > 1:
            cluster = eigenvectors[start:end]
            a_x = [sum(v * w for v, w in zip(vector, load_x)) for vector in cluster]
            a_y = [sum(v * w for v, w in zip(vector, load_y)) for vector in cluster]
            weights = [
                [a_x[i] * a_x[j] + 1e-3 * a_y[i] * a_y[j] for j in range(len(cluster))]
                for i in range(len(cluster))
            ]
            _, rotations = symmetric_eigen(weights)
            rotated = [
                [sum(rotation[k] * cluster[k][dof] for k in range(len(cluster))) for dof in range(size)]
                for rotation in rotations
            ]
            rotated.sort(key=lambda vector: -abs(sum(v * w for v, w in zip(vector, load_x))))
            eigenvectors[start:end] = rotated
        start = end
    total_mass = {
        key: sum(r_i * value for r_i, value in zip(vector, _matvec(mass_matrix, vector)))
        for key, vector in influence.items()
    }

    largest = max((abs(value) for value in eigenvalues), default=1.0) or 1.0
    modes = []
    for eigenvalue, vector in sorted(zip(eigenvalues, eigenvectors), key=lambda item: item[0]):
        if eigenvalue <= largest * 1e-12:
            raise ValueError("El modelo tiene un modo sin rigidez; revisa la estabilidad en X, Y y torsión.")
        shape = _matvec(lower_inv_t, vector)  # normalizado a φᵀMφ = 1
        m_shape = _matvec(mass_matrix, shape)
        generalized_mass = sum(a * b for a, b in zip(shape, m_shape))
        factors = {}
        effective = {}
        for key, vector_r in influence.items():
            l_n = sum(a * b for a, b in zip(m_shape, vector_r))
            factors[key] = l_n / generalized_mass
            effective[key] = (l_n * l_n / generalized_mass) / total_mass[key] if total_mass[key] > 0 else 0.0
        # Normaliza la forma para que el mayor desplazamiento traslacional sea 1.
        translations = [abs(value) for dof, value in enumerate(shape) if dof % 3 != 2]
        reference = max(translations, default=0.0)
        if reference <= 1e-15:
            reference = max(abs(value) for value in shape)
        peak = max(range(size), key=lambda dof: abs(shape[dof]) if (dof % 3 != 2 or reference == 0) else 0.0)
        sign = 1.0 if shape[peak] >= 0 else -1.0
        normalized = [sign * value / reference for value in shape]
        omega = sqrt(eigenvalue)
        dominant = max(effective, key=effective.get)
        modes.append(
            {
                "omega": omega,
                "frequency": omega / (2.0 * pi),
                "period": 2.0 * pi / omega,
                "shape": normalized,
                "participation": {key: sign * reference * value for key, value in factors.items()},
                "mass_ratio": effective,
                "dominant": dominant,
            }
        )

    cumulative = {"X": 0.0, "Y": 0.0, "RZ": 0.0}
    for mode in modes:
        for key in cumulative:
            cumulative[key] += mode["mass_ratio"][key]
        mode["cumulative"] = dict(cumulative)

    return {
        "mass_matrix": mass_matrix,
        "modes": modes,
        "total_mass": total_mass,
    }

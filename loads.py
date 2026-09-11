"""Metrado de cargas: peso sísmico por nivel (E.020) y fuerzas sísmicas
estáticas por nivel (E.030 - método estático equivalente).

Módulo sin dependencias del navegador, reutilizable igual que stiffness.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal


SoilProfile = Literal["S0", "S1", "S2", "S3", "S4"]
UseCategory = Literal["A1", "A2", "B", "C"]
StructuralSystem = Literal["porticos", "dual", "muros", "albanileria"]


@dataclass
class LevelLoad:
    """Datos de metrado de un nivel (piso o techo)."""

    id: str
    label: str
    area: float  # m2 (área techada / tributaria del nivel)
    cm: float  # kN/m2 (carga muerta: peso propio + acabados + tabiquería)
    cv: float  # kN/m2 (sobrecarga de uso, sin reducir)
    height: float  # m (altura de piso a piso, usada para h_i acumulada)
    is_roof: bool = False
    use_key: str = ""  # uso E.020 seleccionado; permite conservarlo en la interfaz
    beam_count: int = 0
    beam_width: float = 0.25  # m
    beam_depth: float = 0.40  # m
    beam_length: float = 4.0  # m por viga
    beam_volume_override: float | None = None  # m3; volumen exacto del modelo gráfico
    slab_thickness: float = 0.20  # m
    slab_volume_override: float | None = None  # m3; volumen exacto de paños modelados
    center_x: float = 2.5  # m, centroide de losa y cargas superficiales
    center_y: float = 2.0  # m
    beam_center_x: float = 2.5  # m, centroide del grupo de vigas
    beam_center_y: float = 2.0  # m
    plan_x: float = 5.0  # m, dimensión total/resistente del nivel en X
    plan_y: float = 4.0  # m, dimensión total/resistente del nivel en Y
    stiffness_x_override: float = 0.0  # kN/m; 0 usa la rigidez heredada
    stiffness_y_override: float = 0.0  # kN/m; 0 usa la rigidez heredada
    strength_x: float = 0.0  # kN; resistencia de entrepiso, 0 = no evaluada
    strength_y: float = 0.0  # kN; resistencia de entrepiso, 0 = no evaluada


# ---------------------------------------------------------------------------
# E.020 · Cargas mínimas de referencia (kN/m2) para pre-llenar CV según uso.
# Valores orientativos de la Norma E.020 Cargas; el usuario puede editarlos.
# ---------------------------------------------------------------------------
LIVE_LOAD_PRESETS: dict[str, tuple[str, float]] = {
    "vivienda": ("Vivienda", 2.0),
    "oficina": ("Oficina", 2.5),
    "aula": ("Aula / centro de enseñanza", 3.0),
    "corredor_publico": ("Corredores y escaleras de acceso público", 4.0),
    "tienda": ("Tiendas / centros comerciales", 5.0),
    "biblioteca_salas": ("Bibliotecas: salas de lectura", 3.0),
    "biblioteca_deposito": ("Bibliotecas: salas de almacenaje", 7.5),
    "garaje_liviano": ("Estacionamiento de vehículos livianos", 2.5),
    "azotea_no_transitable": ("Azotea / techo no transitable", 1.0),
    "otro": ("Otro (ingresar manualmente)", 2.0),
}


def live_load_preset(key: str) -> float:
    entry = LIVE_LOAD_PRESETS.get(key)
    return entry[1] if entry else 2.0


# ---------------------------------------------------------------------------
# E.030 · Peso sísmico por nivel: P = CM + (%CV) * CV
# ---------------------------------------------------------------------------
CATEGORY_CV_FACTOR: dict[UseCategory, float] = {
    "A1": 0.5,
    "A2": 0.5,
    "B": 0.5,
    "C": 0.25,
}
ROOF_CV_FACTOR = 0.25  # E.030: azoteas y techos en general, 25% de la S/C.

CATEGORY_LABELS: dict[UseCategory, str] = {
    "A1": "A₁ · Salud esencial sin aislamiento · U = 1,5",
    "A2": "A₂ · Edificaciones esenciales · U = 1,5",
    "B": "B · Edificaciones importantes",
    "C": "C · Edificaciones comunes",
}
USE_FACTOR_U: dict[UseCategory, float] = {
    "A1": 1.5,
    "A2": 1.5,
    "B": 1.3,
    "C": 1.0,
}

CONCRETE_UNIT_WEIGHT = 24.0  # kN/m³, valor usual para concreto armado.
GRAVITY_ACCELERATION = 9.81  # m/s²


def component_mass_properties(
    weight_kn: float,
    center_x_m: float,
    center_y_m: float,
    participation: float = 1.0,
) -> dict[str, float]:
    """Peso participante, masa equivalente y momentos de masa de un componente."""

    participating_weight = max(0.0, float(weight_kn)) * max(0.0, float(participation))
    mass = participating_weight / GRAVITY_ACCELERATION
    center_x = float(center_x_m)
    center_y = float(center_y_m)
    return {
        "weight": participating_weight,
        "mass": mass,
        "x": center_x,
        "y": center_y,
        "mx": mass * center_x,
        "my": mass * center_y,
    }


def combine_mass_properties(components: list[dict[str, float]]) -> dict[str, float]:
    """Combina componentes y obtiene el centro de masa XCM,YCM."""

    total_weight = sum(float(item["weight"]) for item in components)
    total_mass = sum(float(item["mass"]) for item in components)
    moment_x = sum(float(item["mx"]) for item in components)
    moment_y = sum(float(item["my"]) for item in components)
    return {
        "weight": total_weight,
        "mass": total_mass,
        "mx": moment_x,
        "my": moment_y,
        "center_x": moment_x / total_mass if total_mass else 0.0,
        "center_y": moment_y / total_mass if total_mass else 0.0,
    }


def beam_takeoff(level: LevelLoad) -> tuple[float, float]:
    """Volumen y peso propio de las vigas del nivel."""

    if level.beam_volume_override is None:
        volume = (
            max(0, int(level.beam_count))
            * max(0.0, float(level.beam_width))
            * max(0.0, float(level.beam_depth))
            * max(0.0, float(level.beam_length))
        )
    else:
        volume = max(0.0, float(level.beam_volume_override))
    return volume, volume * CONCRETE_UNIT_WEIGHT


def level_gravity_breakdown(level: LevelLoad, column_weight_kn: float = 0.0) -> dict[str, float]:
    """Desglosa cargas permanentes, elementos estructurales y carga viva."""

    beam_volume, beam_weight = beam_takeoff(level)
    surface_dead = float(level.cm) * float(level.area)
    slab_volume = (
        float(level.slab_thickness) * float(level.area)
        if level.slab_volume_override is None
        else max(0.0, float(level.slab_volume_override))
    )
    slab_weight = slab_volume * CONCRETE_UNIT_WEIGHT
    other_surface_dead = max(0.0, surface_dead - slab_weight)
    live_load = float(level.cv) * float(level.area)
    column_weight = max(0.0, float(column_weight_kn))
    return {
        "surface_dead": surface_dead,
        "slab_volume": slab_volume,
        "slab_weight": slab_weight,
        "other_surface_dead": other_surface_dead,
        "column_weight": column_weight,
        "beam_volume": beam_volume,
        "beam_weight": beam_weight,
        "dead_total": surface_dead + column_weight + beam_weight,
        "live_total": live_load,
    }


def level_seismic_weight(
    level: LevelLoad,
    category: UseCategory,
    column_weight_kn: float = 0.0,
) -> float:
    """Peso sísmico Pi = (CM + factor*CV) * área, en kN."""

    factor = ROOF_CV_FACTOR if level.is_roof else CATEGORY_CV_FACTOR.get(category, 0.25)
    breakdown = level_gravity_breakdown(level, column_weight_kn)
    return breakdown["dead_total"] + factor * breakdown["live_total"]


def level_gravity_totals(level: LevelLoad, column_weight_kn: float = 0.0) -> tuple[float, float]:
    """Carga muerta y viva totales del nivel, en kN (sin reducir)."""

    breakdown = level_gravity_breakdown(level, column_weight_kn)
    return breakdown["dead_total"], breakdown["live_total"]


# ---------------------------------------------------------------------------
# E.030 · Parámetros de sitio y espectro (Z, U, S, TP, TL, C)
# ---------------------------------------------------------------------------
ZONE_FACTORS: dict[str, float] = {"1": 0.10, "2": 0.25, "3": 0.35, "4": 0.45}
ZONE_LABELS: dict[str, str] = {
    "1": "Zona 1 (Z = 0,10)",
    "2": "Zona 2 (Z = 0,25)",
    "3": "Zona 3 (Z = 0,35)",
    "4": "Zona 4 (Z = 0,45)",
}

# E.030:2026, Tabla N° 4. Para S2 y S3 se usan los extremos más
# desfavorables indicados por la norma cuando no se dispone de Vs30.
SOIL_FACTORS: dict[str, dict[SoilProfile, float | None]] = {
    "4": {"S0": 0.80, "S1": 1.00, "S2": 1.10, "S3": 1.20, "S4": None},
    "3": {"S0": 0.80, "S1": 1.00, "S2": 1.15, "S3": 1.20, "S4": 1.30},
    "2": {"S0": 0.80, "S1": 1.00, "S2": 1.30, "S3": 1.40, "S4": 1.70},
    "1": {"S0": 0.80, "S1": 1.00, "S2": 1.30, "S3": 1.60, "S4": 2.40},
}

# E.030:2026, Tabla N° 5. S2 y S3: valores conservadores sin Vs30.
SOIL_PERIODS: dict[SoilProfile, tuple[float, float]] = {
    "S0": (0.3, 3.0),
    "S1": (0.4, 2.5),
    "S2": (0.6, 2.0),
    "S3": (0.9, 1.6),
    "S4": (1.2, 1.6),
}
SOIL_LABELS: dict[SoilProfile, str] = {
    "S0": "S0 · Roca",
    "S1": "S1 · Suelos muy rígidos",
    "S2": "S2 · Suelos rígidos",
    "S3": "S3 · Suelos intermedios",
    "S4": "S4 · Suelos blandos",
}

BASIC_R: dict[StructuralSystem, float] = {
    "porticos": 8.0,
    "dual": 7.0,
    "muros": 6.0,
    "albanileria": 3.0,
}
STRUCTURAL_SYSTEM_LABELS: dict[StructuralSystem, str] = {
    "porticos": "Pórticos de concreto armado (R₀ = 8)",
    "dual": "Sistema dual (R₀ = 7)",
    "muros": "Muros estructurales (R₀ = 6)",
    "albanileria": "Albañilería armada o confinada (R₀ = 3)",
}

BASE_PERIOD_CT: dict[StructuralSystem, float] = {
    "porticos": 35.0,
    "dual": 60.0,
    "muros": 60.0,
    "albanileria": 60.0,
}


def soil_factor_s(zone: str, soil: SoilProfile) -> float:
    value = SOIL_FACTORS.get(zone, SOIL_FACTORS["2"]).get(soil)
    if value is None:
        raise ValueError("El perfil S4 en la Zona 4 requiere un análisis de respuesta de sitio.")
    return value


def site_periods(soil: SoilProfile) -> tuple[float, float]:
    return SOIL_PERIODS.get(soil, SOIL_PERIODS["S1"])


def amplification_factor_c(period: float, tp: float, tl: float) -> float:
    """Factor C del espectro según E.030:2026, Tabla N° 6."""

    period = max(period, 0.0)
    if period < 0.2 * tp:
        return 1.0 + 7.5 * (period / tp)
    if period <= tp:
        return 2.5
    if period <= tl:
        return 2.5 * (tp / period)
    return 2.5 * (tp * tl / period ** 2)


def estimate_period(total_height: float, system: StructuralSystem) -> float:
    """Estimación simplificada T = hn / CT (E.030:2026, artículo 36)."""

    ct = BASE_PERIOD_CT.get(system, 45.0)
    return total_height / ct if ct else 0.0


def height_exponent(period: float) -> float:
    """Exponente k para la distribución de fuerzas en altura (E.030:2026, artículo 35)."""

    if period <= 0.5:
        return 1.0
    return min(0.75 + 0.5 * period, 2.0)


@dataclass
class SeismicSiteParams:
    zone: str
    soil: SoilProfile
    category: UseCategory
    system: StructuralSystem
    irregularity_height: float = 1.0  # Ia
    irregularity_plan: float = 1.0  # Ip
    period_override: float | None = None  # T manual, si el usuario lo define


@dataclass
class SeismicDirectionResult:
    z: float
    u: float
    c: float
    c_effective: float
    s: float
    r: float
    tp: float
    tl: float
    period: float
    weight_total: float
    base_shear_coefficient: float  # ZUCS/R
    base_shear: float  # V, kN
    level_weights: list[float]
    level_forces: list[float]
    level_surface_dead_loads: list[float]
    level_column_weights: list[float]
    level_beam_volumes: list[float]
    level_beam_weights: list[float]
    level_dead_loads: list[float]
    level_live_loads: list[float]
    height_k: float


@dataclass
class IrregularityFacts:
    """Condiciones que requieren inspección geométrica o revisión del proyecto."""

    discontinuity_vertical: bool = False
    extreme_discontinuity_vertical: bool = False
    reentrant_corners: bool = False
    diaphragm_discontinuity: bool = False
    nonparallel_systems: bool = False
    torsional: bool = False
    extreme_torsional: bool = False


def _ratio(numerator: float, denominator: float) -> float | None:
    numerator = float(numerator)
    denominator = float(denominator)
    if numerator < 0 or denominator <= 0:
        return None
    return numerator / denominator


def assess_irregularities(
    levels: list[LevelLoad],
    level_weights: list[float],
    stiffness_x: list[float],
    stiffness_y: list[float],
    strength_x: list[float] | None = None,
    strength_y: list[float] | None = None,
    facts: IrregularityFacts | None = None,
) -> dict[str, object]:
    """Evalúa las Tablas 11 y 12 de la E.030:2026.

    Los niveles se reciben de base a techo. La rigidez puede provenir del
    modelo o de una sobreescritura por nivel. Una resistencia igual a cero se
    interpreta como dato no disponible: el control de piso débil no se inventa
    a partir de la demanda sísmica.
    """

    count = len(levels)
    required = (level_weights, stiffness_x, stiffness_y)
    if count == 0 or any(len(values) != count for values in required):
        raise ValueError("Los datos de irregularidad deben corresponder a todos los niveles.")
    strength_x = list(strength_x or [0.0] * count)
    strength_y = list(strength_y or [0.0] * count)
    if len(strength_x) != count or len(strength_y) != count:
        raise ValueError("Debe existir un valor de resistencia para cada nivel.")
    facts = facts or IrregularityFacts()

    rows: list[dict[str, object]] = []
    flags: dict[str, set[str]] = {
        "soft_story": set(),
        "extreme_soft_story": set(),
        "weak_story": set(),
        "extreme_weak_story": set(),
        "mass": set(),
        "geometric_vertical": set(),
    }
    direction_data = {
        "X": (list(map(float, stiffness_x)), list(map(float, strength_x))),
        "Y": (list(map(float, stiffness_y)), list(map(float, strength_y))),
    }

    for index, level in enumerate(levels):
        row: dict[str, object] = {
            "level": index + 1,
            "label": level.label,
            "kx": float(stiffness_x[index]),
            "ky": float(stiffness_y[index]),
            "weight": float(level_weights[index]),
            "plan_x": float(level.plan_x),
            "plan_y": float(level.plan_y),
        }
        for direction, (stiffnesses, strengths) in direction_data.items():
            adjacent = None
            upper_average = None
            weak_ratio = None
            if index + 1 < count:
                adjacent = _ratio(stiffnesses[index], stiffnesses[index + 1])
                if strengths[index] > 0 and strengths[index + 1] > 0:
                    weak_ratio = _ratio(strengths[index], strengths[index + 1])
            if index + 3 < count:
                upper_values = stiffnesses[index + 1 : index + 4]
                if all(value > 0 for value in upper_values):
                    upper_average = _ratio(stiffnesses[index], sum(upper_values) / 3.0)

            label = f"N{index + 1}/{direction}"
            is_extreme_soft = (
                (adjacent is not None and adjacent < 0.60)
                or (upper_average is not None and upper_average < 0.70)
            )
            is_soft = (
                (adjacent is not None and adjacent < 0.70)
                or (upper_average is not None and upper_average < 0.80)
            )
            if is_soft:
                flags["soft_story"].add(label)
            if is_extreme_soft:
                flags["extreme_soft_story"].add(label)
            if weak_ratio is not None and weak_ratio < 0.80:
                flags["weak_story"].add(label)
            if weak_ratio is not None and weak_ratio < 0.65:
                flags["extreme_weak_story"].add(label)

            key = direction.lower()
            row[f"k_adjacent_{key}"] = adjacent
            row[f"k_average3_{key}"] = upper_average
            row[f"strength_ratio_{key}"] = weak_ratio
        rows.append(row)

    # Masa y geometría: se comparan pisos adyacentes en ambos sentidos. La
    # E.030 excluye expresamente azoteas y sótanos; este modelo no crea sótanos.
    for index, level in enumerate(levels):
        if level.is_roof:
            continue
        for adjacent_index in (index - 1, index + 1):
            if not 0 <= adjacent_index < count or levels[adjacent_index].is_roof:
                continue
            if float(level_weights[index]) > 1.5 * float(level_weights[adjacent_index]):
                flags["mass"].add(f"N{index + 1}")
            for direction, current, adjacent_value in (
                ("X", float(level.plan_x), float(levels[adjacent_index].plan_x)),
                ("Y", float(level.plan_y), float(levels[adjacent_index].plan_y)),
            ):
                if adjacent_value > 0 and current > 1.3 * adjacent_value:
                    flags["geometric_vertical"].add(f"N{index + 1}/{direction}")

    def detail(name: str, fallback: str) -> str:
        affected = sorted(flags.get(name, set()))
        return ", ".join(affected) if affected else fallback

    checks = [
        {"key": "soft_story", "group": "height", "name": "Rigidez - piso blando", "factor": 0.75, "active": bool(flags["soft_story"]), "detail": detail("soft_story", "K ≥ 70% del piso superior y ≥ 80% del promedio de 3 superiores")},
        {"key": "extreme_soft_story", "group": "height", "name": "Rigidez extrema", "factor": 0.50, "active": bool(flags["extreme_soft_story"]), "detail": detail("extreme_soft_story", "K ≥ 60% del piso superior y ≥ 70% del promedio de 3 superiores")},
        {"key": "weak_story", "group": "height", "name": "Resistencia - piso débil", "factor": 0.75, "active": bool(flags["weak_story"]), "detail": detail("weak_story", "Requiere Vn por nivel; 0 = no evaluado")},
        {"key": "extreme_weak_story", "group": "height", "name": "Resistencia extrema", "factor": 0.50, "active": bool(flags["extreme_weak_story"]), "detail": detail("extreme_weak_story", "Requiere Vn por nivel; límite 65%")},
        {"key": "mass", "group": "height", "name": "Masa o peso", "factor": 0.90, "active": bool(flags["mass"]), "detail": detail("mass", "Piso ≤ 1,5 veces cada piso adyacente")},
        {"key": "geometric_vertical", "group": "height", "name": "Geometría vertical", "factor": 0.90, "active": bool(flags["geometric_vertical"]), "detail": detail("geometric_vertical", "Dimensión resistente ≤ 1,3 veces la adyacente")},
        {"key": "discontinuity_vertical", "group": "height", "name": "Discontinuidad vertical", "factor": 0.80, "active": bool(facts.discontinuity_vertical), "detail": "Dato de inspección del sistema resistente"},
        {"key": "extreme_discontinuity_vertical", "group": "height", "name": "Discontinuidad vertical extrema", "factor": 0.60, "active": bool(facts.extreme_discontinuity_vertical), "detail": "Elementos discontinuos resisten más de 25% del cortante"},
        {"key": "torsional", "group": "plan", "name": "Torsional", "factor": 0.75, "active": bool(facts.torsional), "detail": "Δmax/Δprom > 1,3, con excentricidad accidental"},
        {"key": "extreme_torsional", "group": "plan", "name": "Torsional extrema", "factor": 0.60, "active": bool(facts.extreme_torsional), "detail": "Δmax/Δprom > 1,5, con excentricidad accidental"},
        {"key": "reentrant_corners", "group": "plan", "name": "Esquinas entrantes", "factor": 0.90, "active": bool(facts.reentrant_corners), "detail": "Entrantes mayores que 20% en ambas direcciones"},
        {"key": "diaphragm_discontinuity", "group": "plan", "name": "Discontinuidad del diafragma", "factor": 0.85, "active": bool(facts.diaphragm_discontinuity), "detail": "Aberturas > 50% o sección neta resistente < 50%"},
        {"key": "nonparallel_systems", "group": "plan", "name": "Sistemas no paralelos", "factor": 0.90, "active": bool(facts.nonparallel_systems), "detail": "Revisar excepciones de 30° y 10% del cortante"},
    ]
    height_factors = [float(item["factor"]) for item in checks if item["group"] == "height" and item["active"]]
    plan_factors = [float(item["factor"]) for item in checks if item["group"] == "plan" and item["active"]]
    extreme_keys = {"extreme_soft_story", "extreme_weak_story", "extreme_discontinuity_vertical", "extreme_torsional"}
    return {
        "ia": min(height_factors, default=1.0),
        "ip": min(plan_factors, default=1.0),
        "extreme": any(item["active"] and item["key"] in extreme_keys for item in checks),
        "checks": checks,
        "rows": rows,
    }


def irregularity_restriction(
    category: UseCategory,
    zone: str,
    levels: int,
    total_height: float,
    assessment: dict[str, object],
) -> tuple[str, str]:
    """Resume las restricciones de la Tabla 13 de la E.030:2026."""

    irregular = float(assessment["ia"]) < 1.0 or float(assessment["ip"]) < 1.0
    extreme = bool(assessment["extreme"])
    if category in {"A1", "A2"}:
        prohibited = irregular if zone in {"2", "3", "4"} else extreme
        rule = "no se permiten irregularidades" if zone in {"2", "3", "4"} else "no se permiten irregularidades extremas"
    elif category == "B":
        prohibited = extreme and zone in {"2", "3", "4"}
        rule = "no se permiten irregularidades extremas" if zone in {"2", "3", "4"} else "sin restricciones por Tabla 13"
    elif zone in {"3", "4"}:
        prohibited = extreme
        rule = "no se permiten irregularidades extremas"
    elif zone == "2":
        exception = levels <= 2 or total_height <= 8.0
        prohibited = extreme and not exception
        rule = "las extremas sólo se admiten hasta 2 pisos u 8 m de altura"
    else:
        prohibited = False
        rule = "sin restricciones por Tabla 13"
    if prohibited:
        return "not_allowed", f"Configuración no permitida: {rule}."
    if irregular:
        return "review", f"Configuración irregular compatible con esta revisión: {rule}."
    return "ok", f"Configuración regular: {rule}."


def static_seismic_forces(
    levels: list[LevelLoad],
    site: SeismicSiteParams,
    column_weights_kn: list[float] | None = None,
    enforce_minimum_c_over_r: bool = True,
) -> SeismicDirectionResult:
    """Calcula V y la distribución Fi por nivel (E.030, método estático)."""

    if not levels:
        raise ValueError("Se requiere al menos un nivel para el metrado.")
    if column_weights_kn is None:
        column_weights_kn = [0.0] * len(levels)
    if len(column_weights_kn) != len(levels):
        raise ValueError("Debe existir un metrado de columnas para cada nivel.")
    for index, level in enumerate(levels):
        if level.area <= 0 or level.height <= 0:
            raise ValueError(f"El área y la altura del nivel {index + 1} deben ser mayores que cero.")
        numeric_values = (
            level.cm,
            level.cv,
            level.beam_count,
            level.beam_width,
            level.beam_depth,
            level.beam_length,
            level.slab_thickness,
            level.center_x,
            level.center_y,
            level.beam_center_x,
            level.beam_center_y,
            level.plan_x,
            level.plan_y,
            level.stiffness_x_override,
            level.stiffness_y_override,
            level.strength_x,
            level.strength_y,
        )
        numeric_values += tuple(
            float(value)
            for value in (level.beam_volume_override, level.slab_volume_override)
            if value is not None
        )
        if not all(isfinite(float(value)) for value in numeric_values):
            raise ValueError(f"Los datos geométricos del nivel {index + 1} deben ser números válidos.")
        if min(
            level.cm,
            level.cv,
            level.beam_count,
            level.beam_width,
            level.beam_depth,
            level.beam_length,
            level.slab_thickness,
            level.stiffness_x_override,
            level.stiffness_y_override,
            level.strength_x,
            level.strength_y,
        ) < 0:
            raise ValueError(f"Las cargas y dimensiones del nivel {index + 1} no pueden ser negativas.")
        if any(
            float(value) < 0
            for value in (level.beam_volume_override, level.slab_volume_override)
            if value is not None
        ):
            raise ValueError(f"Los volúmenes modelados del nivel {index + 1} no pueden ser negativos.")
        if level.plan_x <= 0 or level.plan_y <= 0:
            raise ValueError(f"Las dimensiones de planta del nivel {index + 1} deben ser mayores que cero.")
        slab_load = level.slab_thickness * CONCRETE_UNIT_WEIGHT
        if level.cm + 1e-9 < slab_load:
            raise ValueError(
                f"En el nivel {index + 1}, CM debe ser al menos {slab_load:.2f} kN/m² "
                "para incluir el peso de la losa ingresada."
            )
    roof_indices = [index for index, level in enumerate(levels) if level.is_roof]
    if len(roof_indices) > 1:
        raise ValueError("Sólo un nivel puede definirse como techo o azotea.")
    if roof_indices and roof_indices[0] != len(levels) - 1:
        raise ValueError("El techo o azotea debe ser el último nivel del modelo.")

    if site.category == "A1":
        if site.zone in {"3", "4"}:
            raise ValueError(
                "La categoría A₁ en zonas 3 y 4 requiere aislamiento sísmico; "
                "ese sistema se diseña con la E.031 y no está incluido en esta página."
            )
        if site.system == "porticos":
            raise ValueError(
                "Para categoría A₁ en zonas 1 y 2, la Tabla 9 no admite pórticos "
                "de concreto como sistema único."
            )
    if site.category == "A2" and site.zone in {"2", "3", "4"} and site.system == "porticos":
        raise ValueError(
            "Para categoría A₂ en zonas 2, 3 y 4, la Tabla 9 no admite pórticos "
            "de concreto como sistema único."
        )

    z = ZONE_FACTORS.get(site.zone, ZONE_FACTORS["2"])
    u = USE_FACTOR_U.get(site.category, 1.0)
    s = soil_factor_s(site.zone, site.soil)
    tp, tl = site_periods(site.soil)
    r0 = BASIC_R.get(site.system, 6.0)
    r = r0 * site.irregularity_height * site.irregularity_plan
    if r <= 0:
        raise ValueError("El coeficiente de reducción R debe ser mayor que cero.")

    cumulative_height = 0.0
    heights: list[float] = []
    for level in levels:
        cumulative_height += level.height
        heights.append(cumulative_height)
    total_height = cumulative_height

    period = site.period_override
    if period is None:
        period = estimate_period(total_height, site.system)
    if period < 0:
        raise ValueError("El período fundamental no puede ser negativo.")

    # Para la fuerza cortante basal estática la E.030:2026 exige C=2,5
    # en todo el intervalo 0 <= T <= TP (artículo 18.3 y artículo 34).
    c = 2.5 if period <= tp else amplification_factor_c(period, tp, tl)
    # C/R no debe ser menor que 0,11 (E.030:2026, artículo 34.2).
    c_effective = max(c, 0.11 * r) if enforce_minimum_c_over_r else c
    coefficient = (z * u * c_effective * s) / r

    breakdowns = [
        level_gravity_breakdown(level, column_weights_kn[index])
        for index, level in enumerate(levels)
    ]
    level_weights = [
        level_seismic_weight(level, site.category, column_weights_kn[index])
        for index, level in enumerate(levels)
    ]
    weight_total = sum(level_weights)
    base_shear = coefficient * weight_total

    k = height_exponent(period)
    weighted = [w * (h ** k) for w, h in zip(level_weights, heights)]
    weighted_total = sum(weighted) or 1.0

    level_forces = [base_shear * (w / weighted_total) for w in weighted]

    return SeismicDirectionResult(
        z=z,
        u=u,
        c=c,
        c_effective=c_effective,
        s=s,
        r=r,
        tp=tp,
        tl=tl,
        period=period,
        weight_total=weight_total,
        base_shear_coefficient=coefficient,
        base_shear=base_shear,
        level_weights=level_weights,
        level_forces=level_forces,
        level_surface_dead_loads=[item["surface_dead"] for item in breakdowns],
        level_column_weights=[item["column_weight"] for item in breakdowns],
        level_beam_volumes=[item["beam_volume"] for item in breakdowns],
        level_beam_weights=[item["beam_weight"] for item in breakdowns],
        level_dead_loads=[item["dead_total"] for item in breakdowns],
        level_live_loads=[item["live_total"] for item in breakdowns],
        height_k=k,
    )

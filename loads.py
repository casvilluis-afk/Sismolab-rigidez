"""Metrado de cargas: peso sísmico por nivel (E.020) y fuerzas sísmicas
estáticas por nivel (E.030 - método estático equivalente).

Módulo sin dependencias del navegador, reutilizable igual que stiffness.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SoilProfile = Literal["S0", "S1", "S2", "S3"]
UseCategory = Literal["A", "B", "C", "D"]
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
    "A": 0.5,
    "B": 0.5,
    "C": 0.25,
    "D": 1.0,
}
ROOF_CV_FACTOR = 0.25  # E.030: azoteas y techos en general, 25% de la S/C.

CATEGORY_LABELS: dict[UseCategory, str] = {
    "A": "A · Edificaciones esenciales",
    "B": "B · Edificaciones importantes",
    "C": "C · Edificaciones comunes",
    "D": "D · Edificaciones menores / depósitos",
}
USE_FACTOR_U: dict[UseCategory, float] = {
    "A": 1.5,
    "B": 1.3,
    "C": 1.0,
    "D": 1.0,
}


def level_seismic_weight(level: LevelLoad, category: UseCategory) -> float:
    """Peso sísmico Pi = (CM + factor*CV) * área, en kN."""

    factor = ROOF_CV_FACTOR if level.is_roof else CATEGORY_CV_FACTOR.get(category, 0.5)
    return (level.cm + factor * level.cv) * level.area


def level_gravity_totals(level: LevelLoad) -> tuple[float, float]:
    """Carga muerta y viva totales del nivel, en kN (sin reducir)."""

    return level.cm * level.area, level.cv * level.area


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

SOIL_FACTORS: dict[str, dict[SoilProfile, float]] = {
    "4": {"S0": 0.80, "S1": 1.00, "S2": 1.05, "S3": 1.10},
    "3": {"S0": 0.80, "S1": 1.00, "S2": 1.15, "S3": 1.20},
    "2": {"S0": 0.80, "S1": 1.00, "S2": 1.20, "S3": 1.40},
    "1": {"S0": 0.80, "S1": 1.00, "S2": 1.60, "S3": 2.00},
}

SOIL_PERIODS: dict[SoilProfile, tuple[float, float]] = {
    "S0": (0.3, 3.0),
    "S1": (0.4, 2.5),
    "S2": (0.6, 2.0),
    "S3": (1.0, 1.6),
}
SOIL_LABELS: dict[SoilProfile, str] = {
    "S0": "S0 · Roca dura",
    "S1": "S1 · Roca o suelo muy rígido",
    "S2": "S2 · Suelo intermedio",
    "S3": "S3 · Suelo blando",
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
    "dual": 45.0,
    "muros": 60.0,
    "albanileria": 60.0,
}


def soil_factor_s(zone: str, soil: SoilProfile) -> float:
    return SOIL_FACTORS.get(zone, SOIL_FACTORS["2"]).get(soil, 1.0)


def site_periods(soil: SoilProfile) -> tuple[float, float]:
    return SOIL_PERIODS.get(soil, SOIL_PERIODS["S1"])


def amplification_factor_c(period: float, tp: float, tl: float) -> float:
    """Factor de amplificación sísmica C (E.030, art. 2.5)."""

    period = max(period, 1e-6)
    if period < tp:
        return 2.5
    if period <= tl:
        return 2.5 * (tp / period)
    return 2.5 * (tp * tl / period ** 2)


def estimate_period(total_height: float, system: StructuralSystem) -> float:
    """Estimación simplificada T = hn / CT (E.030, art. 4.5.4)."""

    ct = BASE_PERIOD_CT.get(system, 45.0)
    return total_height / ct if ct else 0.0


def height_exponent(period: float) -> float:
    """Exponente k para la distribución de fuerzas en altura (E.030, art. 28)."""

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
    height_k: float


def static_seismic_forces(
    levels: list[LevelLoad],
    site: SeismicSiteParams,
) -> SeismicDirectionResult:
    """Calcula V y la distribución Fi por nivel (E.030, método estático)."""

    if not levels:
        raise ValueError("Se requiere al menos un nivel para el metrado.")

    z = ZONE_FACTORS.get(site.zone, ZONE_FACTORS["2"])
    u = USE_FACTOR_U.get(site.category, 1.0)
    s = soil_factor_s(site.zone, site.soil)
    tp, tl = site_periods(site.soil)
    r0 = BASIC_R.get(site.system, 6.0)
    r = max(r0 * site.irregularity_height * site.irregularity_plan, 1.0)

    cumulative_height = 0.0
    heights: list[float] = []
    for level in levels:
        cumulative_height += level.height
        heights.append(cumulative_height)
    total_height = cumulative_height

    period = site.period_override
    if period is None:
        period = estimate_period(total_height, site.system)

    c = amplification_factor_c(period, tp, tl)
    # C/R no debe ser menor que 0,11 (E.030, art. 4.6.2)
    c_effective = max(c, 0.11 * r)
    coefficient = (z * u * c_effective * s) / r

    level_weights = [level_seismic_weight(level, site.category) for level in levels]
    weight_total = sum(level_weights)
    base_shear = coefficient * weight_total

    k = height_exponent(period)
    weighted = [w * (h ** k) for w, h in zip(level_weights, heights)]
    weighted_total = sum(weighted) or 1.0

    top_extra = 0.0
    if period > 0.7:
        top_extra = min(0.07 * period * base_shear, 0.15 * base_shear)

    remaining = base_shear - top_extra
    level_forces = [remaining * (w / weighted_total) for w in weighted]
    level_forces[-1] += top_extra

    return SeismicDirectionResult(
        z=z,
        u=u,
        c=c,
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
        height_k=k,
    )

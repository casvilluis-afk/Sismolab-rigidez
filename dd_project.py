"""Proyecto DD de Ingeniería Resistente (edificio de concreto armado con ala).

Genera, a partir de los datos de la Tabla 1 del enunciado, la geometría de
cada nivel (nudos, pórticos, vigas, losas y aberturas), el metrado por
componentes y la matriz de rigidez lateral de cada pórtico con vigas
flexibles (condensación estática). No depende del navegador.

Convenciones
------------
* Ejes A–E: líneas verticales de la retícula (posición X); se agrega el
  vértice del ala.  Ejes 1–4: líneas horizontales (posición Y), de abajo
  hacia arriba.
* Planta típica (pisos 1 … n−1): retícula A–E × 1–4 y un ala limitada por
  un borde superior inclinado B° desde el nudo A-4 y un borde derecho
  inclinado A° desde el nudo E-1. El vértice del ala es la intersección de
  ambos bordes.
* Planta del techo (piso n): retícula B–E × 1–4, sin ala.
* Aberturas (paños con aspa en las figuras): B–C × 1–2 y C–D × 3–4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, hypot, isfinite, radians, sin, tan

G_ACCEL = 9.80665  # kN por tonf

# Tabla 1: L1, L2, L3, L4, H1, H2 (m) y ángulos A°, B°.
DD_GROUPS: dict[int, dict[str, float]] = {
    1: {"L1": 7.00, "L2": 8.40, "L3": 9.70, "L4": 8.80, "H1": 5.30, "H2": 3.50, "A": 85.20, "B": 7.00},
    2: {"L1": 6.50, "L2": 7.80, "L3": 9.00, "L4": 8.10, "H1": 5.10, "H2": 3.50, "A": 84.20, "B": 6.70},
    3: {"L1": 5.50, "L2": 6.60, "L3": 7.60, "L4": 6.90, "H1": 4.80, "H2": 3.50, "A": 83.80, "B": 4.00},
    4: {"L1": 5.70, "L2": 6.80, "L3": 7.80, "L4": 7.10, "H1": 5.10, "H2": 3.50, "A": 83.70, "B": 5.40},
    5: {"L1": 5.60, "L2": 6.70, "L3": 7.70, "L4": 7.00, "H1": 4.70, "H2": 3.50, "A": 83.60, "B": 4.60},
    6: {"L1": 5.70, "L2": 6.80, "L3": 7.80, "L4": 7.10, "H1": 5.50, "H2": 3.50, "A": 84.60, "B": 6.00},
    7: {"L1": 5.30, "L2": 6.40, "L3": 7.40, "L4": 6.60, "H1": 4.60, "H2": 3.50, "A": 85.70, "B": 6.00},
    8: {"L1": 5.80, "L2": 7.00, "L3": 8.00, "L4": 7.30, "H1": 5.30, "H2": 3.50, "A": 83.80, "B": 6.90},
    9: {"L1": 5.80, "L2": 7.00, "L3": 8.00, "L4": 7.30, "H1": 5.10, "H2": 3.50, "A": 85.20, "B": 4.10},
    10: {"L1": 6.70, "L2": 8.00, "L3": 9.20, "L4": 8.40, "H1": 4.60, "H2": 3.50, "A": 85.50, "B": 4.70},
}

# Ubicación y suelo (Tabla 1). La zona sale del Anexo II de la E.030; las
# marcadas como no confirmadas deben verificarse en el listado oficial.
DD_SITES: dict[int, dict[str, object]] = {
    1: {"soil": "S1", "region": "Ica", "province": "Ica", "district": "Ocucaje", "zone": "4", "confirmed": True},
    2: {"soil": "S2", "region": "Lima", "province": "Lima", "district": "Miraflores", "zone": "4", "confirmed": True},
    3: {"soil": "S2", "region": "San Martín", "province": "Lamas", "district": "Lamas", "zone": "3", "confirmed": False},
    4: {"soil": "S1", "region": "La Libertad", "province": "Otuzco", "district": "Otuzco", "zone": "3", "confirmed": False},
    5: {"soil": "S2", "region": "Moquegua", "province": "Mariscal Nieto", "district": "Moquegua", "zone": "4", "confirmed": True},
    6: {"soil": "S0", "region": "Tacna", "province": "Jorge Basadre", "district": "Locumba", "zone": "4", "confirmed": True},
    7: {"soil": "S3", "region": "Ayacucho", "province": "Cangallo", "district": "Cangallo", "zone": "3", "confirmed": False},
    8: {"soil": "S2", "region": "Cusco", "province": "Espinar", "district": "Espinar", "zone": "2", "confirmed": False},
    9: {"soil": "S3", "region": "Pasco", "province": "Daniel A. Carrión", "district": "Chacayán", "zone": "2", "confirmed": False},
    10: {"soil": "S1", "region": "Piura", "province": "Piura", "district": "Piura", "zone": "4", "confirmed": True},
}

# Usos: sobrecarga típica E.020 (kN/m²) y categoría E.030:2026 (Tabla N° 7).
DD_USES: dict[str, dict[str, object]] = {
    "hotel": {"label": "Hotel", "cv": 2.0, "category": "C", "note": "E.020: cuartos 2,0 kPa; corredores y escaleras 4,0 kPa"},
    "oficina": {"label": "Oficinas", "cv": 2.5, "category": "C", "note": "E.020: oficinas 2,5 kPa"},
    "vivienda": {"label": "Vivienda", "cv": 2.0, "category": "C", "note": "E.020: vivienda 2,0 kPa"},
    "educacion": {"label": "Centro educativo", "cv": 2.5, "category": "A2", "note": "E.020: aulas 2,5 kPa; E.030: instituciones educativas, categoría A2"},
    "comercio": {"label": "Centro comercial", "cv": 5.0, "category": "B", "note": "E.020: tiendas 5,0 kPa; E.030: centros comerciales, categoría B"},
    "biblioteca": {"label": "Biblioteca", "cv": 3.0, "category": "B", "note": "E.020: salas de lectura 3,0 kPa; E.030: bibliotecas, categoría B"},
}
ROOF_LIVE_LOAD = 1.0  # kN/m², azotea no transitable (E.020)

AXIS_LETTERS = "ABCDE"


@dataclass
class DDParams:
    group: int = 1
    levels: int = 3
    L1: float = 7.00
    L2: float = 8.40
    L3: float = 9.70
    L4: float = 8.80
    H1: float = 5.30
    H2: float = 3.50
    A: float = 85.20
    B: float = 7.00
    column_bx: float = 0.40  # m, dimensión de la columna en X
    column_by: float = 0.40  # m, dimensión de la columna en Y
    beam_b: float = 0.30
    beam_h: float = 0.50
    slab_floor: float = 0.25
    slab_roof: float = 0.20
    E_tcm2: float = 210.0  # t/cm²
    gamma_tm3: float = 2.40  # t/m³
    finishes: float = 1.0  # kN/m², acabados
    partitions: float = 1.0  # kN/m², tabiquería (no en el techo)
    use: str = "hotel"

    @classmethod
    def from_group(cls, group: int, **overrides) -> "DDParams":
        data = DD_GROUPS[int(group)]
        return cls(group=int(group), **{**data, **overrides})

    @property
    def E_kn_m2(self) -> float:
        return self.E_tcm2 * 1.0e4 * G_ACCEL

    @property
    def gamma_kn_m3(self) -> float:
        return self.gamma_tm3 * G_ACCEL

    def heights(self) -> list[float]:
        return [self.H1] + [self.H2] * (self.levels - 1)


@dataclass
class Frame:
    id: str
    label: str
    beta: float  # grados, orientación antihoraria desde X
    x0: float
    y0: float
    kind: str  # "X", "Y" o "inclinado"
    stations: list[list[tuple[str, float]]] = field(default_factory=list)  # por nivel: (nudo, s)

    @property
    def direction(self) -> str:
        b = abs(((self.beta + 90.0) % 180.0) - 90.0)
        return "X" if b < 45.0 else "Y"


@dataclass
class LevelGeometry:
    index: int
    is_roof: bool
    nodes: dict[str, tuple[float, float]]
    beams: list[tuple[str, str, str]]  # (nudo a, nudo b, pórtico)
    outline: list[tuple[float, float]]
    openings: list[list[tuple[float, float]]]


@dataclass
class DDBuilding:
    params: DDParams
    xs: list[float]
    ys: list[float]
    peak: tuple[float, float]
    levels: list[LevelGeometry]
    frames: list[Frame]


def _positive(value: float, name: str) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} debe ser mayor que cero.")
    return value


def validate(params: DDParams) -> None:
    for name in ("L1", "L2", "L3", "L4", "H1", "H2", "column_bx", "column_by", "beam_b", "beam_h", "slab_floor", "slab_roof", "E_tcm2", "gamma_tm3"):
        _positive(getattr(params, name), name)
    if not 1 <= int(params.levels) <= 12:
        raise ValueError("El edificio admite entre 1 y 12 niveles.")
    if not 45.0 < float(params.A) < 135.0:
        raise ValueError("El ángulo A debe estar entre 45° y 135°.")
    if not -45.0 < float(params.B) < 45.0:
        raise ValueError("El ángulo B debe estar entre −45° y 45°.")
    if params.beam_h <= params.slab_floor:
        raise ValueError("El peralte de la viga debe superar el espesor de la losa.")
    if params.finishes < 0 or params.partitions < 0:
        raise ValueError("Acabados y tabiquería no pueden ser negativos.")


def _polygon_area_centroid(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    area2 = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    area = area2 / 2.0
    if abs(area) < 1e-12:
        return 0.0, 0.0, 0.0
    return abs(area), cx / (3.0 * area2), cy / (3.0 * area2)


def build_building(params: DDParams) -> DDBuilding:
    validate(params)
    p = params
    xs = [0.0, p.L1, p.L1 + p.L2, p.L1 + 2 * p.L2, 2 * p.L1 + 2 * p.L2]
    ys = [0.0, p.L3, p.L3 + p.L4, 2 * p.L3 + p.L4]
    tb, ta = radians(p.B), radians(p.A)
    xE, y4 = xs[-1], ys[-1]
    cot_a = cos(ta) / sin(ta)

    def top_y(x: float) -> float:
        return y4 + x * tan(tb)

    def right_x(y: float) -> float:
        return xE + y * cot_a

    # Vértice: y = y4 + x·tanB  y  x = xE + y·cotA
    denominator = 1.0 - tan(tb) * cot_a
    if abs(denominator) < 1e-9:
        raise ValueError("Los bordes del ala son paralelos; revisa los ángulos A y B.")
    peak_y = (y4 + xE * tan(tb)) / denominator
    peak = (right_x(peak_y), peak_y)
    if peak[0] <= xE or peak[1] <= y4:
        raise ValueError("Los ángulos A y B no forman un ala hacia afuera de la retícula.")

    typical_nodes: dict[str, tuple[float, float]] = {}
    for i, letter in enumerate(AXIS_LETTERS):
        for j in range(4):
            typical_nodes[f"{letter}{j + 1}"] = (xs[i], ys[j])
    for i, letter in enumerate(AXIS_LETTERS[1:], start=1):
        typical_nodes[f"{letter}s"] = (xs[i], top_y(xs[i]))
    for j in range(1, 4):
        typical_nodes[f"d{j + 1}"] = (right_x(ys[j]), ys[j])
    typical_nodes["V"] = peak

    roof_nodes = {
        key: value for key, value in typical_nodes.items()
        if len(key) == 2 and key[0] in "BCDE" and key[1] in "1234"
    }

    # Pórticos: por nivel, la lista ordenada de nudos sobre su línea.
    frames: list[Frame] = []
    for i, letter in enumerate(AXIS_LETTERS):
        typical = [f"{letter}{j + 1}" for j in range(4)] + ([f"{letter}s"] if letter != "A" else [])
        roof = [f"{letter}{j + 1}" for j in range(4)] if letter != "A" else []
        frames.append(Frame(f"eje-{letter}", f"Eje {letter}", 90.0, xs[i], ys[0], "Y", [typical, roof]))
    for j in range(4):
        line = str(j + 1)
        typical = [f"{letter}{line}" for letter in AXIS_LETTERS] + ([f"d{line}"] if j > 0 else [])
        roof = [f"{letter}{line}" for letter in "BCDE"]
        frames.append(Frame(f"eje-{line}", f"Eje {line}", 0.0, xs[0], ys[j], "X", [typical, roof]))
    top = ["A4"] + [f"{letter}s" for letter in "BCDE"] + ["V"]
    frames.append(Frame("eje-sup", "Ala superior", p.B, xs[0], y4, "inclinado", [top, []]))
    right = ["E1", "d2", "d3", "d4", "V"]
    frames.append(Frame("eje-der", "Ala derecha", p.A, xE, ys[0], "inclinado", [right, []]))

    levels: list[LevelGeometry] = []
    for index in range(p.levels):
        is_roof = index == p.levels - 1 and p.levels > 1
        nodes = roof_nodes if is_roof else typical_nodes
        beams = []
        for frame in frames:
            ids = frame.stations[1] if is_roof else frame.stations[0]
            for a, b in zip(ids, ids[1:]):
                beams.append((a, b, frame.id))
        if is_roof:
            outline = [(xs[1], ys[0]), (xs[4], ys[0]), (xs[4], ys[3]), (xs[1], ys[3])]
        else:
            outline = [(xs[0], ys[0]), (xE, ys[0]), peak, (xs[0], y4)]
        openings = [
            [(xs[1], ys[0]), (xs[2], ys[0]), (xs[2], ys[1]), (xs[1], ys[1])],
            [(xs[2], ys[2]), (xs[3], ys[2]), (xs[3], ys[3]), (xs[2], ys[3])],
        ]
        levels.append(LevelGeometry(index, is_roof, dict(nodes), beams, outline, openings))

    # Estaciones (s) de cada pórtico medidas desde su origen sobre la línea.
    for frame in frames:
        ux, uy = cos(radians(frame.beta)), sin(radians(frame.beta))
        resolved = []
        for index in range(p.levels):
            ids = frame.stations[1] if levels[index].is_roof else frame.stations[0]
            resolved.append([
                (node, (typical_nodes[node][0] - frame.x0) * ux + (typical_nodes[node][1] - frame.y0) * uy)
                for node in ids
            ])
        frame.stations = resolved

    return DDBuilding(p, xs, ys, peak, levels, frames)


# ---------------------------------------------------------------------------
# Metrado por nivel
# ---------------------------------------------------------------------------

def level_takeoff(building: DDBuilding, index: int) -> dict[str, object]:
    """Cantidades y centro de masa de los componentes de un nivel (kN, m)."""

    p = building.params
    level = building.levels[index]
    heights = p.heights()
    gamma = p.gamma_kn_m3
    slab_e = p.slab_roof if level.is_roof else p.slab_floor

    gross_area, gx, gy = _polygon_area_centroid(level.outline)
    open_area = open_mx = open_my = 0.0
    for polygon in level.openings:
        a, cx, cy = _polygon_area_centroid(polygon)
        open_area += a
        open_mx += a * cx
        open_my += a * cy
    area = gross_area - open_area
    slab_cx = (gross_area * gx - open_mx) / area
    slab_cy = (gross_area * gy - open_my) / area

    # Columnas: mitad del entrepiso inferior y mitad del superior.
    below = heights[index]
    above = heights[index + 1] if index + 1 < len(heights) else 0.0
    columns_here = list(level.nodes)
    column_heights = {}
    upper_nodes = building.levels[index + 1].nodes if index + 1 < len(building.levels) else {}
    for node in columns_here:
        column_heights[node] = below / 2.0 + (above / 2.0 if node in upper_nodes else 0.0)
    section = p.column_bx * p.column_by
    column_volume = sum(section * h for h in column_heights.values())
    column_weight = column_volume * gamma
    if column_volume > 0:
        col_cx = sum(level.nodes[n][0] * column_heights[n] for n in columns_here) / sum(column_heights.values())
        col_cy = sum(level.nodes[n][1] * column_heights[n] for n in columns_here) / sum(column_heights.values())
    else:
        col_cx = col_cy = 0.0

    # Vigas: parte descolgada b·(h − e) para no duplicar el peso de la losa.
    beam_length = beam_mx = beam_my = 0.0
    for a, b, _frame in level.beams:
        (x1, y1), (x2, y2) = level.nodes[a], level.nodes[b]
        length = hypot(x2 - x1, y2 - y1)
        beam_length += length
        beam_mx += length * (x1 + x2) / 2.0
        beam_my += length * (y1 + y2) / 2.0
    beam_volume = p.beam_b * (p.beam_h - slab_e) * beam_length
    beam_cx = beam_mx / beam_length if beam_length else slab_cx
    beam_cy = beam_my / beam_length if beam_length else slab_cy

    xs_nodes = [xy[0] for xy in level.nodes.values()]
    ys_nodes = [xy[1] for xy in level.nodes.values()]
    return {
        "area": area,
        "gross_area": gross_area,
        "opening_area": open_area,
        "slab_thickness": slab_e,
        "slab_volume": area * slab_e,
        "slab_center": (slab_cx, slab_cy),
        "column_count": len(columns_here),
        "column_heights": column_heights,
        "column_volume": column_volume,
        "column_weight": column_weight,
        "column_center": (col_cx, col_cy),
        "beam_count": len(level.beams),
        "beam_length": beam_length,
        "beam_volume": beam_volume,
        "beam_center": (beam_cx, beam_cy),
        "finishes": p.finishes,
        "partitions": 0.0 if level.is_roof else p.partitions,
        "cm_surface": slab_e * gamma + p.finishes + (0.0 if level.is_roof else p.partitions),
        "cv": ROOF_LIVE_LOAD if level.is_roof else float(DD_USES.get(p.use, DD_USES["hotel"])["cv"]),
        "plan_x": max(xs_nodes) - min(xs_nodes),
        "plan_y": max(ys_nodes) - min(ys_nodes),
    }


# ---------------------------------------------------------------------------
# Matriz lateral de un pórtico con vigas flexibles
# ---------------------------------------------------------------------------

def _solve(matrix: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    """Resuelve A·X = B por Gauss-Jordan (B con varias columnas)."""
    n = len(matrix)
    m = len(rhs[0]) if rhs else 0
    aug = [list(map(float, matrix[i])) + list(map(float, rhs[i])) for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-14:
            raise ValueError("El pórtico es inestable (matriz de giros singular).")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        aug[col] = [v / pv for v in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0.0:
                f = aug[r][col]
                aug[r] = [a - f * b for a, b in zip(aug[r], aug[col])]
    return [row[n:n + m] for row in aug]


def frame_lateral_matrix(
    frame: Frame,
    heights: list[float],
    E: float,
    column_inertia: float,
    beam_inertia: float,
) -> dict[str, object]:
    """Condensa la matriz de un pórtico plano a sus desplazamientos de piso.

    Hipótesis: columnas y vigas con deformación por flexión, sin deformación
    axial (vigas inextensibles y columnas sin acortamiento), base empotrada.
    GDL: un desplazamiento lateral por nivel y un giro por nudo.
    Devuelve K_L = Kuu − Kuθ·Kθθ⁻¹·Kθu (kN/m si E en kN/m²).
    """

    n = len(heights)
    rotation_dofs: dict[tuple[int, str], int] = {}
    for level in range(n):
        for node, _s in frame.stations[level]:
            rotation_dofs[(level, node)] = n + len(rotation_dofs)
    size = n + len(rotation_dofs)
    K = [[0.0] * size for _ in range(size)]

    def add(dofs: list[int | None], k: list[list[float]]) -> None:
        for a, da in enumerate(dofs):
            if da is None:
                continue
            for b, db in enumerate(dofs):
                if db is None:
                    continue
                K[da][db] += k[a][b]

    columns_per_story = []
    for level in range(n):
        h = heights[level]
        EI = E * column_inertia
        k = [
            [12 * EI / h**3, 6 * EI / h**2, -12 * EI / h**3, 6 * EI / h**2],
            [6 * EI / h**2, 4 * EI / h, -6 * EI / h**2, 2 * EI / h],
            [-12 * EI / h**3, -6 * EI / h**2, 12 * EI / h**3, -6 * EI / h**2],
            [6 * EI / h**2, 2 * EI / h, -6 * EI / h**2, 4 * EI / h],
        ]
        nodes_here = [node for node, _s in frame.stations[level]]
        columns_per_story.append(len(nodes_here))
        for node in nodes_here:
            u_bottom = level - 1 if level > 0 else None
            th_bottom = rotation_dofs.get((level - 1, node)) if level > 0 else None
            if level > 0 and th_bottom is None:
                raise ValueError(f"La columna {node} del nivel {level + 1} no tiene apoyo en el nivel inferior.")
            add([u_bottom, th_bottom, level, rotation_dofs[(level, node)]], k)
        stations = frame.stations[level]
        for (na, sa), (nb, sb) in zip(stations, stations[1:]):
            L = abs(sb - sa)
            if L <= 1e-9:
                continue
            EIb = E * beam_inertia
            kb = [[4 * EIb / L, 2 * EIb / L], [2 * EIb / L, 4 * EIb / L]]
            add([rotation_dofs[(level, na)], rotation_dofs[(level, nb)]], kb)

    if not rotation_dofs:
        return {"matrix": [[0.0] * n for _ in range(n)], "columns": columns_per_story, "dofs": 0}

    r = list(range(n, size))
    Kuu = [[K[i][j] for j in range(n)] for i in range(n)]
    Kut = [[K[i][j] for j in r] for i in range(n)]
    Ktu = [[K[i][j] for j in range(n)] for i in r]
    Ktt = [[K[i][j] for j in r] for i in r]
    X = _solve(Ktt, Ktu)  # Kθθ⁻¹·Kθu
    KL = [
        [Kuu[i][j] - sum(Kut[i][k] * X[k][j] for k in range(len(r))) for j in range(n)]
        for i in range(n)
    ]
    for i in range(n):
        for j in range(i + 1, n):
            avg = 0.5 * (KL[i][j] + KL[j][i])
            KL[i][j] = KL[j][i] = avg
    return {"matrix": KL, "columns": columns_per_story, "dofs": size}


def equivalent_story_stiffness(matrix: list[list[float]]) -> list[float]:
    """Rigidez de entrepiso equivalente: V_i / Δ_i con una fuerza unitaria por nivel."""
    n = len(matrix)
    active = [i for i in range(n) if abs(matrix[i][i]) > 1e-9]
    if not active:
        return [0.0] * n
    sub = [[matrix[i][j] for j in active] for i in active]
    disp_active = [row[0] for row in _solve(sub, [[1.0] for _ in active])]
    disp = [0.0] * n
    for k, i in enumerate(active):
        disp[i] = disp_active[k]
    result = []
    for i in range(n):
        if i not in active:
            result.append(0.0)
            continue
        shear = float(sum(1 for j in active if j >= i))
        previous = disp[i - 1] if i > 0 else 0.0
        drift = disp[i] - previous
        result.append(shear / drift if abs(drift) > 1e-15 else 0.0)
    return result


def column_inertia_for(params: DDParams, beta_degrees: float) -> float:
    """Inercia de la columna para desplazamiento en la dirección β."""
    bx, by = params.column_bx, params.column_by
    i_disp_x = by * bx**3 / 12.0  # flexión con desplazamiento en X
    i_disp_y = bx * by**3 / 12.0
    c, s = cos(radians(beta_degrees)), sin(radians(beta_degrees))
    return i_disp_x * c * c + i_disp_y * s * s


def frame_matrices(building: DDBuilding) -> list[dict[str, object]]:
    p = building.params
    heights = p.heights()
    beam_inertia = p.beam_b * p.beam_h**3 / 12.0
    results = []
    for frame in building.frames:
        data = frame_lateral_matrix(frame, heights, p.E_kn_m2, column_inertia_for(p, frame.beta), beam_inertia)
        data["frame"] = frame
        data["story_stiffness"] = equivalent_story_stiffness(data["matrix"])
        results.append(data)
    return results

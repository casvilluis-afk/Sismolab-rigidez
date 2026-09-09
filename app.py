"""Interfaz web de SismoLab ejecutada por Python en el navegador."""

from __future__ import annotations

from html import escape
from math import cos, isfinite, pi, radians, sin

from pyscript import document, when

from stiffness import (
    ColumnGroup,
    KN_PER_TONF,
    STEEL_MODULUS_MKS,
    STEEL_MODULUS_SI,
    boundary_description,
    boundary_factor,
    analyze_pseudotridimensional,
    assess_torsional_irregularity,
    calculate_group,
    calculate_story,
    convert_group_units,
    direction_label,
    material_label,
    resistance_bounds,
    resistance_label,
    _matmul,
    _transpose,
)
from loads import (
    CATEGORY_CV_FACTOR,
    CONCRETE_UNIT_WEIGHT,
    GRAVITY_ACCELERATION,
    LIVE_LOAD_PRESETS,
    ROOF_CV_FACTOR,
    IrregularityFacts,
    LevelLoad,
    SeismicSiteParams,
    assess_irregularities,
    beam_takeoff,
    combine_mass_properties,
    component_mass_properties,
    level_gravity_breakdown,
    level_seismic_weight,
    irregularity_restriction,
    live_load_preset,
    static_seismic_forces,
)


units = "SI"
story_height = 3.0
next_group_number = 2
current_stage = "rigidity"
analysis_level_count = 2
analysis_heights = [3.0, 3.0]
analysis_forces = [100.0, 200.0]
analysis_stiffness_x = [0.0, 0.0]
analysis_stiffness_y = [0.0, 0.0]
analysis_alpha = 0.0
analysis_cm_x = 2.5
analysis_cm_y = 2.0
analysis_ecc_x = 0.0
analysis_ecc_y = 0.0
analysis_view_level = None
analysis_selected_axis_id = None
groups = [
    ColumnGroup(
        id="c1",
        quantity=2,
        shape="square",
        dimension=300.0,
        fc=21.0,
        base="fixed",
        top="fixed",
        material="concrete",
        direction="X",
        axis="1",
        x0=0.0,
        y0=0.0,
        beta=0.0,
    )
]

next_load_level_number = 3
load_levels = [
    LevelLoad(id="lv1", label="Nivel 1", area=200.0, cm=6.5, cv=2.0, height=3.0, is_roof=False, use_key="vivienda"),
    LevelLoad(id="lv2", label="Azotea", area=200.0, cm=5.0, cv=1.0, height=3.0, is_roof=True, use_key="azotea_no_transitable"),
]
loads_use_preset = "vivienda"
loads_zone = "3"
loads_soil = "S2"
loads_category = "C"
loads_system = "muros"
loads_ia = 1.0
loads_ip = 1.0
loads_discontinuity_vertical = False
loads_extreme_discontinuity_vertical = False
loads_reentrant_corners = False
loads_diaphragm_discontinuity = False
loads_nonparallel_systems = False
loads_period_mode = "auto"
loads_period_manual = 0.30


def by_id(element_id: str):
    return document.getElementById(element_id)


def format_number(value: float, digits: int = 2) -> str:
    number = float(value)
    if not isfinite(number):
        return "—"
    if abs(number) < 0.5 * 10 ** (-digits):
        number = 0.0
    rendered = f"{number:,.{digits}f}"
    if digits:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered.replace(",", "§").replace(".", ",").replace("§", ".")


def input_number(value: float, digits: int = 6) -> str:
    rendered = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return rendered or "0"


def parse_number(value, fallback: float = 0.0) -> float:
    try:
        number = float(str(value).replace(",", "."))
        return number if isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def get_group(group_id: str) -> ColumnGroup | None:
    return next((group for group in groups if group.id == group_id), None)


def get_load_level(level_id: str) -> LevelLoad | None:
    return next((level for level in load_levels if level.id == level_id), None)


def column_takeoff(story_height_m: float) -> dict[str, float | int]:
    """Metrado de las columnas definidas en Rigidez para un entrepiso."""

    rows = column_takeoff_rows(story_height_m)
    return {
        "count": sum(int(row["quantity"]) for row in rows),
        "volume": sum(float(row["volume"]) for row in rows),
        "weight": sum(float(row["weight"]) for row in rows),
    }


def column_takeoff_rows(story_height_m: float) -> list[dict[str, object]]:
    """Desglose de columnas por grupo, incluyendo masa y centroide en planta."""

    rows: list[dict[str, object]] = []
    for index, group in enumerate(groups):
        dimension_m = group.dimension / (1_000.0 if units == "SI" else 100.0)
        section_area = (
            dimension_m**2
            if group.shape == "square"
            else pi * dimension_m**2 / 4.0
        )
        quantity = max(0, int(group.quantity))
        volume = quantity * section_area * max(0.0, story_height_m)
        unit_weight = 24.0 if group.material == "concrete" else 78.5
        weight = volume * unit_weight
        mass = component_mass_properties(weight, group.x0, group.y0)
        rows.append(
            {
                "number": index + 1,
                "description": f"C{index + 1} · Eje {group.axis}",
                "quantity": quantity,
                "shape": shape_name(group.shape),
                "dimension": dimension_m,
                "height": max(0.0, story_height_m),
                "unit_weight": unit_weight,
                "volume": volume,
                "weight": weight,
                **mass,
            }
        )
    return rows


def column_takeoffs_for_levels() -> list[dict[str, float | int]]:
    return [column_takeoff(level.height) for level in load_levels]


def _derived_story_stiffnesses() -> tuple[list[float], list[float]]:
    """Rigideces Kx,Ky por nivel, siempre expresadas en kN/m."""

    stiffness_x: list[float] = []
    stiffness_y: list[float] = []
    for level in load_levels:
        story = calculate_story(groups, level.height, units)
        conversion = KN_PER_TONF if units == "MKS" else 1.0
        derived_x = float(story["totals"]["X"]) * conversion
        derived_y = float(story["totals"]["Y"]) * conversion
        stiffness_x.append(
            float(level.stiffness_x_override) if level.stiffness_x_override > 0 else derived_x
        )
        stiffness_y.append(
            float(level.stiffness_y_override) if level.stiffness_y_override > 0 else derived_y
        )
    return stiffness_x, stiffness_y


def _level_seismic_mass_properties(
    level: LevelLoad,
    column_rows: list[dict[str, object]],
    category: str,
) -> dict[str, float]:
    """Centro de masa coherente con el peso sísmico usado en el metrado."""

    column_weight = sum(float(row["weight"]) for row in column_rows)
    breakdown = level_gravity_breakdown(level, column_weight)
    live_factor = ROOF_CV_FACTOR if level.is_roof else CATEGORY_CV_FACTOR.get(category, 0.25)
    components = [dict(row) for row in column_rows]
    components.extend(
        (
            component_mass_properties(
                breakdown["beam_weight"], level.beam_center_x, level.beam_center_y
            ),
            component_mass_properties(breakdown["slab_weight"], level.center_x, level.center_y),
            component_mass_properties(
                breakdown["other_surface_dead"], level.center_x, level.center_y
            ),
            component_mass_properties(
                breakdown["live_total"], level.center_x, level.center_y, live_factor
            ),
        )
    )
    return combine_mass_properties(components)


def shape_name(shape: str) -> str:
    return "cuadrada" if shape == "square" else "circular"


def support_name(joint: str, position: str) -> str:
    if position == "base":
        return "Base empotrada" if joint == "fixed" else "Base articulada"
    return "rígida" if joint == "fixed" else "articulada"


def unit_labels() -> dict[str, str]:
    if units == "SI":
        return {
            "dimension": "mm",
            "fc": "MPa",
            "stiffness": "kN/m",
            "length": "mm",
            "inertia": "mm⁴",
        }
    return {
        "dimension": "cm",
        "fc": "kgf/cm²",
        "stiffness": "tonf/m",
        "length": "cm",
        "inertia": "cm⁴",
    }


def group_card(group: ColumnGroup, index: int) -> str:
    labels = unit_labels()
    can_remove = len(groups) > 1
    factor = boundary_factor(group.base, group.top)
    factor_text = "0" if factor == 0 else f"{int(factor)}EI / h³"
    dimension_label = "Lado a" if group.shape == "square" else "Diámetro D"
    dimension_min = "100" if units == "SI" else "10"
    dimension_max = "2000" if units == "SI" else "200"
    dimension_step = "10" if units == "SI" else "1"
    remove_button = (
        f'<button type="button" class="button remove-button" data-action="remove" data-id="{group.id}" '
        f'aria-label="Eliminar grupo C{index + 1}">×</button>'
        if can_remove
        else ""
    )
    square_selected = " is-selected" if group.shape == "square" else ""
    circle_selected = " is-selected" if group.shape == "circle" else ""
    base_fixed = " selected" if group.base == "fixed" else ""
    base_pinned = " selected" if group.base == "pinned" else ""
    top_fixed = " selected" if group.top == "fixed" else ""
    top_pinned = " selected" if group.top == "pinned" else ""

    concrete_selected = " is-selected" if group.material == "concrete" else ""
    steel_selected = " is-selected" if group.material == "steel" else ""
    dir_x_selected = " is-selected" if group.direction == "X" else ""
    dir_y_selected = " is-selected" if group.direction == "Y" else ""
    axis_value = escape(str(group.axis), quote=True)

    material_options = f"""
      <fieldset class="field-block shape-field">
        <legend>Material</legend>
        <div class="shape-options">
          <button type="button" class="shape-option{concrete_selected}" data-action="material" data-id="{group.id}" data-value="concrete">Concreto armado</button>
          <button type="button" class="shape-option{steel_selected}" data-action="material" data-id="{group.id}" data-value="steel">Acero estructural</button>
        </div>
      </fieldset>
      <fieldset class="field-block shape-field">
        <legend>Dirección del sismo</legend>
        <div class="shape-options">
          <button type="button" class="shape-option{dir_x_selected}" data-action="direction" data-id="{group.id}" data-value="X">Eje X</button>
          <button type="button" class="shape-option{dir_y_selected}" data-action="direction" data-id="{group.id}" data-value="Y">Eje Y</button>
        </div>
      </fieldset>
    """

    if group.material == "steel":
        steel_modulus = STEEL_MODULUS_SI if units == "SI" else STEEL_MODULUS_MKS
        resistance_field = f"""
        <div class="field-block">
          <label>Módulo elástico E</label>
          <div class="input-with-unit"><input type="text" value="{format_number(steel_modulus, 0)}" disabled /><span>{labels['fc']}</span></div>
          <small>Constante para acero estructural: no depende de una resistencia ingresada.</small>
        </div>
        """
    else:
        resistance_name = resistance_label(group.material)
        fc_min, fc_max, fc_step = resistance_bounds(group.material, units)
        resistance_field = f"""
        <div class="field-block">
          <label for="fc-{group.id}">Resistencia {resistance_name}</label>
          <div class="input-with-unit"><input id="fc-{group.id}" type="number" min="{fc_min}" max="{fc_max}" step="{fc_step}" value="{input_number(group.fc)}" data-group="{group.id}" data-field="fc" /><span>{labels['fc']}</span></div>
        </div>
        """

    return f"""
    <article class="column-card" data-card-id="{group.id}">
      <div class="column-card__head">
        <div><span class="column-code">C{index + 1}</span><div><h3>Grupo de columnas {index + 1}</h3><p>{material_label(group.material)} · {direction_label(group.direction)}</p></div></div>
        {remove_button}
      </div>
      <div class="form-grid form-grid--compact">
        <div class="field-block">
          <label for="quantity-{group.id}">Cantidad</label>
          <div class="input-with-unit"><input id="quantity-{group.id}" type="number" min="1" max="100" step="1" value="{group.quantity}" data-group="{group.id}" data-field="quantity" /><span>unid.</span></div>
        </div>
        <fieldset class="field-block shape-field">
          <legend>Sección</legend>
          <div class="shape-options">
            <button type="button" class="shape-option{square_selected}" data-action="shape" data-id="{group.id}" data-value="square"><span class="shape-symbol"></span>Cuadrada</button>
            <button type="button" class="shape-option{circle_selected}" data-action="shape" data-id="{group.id}" data-value="circle"><span class="shape-symbol circle"></span>Circular</button>
          </div>
        </fieldset>
      </div>
      {material_options}
      <div class="axis-location-card">
        <div class="axis-location-icon" aria-hidden="true">⌗</div>
        <div class="field-block">
          <label for="axis-{group.id}">Eje estructural</label>
          <div class="axis-input-row">
            <span>EJE</span>
            <input id="axis-{group.id}" type="text" maxlength="12" value="{axis_value}" placeholder="1, 2, A…" data-group="{group.id}" data-field="axis" />
          </div>
          <div class="axis-coordinate-grid">
            <div><label for="grid-x-{group.id}">Centro X₀</label><div class="input-with-unit"><input id="grid-x-{group.id}" type="number" step="0.1" value="{input_number(group.x0)}" data-group="{group.id}" data-field="analysis-frame-x" /><span>m</span></div></div>
            <div><label for="grid-y-{group.id}">Centro Y₀</label><div class="input-with-unit"><input id="grid-y-{group.id}" type="number" step="0.1" value="{input_number(group.y0)}" data-group="{group.id}" data-field="analysis-frame-y" /><span>m</span></div></div>
          </div>
          <small>X₀,Y₀ representan el centro del grupo y se reutilizan en el metrado de masa y en el análisis.</small>
        </div>
      </div>
      <div class="form-grid">
        <div class="field-block">
          <label for="dimension-{group.id}">{dimension_label}</label>
          <div class="input-with-unit"><input id="dimension-{group.id}" type="number" min="{dimension_min}" max="{dimension_max}" step="{dimension_step}" value="{input_number(group.dimension)}" data-group="{group.id}" data-field="dimension" /><span>{labels['dimension']}</span></div>
        </div>
        {resistance_field}
      </div>
      <div class="form-grid">
        <div class="field-block">
          <label for="base-{group.id}">Apoyo en la base</label>
          <select id="base-{group.id}" data-group="{group.id}" data-field="base"><option value="fixed"{base_fixed}>Empotrado</option><option value="pinned"{base_pinned}>Articulado</option></select>
        </div>
        <div class="field-block">
          <label for="top-{group.id}">Unión superior</label>
          <select id="top-{group.id}" data-group="{group.id}" data-field="top"><option value="fixed"{top_fixed}>Rígida</option><option value="pinned"{top_pinned}>Articulada</option></select>
        </div>
      </div>
      <div class="case-note"><b>Σ</b><div><strong>k = {factor_text}</strong><span>{escape(boundary_description(group.base, group.top))}</span></div></div>
    </article>
    """


def render_groups() -> None:
    by_id("group-list").innerHTML = "".join(group_card(group, index) for index, group in enumerate(groups))
    by_id("group-count").textContent = f"{len(groups)}/8"
    by_id("add-group").disabled = len(groups) >= 8


def section_diagram(shape: str) -> str:
    shape_class = "section-shape" if shape == "square" else "section-shape circle"
    symbol = "a" if shape == "square" else "D"
    return f'<div class="section-diagram"><div class="{shape_class}">{symbol}</div><span class="axis-line"></span><span class="axis-label">eje de flexión</span></div>'


def contribution_row(group: ColumnGroup, calculation: dict, index: int, direction_total: float) -> str:
    percent = calculation["contribution"] / direction_total * 100.0 if direction_total > 0 else 0.0
    circle_class = " circle" if group.shape == "circle" else ""
    return f"""
      <div class="contribution-row">
        <div class="contribution-symbol"><span class="shape-symbol{circle_class}"></span></div>
        <div class="contribution-main">
          <div><strong>C{index + 1}</strong><span>Eje {escape(str(group.axis))} · {group.quantity} × {shape_name(group.shape)} · {material_label(group.material)}</span><em>{format_number(percent, 1)}%</em></div>
          <div class="progress-track"><span style="width:{min(100.0, percent):.2f}%"></span></div>
        </div>
        <b>{format_number(calculation['contribution'])}<small>{calculation['stiffness_unit']}</small></b>
      </div>
    """


def modulus_step_text(group: ColumnGroup, calculation: dict) -> str:
    modulus_value = f"{format_number(calculation['elastic_modulus'])} {calculation['modulus_unit']}"
    if group.material == "steel":
        return f"E = <b>{modulus_value}</b> (constante del acero, no depende de f′c)"
    modulus_factor = "4.700" if units == "SI" else "15.000"
    return f"E = {modulus_factor} · √{format_number(group.fc)} = <b>{modulus_value}</b>"


def calculation_step(group: ColumnGroup, calculation: dict, index: int) -> str:
    inertia_formula = "a⁴ / 12" if group.shape == "square" else "πD⁴ / 64"
    inertia_substitution = (
        f"{format_number(group.dimension)}⁴ / 12"
        if group.shape == "square"
        else f"π · {format_number(group.dimension)}⁴ / 64"
    )
    factor = calculation["factor"]
    stiffness_formula = "0" if factor == 0 else f"{int(factor)}EI/h³"
    open_attribute = " open" if index == 0 else ""
    return f"""
      <details class="step-detail"{open_attribute}>
        <summary><span>C{index + 1}</span><div><strong>Eje {escape(str(group.axis))} · sección {shape_name(group.shape)} × {group.quantity}</strong><small>{material_label(group.material)} · {direction_label(group.direction)} · {support_name(group.base, 'base')} · unión {support_name(group.top, 'top')}</small></div><b>›</b></summary>
        <div class="step-content">
          {section_diagram(group.shape)}
          <ol>
            <li><span>1</span><div><strong>Módulo elástico del material</strong><p>{modulus_step_text(group, calculation)}</p></div></li>
            <li><span>2</span><div><strong>Momento de inercia bruto</strong><p>I = {inertia_formula} = {inertia_substitution} = <b>{format_number(calculation['inertia'])} {calculation['inertia_unit']}</b></p></div></li>
            <li><span>3</span><div><strong>Rigidez de una columna</strong><p>k = {stiffness_formula} = <b>{format_number(calculation['stiffness_per_column'])} {calculation['stiffness_unit']}</b></p></div></li>
            <li><span>4</span><div><strong>Aporte al eje {group.direction}</strong><p>{group.quantity} · {format_number(calculation['stiffness_per_column'])} = <b>{format_number(calculation['contribution'])} {calculation['stiffness_unit']}</b></p></div></li>
          </ol>
        </div>
      </details>
    """


def _iso_point(
    bx: float,
    by: float,
    bz: float,
    corner: tuple[float, float],
    ux: tuple[float, float],
    uy: tuple[float, float],
    uz: tuple[float, float],
) -> tuple[float, float]:
    """Proyecta una coordenada de grilla (bx, by, bz) a un punto 2D isométrico."""
    x = corner[0] + bx * ux[0] + by * uy[0] + bz * uz[0]
    y = corner[1] + bx * ux[1] + by * uy[1] + bz * uz[1]
    return x, y


def _iso_footing(px: float, py: float) -> str:
    return (
        f'<path class="iso-footing" d="M{px - 11:.1f} {py:.1f} L{px + 11:.1f} {py:.1f} '
        f'M{px - 8:.1f} {py:.1f} L{px - 13:.1f} {py + 9:.1f} '
        f'M{px:.1f} {py:.1f} L{px - 5:.1f} {py + 9:.1f} '
        f'M{px + 8:.1f} {py:.1f} L{px + 3:.1f} {py + 9:.1f}"/>'
    )


def _material_class(material: str) -> str:
    return "iso-column-steel" if material == "steel" else "iso-column-concrete"


def _expand_units(group_list: list[ColumnGroup], cap: int) -> list[tuple[str, str]]:
    units_list: list[tuple[str, str]] = []
    for group in group_list:
        for _ in range(int(group.quantity)):
            if len(units_list) >= cap:
                return units_list
            units_list.append((group.material, group.shape))
    return units_list


def _iso_shape_marker(
    top: tuple[float, float],
    material: str,
    shape: str,
    ux: tuple[float, float],
    uy: tuple[float, float],
) -> str:
    """Símbolo pequeño sobre la columna que indica si es cuadrada o circular."""
    marker_class = f"iso-marker-{material}"
    half = 0.24
    if shape == "circle":
        rx = ((ux[0] - uy[0]) ** 2 + (ux[1] - uy[1]) ** 2) ** 0.5 * half * 0.55
        ry = rx * 0.55
        return f'<ellipse class="{marker_class}" cx="{top[0]:.1f}" cy="{top[1]:.1f}" rx="{rx:.1f}" ry="{ry:.1f}"/>'
    p1 = (top[0] - half * ux[0] - half * uy[0], top[1] - half * ux[1] - half * uy[1])
    p2 = (top[0] + half * ux[0] - half * uy[0], top[1] + half * ux[1] - half * uy[1])
    p3 = (top[0] + half * ux[0] + half * uy[0], top[1] + half * ux[1] + half * uy[1])
    p4 = (top[0] - half * ux[0] + half * uy[0], top[1] - half * ux[1] + half * uy[1])
    points = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in (p1, p2, p3, p4))
    return f'<polygon class="{marker_class}" points="{points}"/>'


def _legacy_render_frame_diagram() -> None:
    """Dibuja un corte isométrico del entrepiso que refleja los grupos actuales."""
    corner = (0.0, 0.0)
    ux = (54.0, -31.0)
    uy = (-54.0, -31.0)
    height_px = max(70.0, min(170.0, 32.0 * max(story_height, 0.1)))
    uz = (0.0, -height_px)
    cap = 4

    x_groups = [group for group in groups if group.direction == "X"]
    y_groups = [group for group in groups if group.direction == "Y"]
    nx_total = sum(int(group.quantity) for group in x_groups)
    ny_total = sum(int(group.quantity) for group in y_groups)

    x_units = _expand_units(x_groups, cap)
    y_units = _expand_units(y_groups, cap)
    bays_x = max(1, len(x_units))
    bays_y = max(1, len(y_units))

    parts: list[str] = []
    bbox_points: list[tuple[float, float]] = []

    def track(*points: tuple[float, float]) -> None:
        bbox_points.extend(points)

    # Contorno del terreno (referencia, línea punteada)
    ground_x = _iso_point(bays_x, 0, 0, corner, ux, uy, uz)
    ground_y = _iso_point(0, bays_y, 0, corner, ux, uy, uz)
    ground_origin = _iso_point(0, 0, 0, corner, ux, uy, uz)
    track(ground_x, ground_y, ground_origin)
    parts.append(
        f'<path class="iso-ground" d="M{ground_origin[0]:.1f} {ground_origin[1]:.1f} '
        f'L{ground_x[0]:.1f} {ground_x[1]:.1f} M{ground_origin[0]:.1f} {ground_origin[1]:.1f} '
        f'L{ground_y[0]:.1f} {ground_y[1]:.1f}"/>'
    )

    # Losa / viga rígida en la parte superior
    top0 = _iso_point(0, 0, 1, corner, ux, uy, uz)
    topx = _iso_point(bays_x, 0, 1, corner, ux, uy, uz)
    topxy = _iso_point(bays_x, bays_y, 1, corner, ux, uy, uz)
    topy = _iso_point(0, bays_y, 1, corner, ux, uy, uz)
    track(top0, topx, topxy, topy)
    slab_points = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in (top0, topx, topxy, topy))
    parts.append(f'<polygon class="iso-slab" points="{slab_points}"/>')

    # Columna de esquina (comparte X e Y)
    corner_material, corner_shape = x_units[0] if x_units else (y_units[0] if y_units else ("concrete", "square"))
    base_c = _iso_point(0, 0, 0, corner, ux, uy, uz)
    top_c = _iso_point(0, 0, 1, corner, ux, uy, uz)
    track(base_c, top_c)
    parts.append(
        f'<line class="{_material_class(corner_material)}" x1="{base_c[0]:.1f}" y1="{base_c[1]:.1f}" '
        f'x2="{top_c[0]:.1f}" y2="{top_c[1]:.1f}"/>'
    )
    parts.append(_iso_footing(*base_c))
    parts.append(_iso_shape_marker(top_c, corner_material, corner_shape, ux, uy))

    for i, (material, shape) in enumerate(x_units, start=1):
        base = _iso_point(i, 0, 0, corner, ux, uy, uz)
        top = _iso_point(i, 0, 1, corner, ux, uy, uz)
        track(base, top)
        parts.append(
            f'<line class="{_material_class(material)}" x1="{base[0]:.1f}" y1="{base[1]:.1f}" '
            f'x2="{top[0]:.1f}" y2="{top[1]:.1f}"/>'
        )
        parts.append(_iso_footing(*base))
        parts.append(_iso_shape_marker(top, material, shape, ux, uy))

    for j, (material, shape) in enumerate(y_units, start=1):
        base = _iso_point(0, j, 0, corner, ux, uy, uz)
        top = _iso_point(0, j, 1, corner, ux, uy, uz)
        track(base, top)
        parts.append(
            f'<line class="{_material_class(material)}" x1="{base[0]:.1f}" y1="{base[1]:.1f}" '
            f'x2="{top[0]:.1f}" y2="{top[1]:.1f}"/>'
        )
        parts.append(_iso_footing(*base))
        parts.append(_iso_shape_marker(top, material, shape, ux, uy))

    if nx_total > 0:
        arrow_base = _iso_point(bays_x, 0, 1, corner, ux, uy, uz)
        arrow_tip = _iso_point(bays_x + 0.65, 0, 1, corner, ux, uy, uz)
        track(arrow_base, arrow_tip, (arrow_tip[0] + 60, arrow_tip[1]))
        parts.append(
            f'<path class="iso-axis-x" d="M{arrow_base[0]:.1f} {arrow_base[1]:.1f} '
            f'L{arrow_tip[0]:.1f} {arrow_tip[1]:.1f}" marker-end="url(#isoArrowX)"/>'
        )
        parts.append(f'<text class="iso-axis-x-label" x="{arrow_tip[0] + 6:.1f}" y="{arrow_tip[1]:.1f}">Δx = 1</text>')
    if ny_total > 0:
        arrow_base = _iso_point(0, bays_y, 1, corner, ux, uy, uz)
        arrow_tip = _iso_point(0, bays_y + 0.65, 1, corner, ux, uy, uz)
        track(arrow_base, arrow_tip, (arrow_tip[0] - 60, arrow_tip[1]))
        parts.append(
            f'<path class="iso-axis-y" d="M{arrow_base[0]:.1f} {arrow_base[1]:.1f} '
            f'L{arrow_tip[0]:.1f} {arrow_tip[1]:.1f}" marker-end="url(#isoArrowY)"/>'
        )
        parts.append(
            f'<text class="iso-axis-y-label" x="{arrow_tip[0] - 6:.1f}" y="{arrow_tip[1]:.1f}" text-anchor="end">Δy = 1</text>'
        )

    if nx_total > cap:
        label_pt = _iso_point(bays_x, 0, 1.18, corner, ux, uy, uz)
        track(label_pt)
        parts.append(f'<text class="iso-overflow" x="{label_pt[0]:.1f}" y="{label_pt[1]:.1f}">+{nx_total - cap}</text>')
    if ny_total > cap:
        label_pt = _iso_point(0, bays_y, 1.18, corner, ux, uy, uz)
        track(label_pt)
        parts.append(
            f'<text class="iso-overflow" x="{label_pt[0]:.1f}" y="{label_pt[1]:.1f}" text-anchor="end">+{ny_total - cap}</text>'
        )

    dim_base = _iso_point(-0.32, -0.08, 0, corner, ux, uy, uz)
    dim_top = _iso_point(-0.32, -0.08, 1, corner, ux, uy, uz)
    track((dim_base[0] - 95, dim_base[1]), (dim_top[0] - 95, dim_top[1]))
    parts.append(
        f'<path class="iso-dim" d="M{dim_base[0]:.1f} {dim_base[1]:.1f} L{dim_top[0]:.1f} {dim_top[1]:.1f} '
        f'M{dim_base[0] - 5:.1f} {dim_base[1]:.1f} L{dim_base[0] + 5:.1f} {dim_base[1]:.1f} '
        f'M{dim_top[0] - 5:.1f} {dim_top[1]:.1f} L{dim_top[0] + 5:.1f} {dim_top[1]:.1f}"/>'
    )
    dim_mid_x = (dim_base[0] + dim_top[0]) / 2 - 40
    dim_mid_y = (dim_base[1] + dim_top[1]) / 2
    parts.append(
        f'<text class="iso-dim-label" x="{dim_mid_x:.1f}" y="{dim_mid_y:.1f}">h = {format_number(story_height, 2)} m</text>'
    )

    # Encuadre dinámico: la vista se ajusta según cuántas columnas hay,
    # para que el dibujo siempre se vea centrado y a buena escala.
    pad_x, pad_top, pad_bottom = 34.0, 34.0, 22.0
    min_x = min(p[0] for p in bbox_points) - pad_x
    max_x = max(p[0] for p in bbox_points) + pad_x
    min_y = min(p[1] for p in bbox_points) - pad_top
    max_y = max(p[1] for p in bbox_points) + pad_bottom
    view_box = f"{min_x:.1f} {min_y:.1f} {max_x - min_x:.1f} {max_y - min_y:.1f}"

    svg = (
        f'<svg viewBox="{view_box}" role="img" '
        'aria-label="Corte isométrico del entrepiso con columnas en X e Y">'
        "<defs>"
        '<marker id="isoArrowX" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-x" d="M0,0 L8,4 L0,8 Z"/></marker>'
        '<marker id="isoArrowY" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-y" d="M0,0 L8,4 L0,8 Z"/></marker>'
        "</defs>"
        + "".join(parts)
        + "</svg>"
    )
    by_id("frame-diagram-3d").innerHTML = svg
    by_id("diagram-caption").textContent = (
        f"{nx_total} columna(s) en X · {ny_total} columna(s) en Y · corte isométrico ilustrativo"
    )


def _plan_marker(cx: float, cy: float, material: str, shape: str) -> str:
    marker_class = f"plan-marker-{material}"
    if shape == "circle":
        return f'<circle class="{marker_class}" cx="{cx:.1f}" cy="{cy:.1f}" r="10"/>'
    return f'<rect class="{marker_class}" x="{cx - 9:.1f}" y="{cy - 9:.1f}" width="18" height="18"/>'


def _legacy_render_plan_diagram() -> None:
    """Dibuja una vista en planta (desde arriba) que distingue con claridad
    la forma real de cada columna: cuadrada (□) o circular (○)."""
    L = 48.0
    cap = 6

    x_groups = [group for group in groups if group.direction == "X"]
    y_groups = [group for group in groups if group.direction == "Y"]
    nx_total = sum(int(group.quantity) for group in x_groups)
    ny_total = sum(int(group.quantity) for group in y_groups)

    x_units = _expand_units(x_groups, cap)
    y_units = _expand_units(y_groups, cap)
    bays_x = max(1, len(x_units))
    bays_y = max(1, len(y_units))

    parts: list[str] = []
    bbox_points: list[tuple[float, float]] = []

    def track(*points: tuple[float, float]) -> None:
        bbox_points.extend(points)

    end_x = (bays_x * L, 0.0)
    end_y = (0.0, -bays_y * L)
    corner_pt = (0.0, 0.0)
    far_pt = (bays_x * L, -bays_y * L)
    track(corner_pt, end_x, end_y, far_pt)

    # Contorno punteado del entrepiso
    parts.append(
        f'<path class="plan-grid" d="M{corner_pt[0]:.1f} {corner_pt[1]:.1f} L{end_x[0]:.1f} {end_x[1]:.1f} '
        f'L{far_pt[0]:.1f} {far_pt[1]:.1f} L{end_y[0]:.1f} {end_y[1]:.1f} Z"/>'
    )

    # Ejes X (teal) e Y (violeta)
    axis_x_end = (bays_x * L + 30, 0.0)
    axis_y_end = (0.0, -(bays_y * L + 30))
    track(axis_x_end, axis_y_end)
    parts.append(
        f'<path class="plan-axis-x" d="M0 0 L{axis_x_end[0]:.1f} {axis_x_end[1]:.1f}" marker-end="url(#planArrowX)"/>'
    )
    parts.append(f'<text class="plan-axis-label-x" x="{axis_x_end[0] + 6:.1f}" y="4">X</text>')
    parts.append(
        f'<path class="plan-axis-y" d="M0 0 L{axis_y_end[0]:.1f} {axis_y_end[1]:.1f}" marker-end="url(#planArrowY)"/>'
    )
    parts.append(f'<text class="plan-axis-label-y" x="6" y="{axis_y_end[1] - 8:.1f}">Y</text>')

    # Columna de esquina
    corner_material, corner_shape = x_units[0] if x_units else (y_units[0] if y_units else ("concrete", "square"))
    parts.append(_plan_marker(0, 0, corner_material, corner_shape))
    track((0, 0))

    for i, (material, shape) in enumerate(x_units, start=1):
        px, py = i * L, 0.0
        track((px, py))
        parts.append(_plan_marker(px, py, material, shape))

    for j, (material, shape) in enumerate(y_units, start=1):
        px, py = 0.0, -j * L
        track((px, py))
        parts.append(_plan_marker(px, py, material, shape))

    if nx_total > cap:
        pt = (bays_x * L, 20.0)
        track(pt)
        parts.append(f'<text class="plan-overflow" x="{pt[0]:.1f}" y="{pt[1]:.1f}" text-anchor="middle">+{nx_total - cap}</text>')
    if ny_total > cap:
        pt = (-24.0, -bays_y * L)
        track(pt)
        parts.append(f'<text class="plan-overflow" x="{pt[0]:.1f}" y="{pt[1]:.1f}" text-anchor="middle">+{ny_total - cap}</text>')

    pad = 30.0
    min_x = min(p[0] for p in bbox_points) - pad
    max_x = max(p[0] for p in bbox_points) + pad
    min_y = min(p[1] for p in bbox_points) - pad
    max_y = max(p[1] for p in bbox_points) + pad
    view_box = f"{min_x:.1f} {min_y:.1f} {max_x - min_x:.1f} {max_y - min_y:.1f}"

    svg = (
        f'<svg viewBox="{view_box}" role="img" aria-label="Vista en planta de la distribución de columnas">'
        "<defs>"
        '<marker id="planArrowX" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-x" d="M0,0 L8,4 L0,8 Z"/></marker>'
        '<marker id="planArrowY" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-y" d="M0,0 L8,4 L0,8 Z"/></marker>'
        "</defs>"
        + "".join(parts)
        + "</svg>"
    )
    by_id("frame-diagram-plan").innerHTML = svg
    by_id("plan-caption").textContent = (
        "Cada símbolo respeta la forma real de la columna: cuadrado = sección cuadrada, círculo = sección circular."
    )


def _display_axis(axis: str) -> str:
    """Presenta una etiqueta uniforme sin obligar al usuario a escribir 'Eje'."""
    clean = str(axis).strip() or "?"
    return clean if clean.lower().startswith("eje ") else f"Eje {clean}"


def _grid_layout(cap_per_axis: int = 10) -> list[tuple[str, list[tuple[str, str, str]], int]]:
    """Agrupa las columnas por eje y asigna estaciones A, B, C... sobre cada línea.

    Cada unidad conserva material, sección y dirección sísmica. La cantidad total
    se conserva aunque el dibujo limite los símbolos para seguir siendo legible.
    """
    order: list[str] = []
    visible: dict[str, list[tuple[str, str, str]]] = {}
    totals: dict[str, int] = {}
    for group in groups:
        axis = str(group.axis).strip() or "?"
        if axis not in visible:
            order.append(axis)
            visible[axis] = []
            totals[axis] = 0
        quantity = max(0, int(group.quantity))
        totals[axis] += quantity
        remaining = max(0, cap_per_axis - len(visible[axis]))
        visible[axis].extend(
            (group.material, group.shape, group.direction)
            for _ in range(min(quantity, remaining))
        )
    return [(axis, visible[axis], totals[axis]) for axis in order]


def render_frame_diagram() -> None:
    """Dibuja la misma retícula estructural de la planta en vista isométrica."""
    layout = _grid_layout()
    if not layout:
        by_id("frame-diagram-3d").innerHTML = ""
        by_id("diagram-caption").textContent = "Añade un grupo para generar la retícula."
        return

    axis_count = len(layout)
    station_count = max(1, max(len(axis_units) for _, axis_units, _ in layout))
    corner = (0.0, 0.0)
    ux = (64.0, -35.0)
    uy = (-48.0, -28.0)
    height_px = max(78.0, min(172.0, 34.0 * max(story_height, 0.1)))
    uz = (0.0, -height_px)
    min_grid_x, max_grid_x = -0.36, max(0, axis_count - 1) + 0.36
    min_grid_y, max_grid_y = -0.36, max(0, station_count - 1) + 0.36
    parts: list[str] = []
    bbox: list[tuple[float, float]] = []

    def point(gx: float, gy: float, top: float = 0.0) -> tuple[float, float]:
        projected = _iso_point(gx, gy, top, corner, ux, uy, uz)
        bbox.append(projected)
        return projected

    # Contorno de losa que rodea exactamente la retícula utilizada.
    slab = [
        point(min_grid_x, min_grid_y, 1),
        point(max_grid_x, min_grid_y, 1),
        point(max_grid_x, max_grid_y, 1),
        point(min_grid_x, max_grid_y, 1),
    ]
    slab_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in slab)
    parts.append(f'<polygon class="iso-slab" points="{slab_points}"/>')

    # Líneas de la grilla sobre la losa.
    for axis_index in range(axis_count):
        start = point(axis_index, min_grid_y, 1)
        end = point(axis_index, max_grid_y, 1)
        parts.append(
            f'<line class="iso-grid-line" x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
            f'x2="{end[0]:.1f}" y2="{end[1]:.1f}"/>'
        )
    for station_index in range(station_count):
        start = point(min_grid_x, station_index, 1)
        end = point(max_grid_x, station_index, 1)
        parts.append(
            f'<line class="iso-grid-line" x1="{start[0]:.1f}" y1="{start[1]:.1f}" '
            f'x2="{end[0]:.1f}" y2="{end[1]:.1f}"/>'
        )

    total_columns = 0
    for axis_index, (axis, axis_units, axis_total) in enumerate(layout):
        total_columns += axis_total
        label_point = point(axis_index, min_grid_y - 0.34, 1)
        parts.append(
            f'<text class="iso-grid-label" x="{label_point[0]:.1f}" y="{label_point[1] - 5:.1f}" '
            f'text-anchor="middle">{escape(_display_axis(axis))}</text>'
        )
        for station_index, (material, shape, _direction) in enumerate(axis_units):
            base = point(axis_index, station_index, 0)
            top = point(axis_index, station_index, 1)
            parts.append(
                f'<line class="{_material_class(material)}" x1="{base[0]:.1f}" y1="{base[1]:.1f}" '
                f'x2="{top[0]:.1f}" y2="{top[1]:.1f}"/>'
            )
            parts.append(_iso_footing(*base))
            parts.append(_iso_shape_marker(top, material, shape, ux, uy))
        hidden_count = axis_total - len(axis_units)
        if hidden_count > 0:
            overflow_point = point(axis_index, max(0, len(axis_units) - 1), 1.18)
            parts.append(
                f'<text class="iso-overflow" x="{overflow_point[0]:.1f}" y="{overflow_point[1]:.1f}" '
                f'text-anchor="middle">+{hidden_count}</text>'
            )

    # Letras de las estaciones transversales.
    for station_index in range(station_count):
        station_point = point(min_grid_x - 0.28, station_index, 1)
        station = chr(65 + station_index)
        parts.append(
            f'<text class="iso-station-label" x="{station_point[0]:.1f}" y="{station_point[1]:.1f}" '
            f'text-anchor="end">{station}</text>'
        )

    # Flechas X/Y: indican la dirección de análisis, no la ubicación del eje.
    x_start = point(max_grid_x, min_grid_y, 1)
    x_end = point(max_grid_x + 0.7, min_grid_y, 1)
    y_start = point(min_grid_x, max_grid_y, 1)
    y_end = point(min_grid_x, max_grid_y + 0.7, 1)
    parts.extend(
        [
            f'<path class="iso-axis-x" d="M{x_start[0]:.1f} {x_start[1]:.1f} L{x_end[0]:.1f} {x_end[1]:.1f}" marker-end="url(#isoArrowX)"/>',
            f'<text class="iso-axis-x-label" x="{x_end[0] + 6:.1f}" y="{x_end[1]:.1f}">X</text>',
            f'<path class="iso-axis-y" d="M{y_start[0]:.1f} {y_start[1]:.1f} L{y_end[0]:.1f} {y_end[1]:.1f}" marker-end="url(#isoArrowY)"/>',
            f'<text class="iso-axis-y-label" x="{y_end[0] - 6:.1f}" y="{y_end[1]:.1f}" text-anchor="end">Y</text>',
        ]
    )

    # La cota "h" se ubica a partir del punto más a la izquierda ya dibujado
    # (en coordenadas de pantalla), no de un offset fijo en la grilla. Con
    # varias estaciones en profundidad, la proyección isométrica desplaza las
    # columnas del fondo mucho más a la izquierda que un offset fijo podía
    # prever, y la cota terminaba superpuesta con ellas.
    reference_base = point(min_grid_x, min_grid_y, 0)
    reference_top = point(min_grid_x, min_grid_y, 1)
    dim_x = min(x for x, _ in bbox) - 34.0
    dim_base = (dim_x, reference_base[1])
    dim_top = (dim_x, reference_top[1])
    bbox.append(dim_base)
    bbox.append(dim_top)
    parts.append(
        f'<path class="iso-dim" d="M{dim_base[0]:.1f} {dim_base[1]:.1f} L{dim_top[0]:.1f} {dim_top[1]:.1f}"/>'
    )
    parts.append(
        f'<text class="iso-dim-label" x="{dim_x - 7:.1f}" y="{(dim_base[1] + dim_top[1]) / 2:.1f}" '
        f'text-anchor="end">h = {format_number(story_height, 2)} m</text>'
    )

    padding = 42.0
    min_x = min(x for x, _ in bbox) - padding
    max_x = max(x for x, _ in bbox) + padding
    min_y = min(y for _, y in bbox) - padding
    max_y = max(y for _, y in bbox) + padding
    svg = (
        f'<svg viewBox="{min_x:.1f} {min_y:.1f} {max_x - min_x:.1f} {max_y - min_y:.1f}" '
        'role="img" aria-label="Vista isométrica de la retícula estructural">'
        '<defs><marker id="isoArrowX" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-x" d="M0,0 L8,4 L0,8 Z"/></marker>'
        '<marker id="isoArrowY" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-y" d="M0,0 L8,4 L0,8 Z"/></marker></defs>'
        + "".join(parts)
        + "</svg>"
    )
    by_id("frame-diagram-3d").innerHTML = svg
    by_id("diagram-caption").textContent = (
        f"{total_columns} columna(s) distribuida(s) en {axis_count} eje(s) estructural(es)."
    )


def render_plan_diagram() -> None:
    """Dibuja una planta de ejes: cada grupo aparece sobre la línea indicada."""
    layout = _grid_layout()
    if not layout:
        by_id("frame-diagram-plan").innerHTML = ""
        by_id("plan-caption").textContent = "Añade un grupo para generar la planta."
        return

    spacing_x, spacing_y = 72.0, 56.0
    axis_count = len(layout)
    station_count = max(1, max(len(axis_units) for _, axis_units, _ in layout))
    width = max(0, axis_count - 1) * spacing_x
    height = max(0, station_count - 1) * spacing_y
    parts: list[str] = []

    # Retícula: ejes estructurales verticales y estaciones A, B, C horizontales.
    for axis_index, (axis, _axis_units, _axis_total) in enumerate(layout):
        x = axis_index * spacing_x
        parts.append(f'<line class="plan-axis-line" x1="{x:.1f}" y1="-18" x2="{x:.1f}" y2="{height + 18:.1f}"/>')
        parts.append(
            f'<text class="plan-grid-label" x="{x:.1f}" y="{height + 39:.1f}" text-anchor="middle">'
            f'{escape(_display_axis(axis))}</text>'
        )
    for station_index in range(station_count):
        y = station_index * spacing_y
        parts.append(f'<line class="plan-station-line" x1="-18" y1="{y:.1f}" x2="{width + 18:.1f}" y2="{y:.1f}"/>')
        parts.append(
            f'<text class="plan-station-label" x="-29" y="{y + 4:.1f}" text-anchor="middle">{chr(65 + station_index)}</text>'
        )

    for axis_index, (_axis, axis_units, axis_total) in enumerate(layout):
        x = axis_index * spacing_x
        for station_index, (material, shape, _direction) in enumerate(axis_units):
            y = station_index * spacing_y
            parts.append(_plan_marker(x, y, material, shape))
        hidden_count = axis_total - len(axis_units)
        if hidden_count > 0:
            parts.append(
                f'<text class="plan-overflow" x="{x:.1f}" y="{height + 57:.1f}" '
                f'text-anchor="middle">+{hidden_count} columnas</text>'
            )

    # Indicadores globales de coordenadas.
    arrow_y = height + 77.0
    parts.append(
        f'<path class="plan-axis-x" d="M0 {arrow_y:.1f} L{max(70.0, width + 42):.1f} {arrow_y:.1f}" marker-end="url(#planArrowX)"/>'
    )
    parts.append(f'<text class="plan-axis-label-x" x="{max(76.0, width + 49):.1f}" y="{arrow_y + 4:.1f}">X</text>')
    parts.append(
        f'<path class="plan-axis-y" d="M-51 {height:.1f} L-51 -36" marker-end="url(#planArrowY)"/>'
    )
    parts.append('<text class="plan-axis-label-y" x="-47" y="-43">Y</text>')

    min_x, min_y = -72.0, -60.0
    max_x, max_y = max(width + 92.0, 165.0), arrow_y + 28.0
    svg = (
        f'<svg viewBox="{min_x:.1f} {min_y:.1f} {max_x - min_x:.1f} {max_y - min_y:.1f}" '
        'role="img" aria-label="Vista en planta de columnas distribuidas por ejes estructurales">'
        '<defs><marker id="planArrowX" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-x" d="M0,0 L8,4 L0,8 Z"/></marker>'
        '<marker id="planArrowY" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
        '<path class="iso-arrowhead-y" d="M0,0 L8,4 L0,8 Z"/></marker></defs>'
        + "".join(parts)
        + "</svg>"
    )
    by_id("frame-diagram-plan").innerHTML = svg
    axis_names = ", ".join(_display_axis(axis) for axis, _, _ in layout)
    by_id("plan-caption").textContent = (
        f"Retícula activa: {axis_names}. Las columnas se reparten en estaciones A, B, C…"
    )


def show_warning(message: str | None) -> None:
    warning = by_id("calculation-warning")
    warning.hidden = not bool(message)
    warning.textContent = message or ""


def render_results() -> None:
    labels = unit_labels()
    by_id("stiffness-unit-x").textContent = labels["stiffness"]
    by_id("stiffness-unit-y").textContent = labels["stiffness"]
    height_in_units = story_height * (1_000 if units == "SI" else 100)
    by_id("height-conversion").innerHTML = (
        f"h = {format_number(story_height, 3)} m = <strong>{format_number(height_in_units, 2)} {labels['length']}</strong>"
    )
    render_frame_diagram()
    render_plan_diagram()
    try:
        result = calculate_story(groups, story_height, units)
    except ValueError as error:
        by_id("total-stiffness-x").textContent = "—"
        by_id("total-stiffness-y").textContent = "—"
        by_id("contribution-count").textContent = f"{len(groups)} grupo(s)"
        by_id("contribution-list").innerHTML = ""
        by_id("steps-list").innerHTML = ""
        show_warning(str(error))
        return

    totals = result["totals"]
    calculations = result["groups"]
    by_id("total-stiffness-x").textContent = format_number(totals["X"])
    by_id("total-stiffness-y").textContent = format_number(totals["Y"])
    by_id("contribution-count").textContent = f"{len(groups)} grupo(s)"
    by_id("contribution-list").innerHTML = "".join(
        contribution_row(group, calculations[index], index, totals[group.direction])
        for index, group in enumerate(groups)
    )
    by_id("steps-list").innerHTML = "".join(
        calculation_step(group, calculations[index], index)
        for index, group in enumerate(groups)
    )
    show_warning(None)


def render_analysis_inputs() -> None:
    """Sincroniza los controles de la etapa 2 con el estado de Python."""
    by_id("building-levels").value = str(analysis_level_count)
    by_id("analysis-level-count").textContent = (
        "1 nivel" if analysis_level_count == 1 else f"{analysis_level_count} niveles"
    )
    by_id("analysis-alpha").value = input_number(analysis_alpha)
    by_id("analysis-cm-x").value = input_number(analysis_cm_x)
    by_id("analysis-cm-y").value = input_number(analysis_cm_y)
    by_id("analysis-ecc-x").value = input_number(analysis_ecc_x)
    by_id("analysis-ecc-y").value = input_number(analysis_ecc_y)

    floor_rows = []
    for index in range(analysis_level_count):
        floor_rows.append(
            f"""
            <div class="analysis-floor-row">
              <strong>Nivel {index + 1}</strong>
              <div class="analysis-mini-field"><input type="number" min="1" max="12" step="0.05" value="{input_number(analysis_heights[index])}" data-field="analysis-height" data-level="{index}" aria-label="Altura del nivel {index + 1}" /><span>h m</span></div>
              <div class="analysis-mini-field"><input type="number" step="1" value="{input_number(analysis_forces[index])}" data-field="analysis-force" data-level="{index}" aria-label="Fuerza sísmica del nivel {index + 1}" /><span>F kN</span></div>
            </div>
            """
        )
    by_id("analysis-floor-list").innerHTML = "".join(floor_rows)

    frame_rows = []
    for index, group in enumerate(groups):
        frame_rows.append(
            f"""
            <article class="analysis-frame-row">
              <div class="analysis-frame-row__head">
                <div><span class="column-code">C{index + 1}</span><strong>Eje {escape(str(group.axis))}</strong></div>
                <div><span class="direction-chip">Base {group.direction}</span><small>{group.quantity} columna(s) · {shape_name(group.shape)}</small></div>
              </div>
              <div class="analysis-frame-fields">
                <label>x₀ (m)<input type="number" step="0.1" value="{input_number(group.x0)}" data-field="analysis-frame-x" data-group="{group.id}" /></label>
                <label>y₀ (m)<input type="number" step="0.1" value="{input_number(group.y0)}" data-field="analysis-frame-y" data-group="{group.id}" /></label>
                <label>β (°)<input type="number" step="1" value="{input_number(group.beta)}" data-field="analysis-frame-beta" data-group="{group.id}" /></label>
              </div>
            </article>
            """
        )
    by_id("analysis-frame-list").innerHTML = "".join(frame_rows)


def _analysis_plan_svg(center_rigidity: dict[str, float] | None = None) -> str:
    points = [(float(group.x0), float(group.y0)) for group in groups]
    points.append((analysis_cm_x, analysis_cm_y))
    if center_rigidity is not None:
        points.append((center_rigidity["x"], center_rigidity["y"]))
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    min_x, max_x = min(x_values), max(x_values)
    min_y, max_y = min(y_values), max(y_values)
    if max_x - min_x < 1.0:
        center = (max_x + min_x) / 2.0
        min_x, max_x = center - 2.5, center + 2.5
    else:
        margin = (max_x - min_x) * 0.18
        min_x, max_x = min_x - margin, max_x + margin
    if max_y - min_y < 1.0:
        center = (max_y + min_y) / 2.0
        min_y, max_y = center - 2.0, center + 2.0
    else:
        margin = (max_y - min_y) * 0.18
        min_y, max_y = min_y - margin, max_y + margin

    def map_point(x_value: float, y_value: float) -> tuple[float, float]:
        px = 48.0 + (x_value - min_x) / (max_x - min_x) * 424.0
        py = 262.0 - (y_value - min_y) / (max_y - min_y) * 224.0
        return px, py

    parts = [
        '<svg viewBox="0 0 520 300" role="img" aria-label="Ejes resistentes y centro de masa en planta">',
        '<rect x="48" y="38" width="424" height="224" rx="6" fill="white" stroke="#cbd7d5"/>',
    ]
    for step in range(1, 5):
        grid_x = 48 + 424 * step / 5
        grid_y = 38 + 224 * step / 5
        parts.append(f'<line class="analysis-grid-line" x1="{grid_x:.1f}" y1="38" x2="{grid_x:.1f}" y2="262"/>')
        parts.append(f'<line class="analysis-grid-line" x1="48" y1="{grid_y:.1f}" x2="472" y2="{grid_y:.1f}"/>')
    for index, group in enumerate(groups):
        px, py = map_point(float(group.x0), float(group.y0))
        beta = radians(float(group.beta))
        dx = cos(beta) * 56.0
        dy = -sin(beta) * 56.0
        extra_class = " analysis-axis-line--y" if abs(sin(beta)) > abs(cos(beta)) else ""
        label_x = min(482.0, max(38.0, px + dx + 7.0))
        label_y = min(278.0, max(24.0, py + dy - 7.0))
        parts.append(
            f'<line class="analysis-axis-line{extra_class}" x1="{px - dx:.1f}" y1="{py - dy:.1f}" x2="{px + dx:.1f}" y2="{py + dy:.1f}"/>'
        )
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#122c33"/>')
        parts.append(
            f'<text class="analysis-axis-label" x="{label_x:.1f}" y="{label_y:.1f}">{escape(str(group.axis))} · β={format_number(group.beta, 0)}°</text>'
        )
    if center_rigidity is not None:
        # El CR se dibuja ANTES que el CM y como rombo hueco: si ambos
        # coinciden (edificio simétrico, caso normal en el ejemplo estable)
        # el círculo relleno del CM queda visible por encima y el rombo del
        # CR se ve alrededor, en vez de que uno tape completamente al otro.
        cr_x, cr_y = map_point(center_rigidity["x"], center_rigidity["y"])
        parts.append(f'<rect class="analysis-cr" x="{cr_x - 9:.1f}" y="{cr_y - 9:.1f}" width="18" height="18" transform="rotate(45 {cr_x:.1f} {cr_y:.1f})"/>')
        parts.append(f'<text class="analysis-cr-label" x="{cr_x + 14:.1f}" y="{cr_y + 21:.1f}">CR</text>')
    cm_x, cm_y = map_point(analysis_cm_x, analysis_cm_y)
    parts.append(f'<circle class="analysis-cm" cx="{cm_x:.1f}" cy="{cm_y:.1f}" r="8"/>')
    parts.append(f'<text class="analysis-cm-label" x="{cm_x + 12:.1f}" y="{cm_y - 10:.1f}">CM</text>')
    parts.append('<text class="analysis-axis-label" x="477" y="278">X</text>')
    parts.append('<text class="analysis-axis-label" x="32" y="34">Y</text></svg>')
    return "".join(parts)


def _compact_number(value: float) -> str:
    number = float(value)
    absolute = abs(number)
    if absolute >= 100_000 or (0 < absolute < 0.001):
        return f"{number:.3e}".replace(".", ",")
    return format_number(number, 3)


def _labeled_matrix_table(matrix: list[list[float]], row_labels: list[str], col_labels: list[str], corner: str = "") -> str:
    header = "".join(f"<th>{escape(label)}</th>" for label in col_labels)
    rows = []
    for row_label, row in zip(row_labels, matrix):
        cells = "".join(f"<td>{_compact_number(value)}</td>" for value in row)
        rows.append(f"<tr><th>{escape(row_label)}</th>{cells}</tr>")
    return f'<div class="table-scroll"><table class="matrix-table"><thead><tr><th>{escape(corner)}</th>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _matrix_table(matrix: list[list[float]], labels: list[str]) -> str:
    return _labeled_matrix_table(matrix, labels, labels, "GDL")


def _equation_matrix(rows: list[list[str]], aria_label: str) -> str:
    """Matriz compacta con corchetes, pensada para desarrollos de ecuaciones."""

    column_count = max((len(row) for row in rows), default=1)
    cells = "".join(f"<span>{cell}</span>" for row in rows for cell in row)
    return (
        f'<span class="equation-matrix" role="img" aria-label="{escape(aria_label, quote=True)}">'
        f'<span class="equation-matrix-grid" style="--matrix-columns:{column_count}">{cells}</span></span>'
    )


def _local_matrix_symbolic(axis: str, levels: int) -> list[list[str]]:
    """Forma simbólica tridiagonal del modelo de corte de un pórtico."""

    axis_html = escape(str(axis))

    def k(level: int) -> str:
        return f"k<sub>{axis_html},{level}</sub>"

    symbolic = [["0" for _column in range(levels)] for _row in range(levels)]
    for row in range(levels):
        symbolic[row][row] = k(row + 1) if row == levels - 1 else f"{k(row + 1)} + {k(row + 2)}"
        if row < levels - 1:
            symbolic[row][row + 1] = f"−{k(row + 2)}"
            symbolic[row + 1][row] = f"−{k(row + 2)}"
    return symbolic


def _local_matrix_development(frame: dict, levels: int, stiffness_unit: str) -> str:
    """Desarrollo simbólico y numérico de K local para el pórtico seleccionado."""

    axis = str(frame["axis"])
    axis_html = escape(axis)
    symbolic = _local_matrix_symbolic(axis, levels)
    numeric = [[_compact_number(value) for value in row] for row in frame["local_matrix"]]
    k_values = " · ".join(
        f"k<sub>{axis_html},{level + 1}</sub> = {_compact_number(value)}"
        for level, value in enumerate(frame["story_stiffnesses"])
    )
    return f"""
      <div class="local-matrix-development">
        <div class="local-matrix-title">
          <div><strong>Pórtico del eje {axis_html} — desarrollo completo</strong><span>Modelo de corte de {levels} nivel{"es" if levels != 1 else ""}</span></div>
          <span>{escape(stiffness_unit)}</span>
        </div>
        <p>Rigideces de entrepiso: {k_values} {escape(stiffness_unit)}.</p>
        <div class="local-matrix-equation-scroll">
          <div class="local-matrix-equation">
            <span class="matrix-name">[K<sub>{axis_html}</sub>]<sub>local</sub></span>
            <span class="matrix-equals">=</span>
            {_equation_matrix(symbolic, f'Matriz local simbólica del eje {axis}')}
            <span class="matrix-equals">=</span>
            {_equation_matrix(numeric, f'Matriz local numérica del eje {axis}')}
            <span class="matrix-equation-unit">{escape(stiffness_unit)}</span>
          </div>
        </div>
        <p class="local-matrix-note">Cada fila y columna representa un nivel. Al cambiar de pórtico se actualizan sus rigideces y todos los términos de la matriz.</p>
      </div>
    """


def _analysis_steps_html(result: dict) -> str:
    """Desarrollo didáctico paso a paso, recalculado con los datos vigentes.

    Reutiliza exactamente las mismas cifras que ya calculó
    analyze_pseudotridimensional (result y result['frames']), así que nunca
    puede desincronizarse de lo que muestran las demás tarjetas: si el
    usuario cambia una fuerza, una altura o agrega un eje, este desarrollo
    se recalcula solo, como el resto de la Etapa 2.
    """
    frames = result["frames"]
    levels = result["levels"]
    level_labels = [f"Nivel {level + 1}" for level in range(levels)]
    dof_labels: list[str] = []
    for level in range(levels):
        dof_labels.extend((f"Ux{level + 1}", f"Uy{level + 1}", f"Rz{level + 1}"))
    # El solucionador convierte internamente las rigideces MKS a kN/m.
    stiffness_unit = "kN/m"
    selected_frame = next(
        (frame for frame in frames if str(frame["id"]) == str(analysis_selected_axis_id)),
        frames[0],
    )

    # Paso 0 — rigidez de columna por eje
    rows0 = []
    for group, frame in zip(groups, frames):
        calc0 = calculate_group(group, analysis_heights[0], units)
        k_levels = " · ".join(_compact_number(value) for value in frame["story_stiffnesses"])
        rows0.append(
            f"<tr><td>{escape(str(group.axis))}</td><td>{escape(material_label(group.material))}</td>"
            f"<td>{_compact_number(calc0.elastic_modulus)} {escape(calc0.modulus_unit)}</td>"
            f"<td>{_compact_number(calc0.inertia)} {escape(calc0.inertia_unit)}</td>"
            f"<td>{int(group.quantity)}</td><td>{k_levels} kN/m</td></tr>"
        )
    step0 = f"""
      <div class="step-block">
        <h4><span class="step-badge">0</span>Rigidez lateral de cada eje</h4>
        <p>Cada columna aporta <code>k_col = c·E·I / h³</code> (c=12 con ambos extremos empotrados). El eje suma sus columnas en paralelo: <code>k_eje = n · k_col</code>. Si la altura cambia por nivel, k_eje se recalcula en cada uno.</p>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>Eje</th><th>Material</th><th>E</th><th>I</th><th>n° col.</th><th>k_eje por nivel</th></tr></thead><tbody>{"".join(rows0)}</tbody></table></div>
      </div>
    """

    # Paso 1 — identificación de ejes y sistema global
    rows1 = []
    for group in groups:
        beta = radians(float(group.beta))
        rows1.append(
            f"<tr><td>{escape(str(group.axis))}</td><td>{format_number(group.x0, 3)}</td><td>{format_number(group.y0, 3)}</td>"
            f"<td>{format_number(group.beta, 1)}</td><td>{_compact_number(cos(beta))}</td><td>{_compact_number(sin(beta))}</td></tr>"
        )
    dof_list_text = ", ".join(dof_labels)
    step1 = f"""
      <div class="step-block">
        <h4><span class="step-badge">1</span>Identificación de ejes y sistema global</h4>
        <p>Sistema global X-Y: cada eje se ubica con un punto (x₀,y₀) sobre él y el ángulo β respecto a X (positivo antihorario).</p>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>Eje</th><th>x₀ (m)</th><th>y₀ (m)</th><th>β (°)</th><th>cos β</th><th>sin β</th></tr></thead><tbody>{"".join(rows1)}</tbody></table></div>
        <p>Centro de masa: CM = ({format_number(analysis_cm_x, 3)} ; {format_number(analysis_cm_y, 3)}) m. Incógnitas: {{U}} = {{{escape(dof_list_text)}}}<sup>T</sup> → {3 * levels} grados de libertad.</p>
      </div>
    """

    # Paso 2 — matriz local K_eje del pórtico seleccionado
    step2 = f"""
      <div class="step-block">
        <h4><span class="step-badge">2</span>Rigidez lateral de cada eje (K<sub>eje</sub>)</h4>
        <p>Modelo de corte apilado: fila y columna representan niveles; el eje se comporta como resortes de corte en serie. El selector de la tarjeta «Matriz local del pórtico» permite revisar cada eje.</p>
        {_local_matrix_development(selected_frame, levels, stiffness_unit)}
      </div>
    """

    # Paso 3 — brazos de palanca r y matrices [G]
    step3_blocks = []
    for frame in frames:
        formula = (
            f"r_{frame['axis']} = -({format_number(frame['x0'], 3)} - {format_number(analysis_cm_x, 3)})·sin({format_number(frame['beta'], 1)}°) "
            f"+ ({format_number(frame['y0'], 3)} - {format_number(analysis_cm_y, 3)})·cos({format_number(frame['beta'], 1)}°) = {format_number(frame['lever_arm'], 4)} m"
        )
        step3_blocks.append(
            f'<p class="step-axis-title">Eje {escape(str(frame["axis"]))}</p>'
            f'<div class="step-formula">{escape(formula)}</div>'
            + _labeled_matrix_table(frame["transformation"], level_labels, dof_labels, "Nivel")
        )
    step3 = f"""
      <div class="step-block">
        <h4><span class="step-badge">3</span>Brazos r<sub>j</sub> y matrices de transformación [G<sub>j</sub>]</h4>
        <p><code>r = -(x₀-x_CM)·sinβ + (y₀-y_CM)·cosβ</code>. [G] relaciona el desplazamiento del eje con {{u<sub>x</sub>, u<sub>y</sub>, θ}} del diafragma, nivel a nivel.</p>
        {"".join(step3_blocks)}
      </div>
    """

    # Paso 4 — contribución de cada eje y ensamblaje de K_P3D
    intermediate = _matmul(selected_frame["local_matrix"], selected_frame["transformation"])
    contribution = _matmul(_transpose(selected_frame["transformation"]), intermediate)
    other_axes = ", ".join(
        f"eje {escape(str(frame['axis']))} (r={format_number(frame['lever_arm'], 3)} m, k={_compact_number(frame['story_stiffnesses'][0])} {stiffness_unit})"
        for frame in frames if str(frame["id"]) != str(selected_frame["id"])
    )
    step4 = f"""
      <div class="step-block">
        <h4><span class="step-badge">4</span>Contribución de cada eje a la matriz global</h4>
        <p>Cada eje aporta con la transformación de congruencia <code>[K_eje]<sub>global</sub> = [G]<sup>T</sup>[K_eje][G]</code>. Se muestra el desarrollo completo del pórtico seleccionado.</p>
        <p class="step-axis-title">Eje {escape(str(selected_frame["axis"]))} — producto [K_local]·[G]</p>
        {_labeled_matrix_table(intermediate, level_labels, dof_labels, "Nivel")}
        <p class="step-axis-title">Eje {escape(str(selected_frame["axis"]))} — [G]<sup>T</sup>·(anterior) = aporte a K global</p>
        {_labeled_matrix_table(contribution, dof_labels, dof_labels, "GDL")}
        {f'<p class="step-note">Los demás ejes se procesan igual: {other_axes}.</p>' if other_axes else ""}
        <p class="step-axis-title">Matriz global ensamblada K<sub>P3D</sub> = Σ [G]<sup>T</sup>[K_eje][G]</p>
        {_matrix_table(result["global_matrix"], dof_labels)}
      </div>
    """

    # Paso 5 — vector de fuerzas F
    force_rows = []
    for level, load in enumerate(result["floor_loads"]):
        force_rows.append(
            f"<tr><td>Nivel {level + 1}</td><td>{format_number(load['fx'], 3)}</td><td>{format_number(load['fy'], 3)}</td><td>{format_number(load['mz'], 3)}</td></tr>"
        )
    step5 = f"""
      <div class="step-block">
        <h4><span class="step-badge">5</span>Vector de fuerzas {{F}}</h4>
        <p>Independiente de K: sale directo de las fuerzas de entrada, el ángulo α y las excentricidades accidentales — no de la geometría de los ejes. <code>Fx=F·cosα</code>, <code>Fy=F·sinα</code>, <code>Mz=e<sub>acc,x</sub>·Fy − e<sub>acc,y</sub>·Fx</code>.</p>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>Nivel</th><th>Fx (kN)</th><th>Fy (kN)</th><th>Mz (kN·m)</th></tr></thead><tbody>{"".join(force_rows)}</tbody></table></div>
      </div>
    """

    # Paso 6 — solución del sistema K·U=F
    disp_rows = []
    for item in result["displacements"]:
        disp_rows.append(
            f"<tr><td>Nivel {item['level']}</td><td>{format_number(item['ux'] * 1000.0, 4)}</td><td>{format_number(item['uy'] * 1000.0, 4)}</td><td>{format_number(item['theta'] * 1000.0, 5)}</td></tr>"
        )
    step6 = f"""
      <div class="step-block">
        <h4><span class="step-badge">6</span>Solución del sistema [K<sub>P3D</sub>]{{U}} = {{F}}</h4>
        <p>Resolviendo el sistema lineal se obtienen los desplazamientos y el giro de cada diafragma.</p>
        <div class="table-scroll"><table class="data-table"><thead><tr><th>Nivel</th><th>u<sub>x</sub> (mm)</th><th>u<sub>y</sub> (mm)</th><th>θ (mrad)</th></tr></thead><tbody>{"".join(disp_rows)}</tbody></table></div>
      </div>
    """

    # Paso 7 — centro de rigidez
    a_xx = a_xy = a_yy = b_x = b_y = 0.0
    for frame in frames:
        beta = radians(float(frame["beta"]))
        dir_x, dir_y = cos(beta), sin(beta)
        k1 = float(frame["story_stiffnesses"][0])
        r = float(frame["lever_arm"])
        a_xx += k1 * dir_x * dir_x
        a_xy += k1 * dir_x * dir_y
        a_yy += k1 * dir_y * dir_y
        b_x += k1 * dir_x * r
        b_y += k1 * dir_y * r
    center_rigidity = result["center_rigidity"]
    if center_rigidity is not None:
        cr_text = f"CR = ({format_number(center_rigidity['x'], 3)} ; {format_number(center_rigidity['y'], 3)}) m"
    else:
        cr_text = "El sistema es singular en el nivel 1 (a_xx·a_yy = a_xy²); no se pudo aislar un CR único con esta configuración."
    step7 = f"""
      <div class="step-block">
        <h4><span class="step-badge">7</span>Centro de rigidez (CR)</h4>
        <p>Se anula el acople traslación-giro de la matriz de nivel 1: a_xx={_compact_number(a_xx)}, a_xy={_compact_number(a_xy)}, a_yy={_compact_number(a_yy)}, b_x={_compact_number(b_x)}, b_y={_compact_number(b_y)} ({stiffness_unit}, referidos al nivel 1).</p>
        <div class="step-formula">q_x = (-b_x·a_yy + a_xy·b_y) / (a_xx·a_yy - a_xy²)
q_y = (a_xy·b_x - a_xx·b_y) / (a_xx·a_yy - a_xy²)
CR = (x_CM + q_y ; y_CM - q_x)</div>
        <p><strong>{escape(cr_text)}</strong></p>
      </div>
    """

    return step0 + step1 + step2 + step3 + step4 + step5 + step6 + step7


def toggle_details_panel(selector: str) -> None:
    """Abre/cierra un panel colapsable con un único clic.

    Antes usábamos <details>/<summary> nativos con event.preventDefault()
    para evitar que el toggle nativo del navegador compitiera con el de
    Python. Eso fallaba en la práctica: PyScript despacha el evento de clic
    a Python de forma asíncrona, así que para cuando preventDefault() se
    ejecutaba, el navegador ya había aplicado su propio toggle nativo — el
    resultado neto de los dos toggles encontrados era que no cambiaba nada
    visualmente. Ahora el panel es un <div>/<button> sin ningún
    comportamiento nativo que interceptar: el estado abierto/cerrado vive
    exclusivamente en la clase 'is-open', que solo Python controla.
    """
    container = document.querySelector(selector)
    if hasattr(container, "classList"):
        is_open = bool(container.classList.contains("is-open"))
        container.classList.toggle("is-open")
        toggle_button = container.querySelector(".details-toggle")
        if hasattr(toggle_button, "setAttribute"):
            toggle_button.setAttribute("aria-expanded", "false" if is_open else "true")


def _update_details_panel(panel_id: str, selector: str, html: str) -> None:
    by_id(panel_id).innerHTML = html


def _footprint_bounds() -> tuple[float, float, float, float]:
    """Rectángulo simplificado que envuelve todos los ejes resistentes."""
    xs = [float(group.x0) for group in groups]
    ys = [float(group.y0) for group in groups]
    pad = 1.3
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    if max_x - min_x < 1.0:
        center = (max_x + min_x) / 2.0
        min_x, max_x = center - 1.5, center + 1.5
    if max_y - min_y < 1.0:
        center = (max_y + min_y) / 2.0
        min_y, max_y = center - 1.5, center + 1.5
    return min_x, max_x, min_y, max_y


def _deformation_amplifier(displacements: list[dict], footprint_size: float) -> float:
    """Factor de amplificación visual: el máximo desplazamiento real (mm)
    ocuparía un pixel en el dibujo, así que se agranda para que se note.
    """
    max_disp = max(
        (max(abs(item["ux"]), abs(item["uy"])) for item in displacements),
        default=0.0,
    )
    if max_disp <= 1e-9:
        return 1.0
    target = max(0.5, footprint_size * 0.2)
    return max(1.0, target / max_disp)


def _rigid_diaphragm_offset(
    px: float, py: float, cm_x: float, cm_y: float, ux: float, uy: float, theta: float
) -> tuple[float, float]:
    """Campo de desplazamientos de un diafragma rígido (aprox. lineal en θ):
    u(x,y) = ux − θ(y − y_cm) ; v(x,y) = uy + θ(x − x_cm)."""
    dx, dy = px - cm_x, py - cm_y
    return ux - theta * dy, uy + theta * dx


def _deformed_plan_svg(result: dict, level_index: int) -> str:
    """Planta original (punteada) vs. planta desplazada y rotada (sólida)
    para el nivel elegido, con amplificación visual del movimiento."""
    displacements = result["displacements"]
    if not (0 <= level_index < len(displacements)):
        level_index = len(displacements) - 1
    item = displacements[level_index]
    min_x, max_x, min_y, max_y = _footprint_bounds()
    footprint_size = max(max_x - min_x, max_y - min_y, 1.0)
    scale = _deformation_amplifier(displacements, footprint_size)

    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    shifted_corners = []
    for px, py in corners:
        ox, oy = _rigid_diaphragm_offset(
            px, py, analysis_cm_x, analysis_cm_y, item["ux"], item["uy"], item["theta"]
        )
        shifted_corners.append((px + ox * scale, py + oy * scale))
    cm_ox, cm_oy = _rigid_diaphragm_offset(
        analysis_cm_x, analysis_cm_y, analysis_cm_x, analysis_cm_y, item["ux"], item["uy"], item["theta"]
    )
    shifted_cm = (analysis_cm_x + cm_ox * scale, analysis_cm_y + cm_oy * scale)

    all_points = corners + shifted_corners + [(analysis_cm_x, analysis_cm_y), shifted_cm]
    xs = [p[0] for p in all_points]
    ys = [p[1] for p in all_points]
    pad = max(1.0, footprint_size * 0.12)
    view_min_x, view_max_x = min(xs) - pad, max(xs) + pad
    view_min_y, view_max_y = min(ys) - pad, max(ys) + pad

    def map_point(x_value: float, y_value: float) -> tuple[float, float]:
        px = 44.0 + (x_value - view_min_x) / (view_max_x - view_min_x) * 432.0
        py = 260.0 - (y_value - view_min_y) / (view_max_y - view_min_y) * 220.0
        return px, py

    original_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (map_point(*p) for p in corners))
    shifted_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (map_point(*p) for p in shifted_corners))
    cm0 = map_point(analysis_cm_x, analysis_cm_y)
    cm1 = map_point(*shifted_cm)

    parts = [
        '<svg viewBox="0 0 520 300" role="img" aria-label="Planta original y planta deformada">',
        '<rect x="44" y="32" width="432" height="228" rx="6" fill="white" stroke="#e4ebe9"/>',
        f'<polygon class="deform-plan-original" points="{original_pts}"/>',
        f'<polygon class="deform-plan-shifted" points="{shifted_pts}"/>',
        f'<line class="deform-cm-line" x1="{cm0[0]:.1f}" y1="{cm0[1]:.1f}" x2="{cm1[0]:.1f}" y2="{cm1[1]:.1f}" marker-end="url(#deformArrow)"/>',
        f'<circle class="analysis-cm" cx="{cm0[0]:.1f}" cy="{cm0[1]:.1f}" r="6"/>',
        f'<circle class="deform-cm-shifted" cx="{cm1[0]:.1f}" cy="{cm1[1]:.1f}" r="6"/>',
        f'<text class="analysis-cm-label" x="{cm0[0] + 10:.1f}" y="{cm0[1] - 8:.1f}">CM</text>',
        f'<text class="deform-shifted-label" x="{cm1[0] + 10:.1f}" y="{cm1[1] + 16:.1f}">CM\'</text>',
        "<defs><marker id=\"deformArrow\" markerWidth=\"7\" markerHeight=\"7\" refX=\"6\" refY=\"3.5\" orient=\"auto\">"
        '<path class="deform-arrowhead" d="M0,0 L7,3.5 L0,7 Z"/></marker></defs>',
        "</svg>",
    ]
    return "".join(parts), scale


def _deformed_axonometric_svg(result: dict) -> tuple[str, float]:
    """Vista axonométrica de la retícula completa, mostrando la inclinación
    progresiva de cada nivel (modelo de corte apilado)."""
    displacements = result["displacements"]
    heights = analysis_heights[: len(displacements)]
    min_x, max_x, min_y, max_y = _footprint_bounds()
    footprint_size = max(max_x - min_x, max_y - min_y, 1.0)
    scale = _deformation_amplifier(displacements, footprint_size)
    footprint = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]

    iso_mx = (15.5, -8.4)
    iso_my = (-11.2, -6.6)
    px_per_meter_h = 27.0
    bbox: list[tuple[float, float]] = []

    def project(x_m: float, y_m: float, cum_height: float, disp_x: float, disp_y: float) -> tuple[float, float]:
        eff_x = x_m + disp_x * scale
        eff_y = y_m + disp_y * scale
        sx = eff_x * iso_mx[0] + eff_y * iso_my[0]
        sy = eff_x * iso_mx[1] + eff_y * iso_my[1] - cum_height * px_per_meter_h
        bbox.append((sx, sy))
        return sx, sy

    levels_data = [(0.0, 0.0, 0.0)]
    cumulative = 0.0
    for index, item in enumerate(displacements):
        cumulative += heights[index] if index < len(heights) else 0.0
        levels_data.append((item["ux"], item["uy"], cumulative))

    slabs = [
        [project(px, py, cum_h, dux, duy) for px, py in footprint]
        for dux, duy, cum_h in levels_data
    ]

    parts: list[str] = []
    for corner_index in range(4):
        for level_index in range(1, len(slabs)):
            x1, y1 = slabs[level_index - 1][corner_index]
            x2, y2 = slabs[level_index][corner_index]
            parts.append(f'<line class="deform-axo-column" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')

    for level_index, pts in enumerate(slabs):
        css_class = "deform-axo-slab-base" if level_index == 0 else "deform-axo-slab"
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        parts.append(f'<polygon class="{css_class}" points="{points}"/>')
        if level_index > 0:
            label_point = pts[3]
            parts.append(
                f'<text class="deform-axo-label" x="{label_point[0] - 9:.1f}" y="{label_point[1] + 3:.1f}" '
                f'text-anchor="end">N{level_index}</text>'
            )

    padding = 32.0
    min_bx = min(x for x, _ in bbox) - padding
    max_bx = max(x for x, _ in bbox) + padding
    min_by = min(y for _, y in bbox) - padding
    max_by = max(y for _, y in bbox) + padding
    svg = (
        f'<svg viewBox="{min_bx:.1f} {min_by:.1f} {max_bx - min_bx:.1f} {max_by - min_by:.1f}" '
        'role="img" aria-label="Vista axonométrica de la forma deformada">'
        + "".join(parts)
        + "</svg>"
    )
    return svg, scale


def _frame_elevation_svg(result: dict, group_id: str | None) -> str:
    """Elevación 2D de un pórtico: forma deformada del modelo de corte
    (desplazamiento lateral acumulado por nivel) contra la referencia vertical."""
    frame = next((item for item in result["frames"] if str(item["id"]) == str(group_id)), None)
    if frame is None:
        return '<p class="matrix-caption">Selecciona un eje para ver su elevación.</p>'

    local = frame["local_displacements"]
    heights = analysis_heights[: len(local)]
    total_height = sum(heights) or 1.0
    max_disp = max((abs(value) for value in local), default=0.0)
    target_px = 78.0
    x_scale = target_px / max_disp if max_disp > 1e-9 else 0.0
    px_per_meter_h = min(60.0, max(28.0, 260.0 / total_height))

    axis_x0 = 130.0
    nodes = [(axis_x0, 0.0)]
    cumulative = 0.0
    for index, value in enumerate(local):
        cumulative += heights[index] if index < len(heights) else 0.0
        nodes.append((axis_x0 + value * x_scale, cumulative * px_per_meter_h))

    def sy(height_value: float) -> float:
        return 268.0 - height_value

    parts = [
        '<svg viewBox="0 0 260 300" role="img" aria-label="Elevación deformada del pórtico seleccionado">',
        f'<line class="deform-elev-reference" x1="{axis_x0:.1f}" y1="{sy(0):.1f}" x2="{axis_x0:.1f}" y2="{sy(nodes[-1][1]):.1f}"/>',
    ]
    for index in range(len(nodes) - 1):
        x1, h1 = nodes[index]
        x2, h2 = nodes[index + 1]
        parts.append(
            f'<line class="deform-elev-column" x1="{x1:.1f}" y1="{sy(h1):.1f}" x2="{x2:.1f}" y2="{sy(h2):.1f}"/>'
        )
    parts.append(f'{_iso_footing(axis_x0, sy(0))}')
    for index, (x_pos, h_pos) in enumerate(nodes):
        parts.append(f'<circle class="deform-elev-node" cx="{x_pos:.1f}" cy="{sy(h_pos):.1f}" r="4.5"/>')
        if index > 0:
            drift_mm = local[index - 1] * 1000.0
            parts.append(
                f'<text class="deform-elev-label" x="{x_pos + 9:.1f}" y="{sy(h_pos) + 4:.1f}">'
                f'N{index} · {format_number(drift_mm, 2)} mm</text>'
            )
        else:
            parts.append(f'<text class="deform-elev-label" x="{x_pos + 9:.1f}" y="{sy(h_pos) + 4:.1f}">Base</text>')
    parts.append("</svg>")
    return "".join(parts)


def _bar_chart_svg(rows: list[tuple[str, float]], unit: str, bar_class: str = "chart-bar-teal") -> str:
    """Gráfico de barras horizontales genérico para fuerzas, cortantes o momentos."""
    if not rows:
        return '<p class="matrix-caption">Sin datos para graficar.</p>'
    max_value = max((abs(value) for _, value in rows), default=0.0) or 1.0
    row_height = 30.0
    chart_height = row_height * len(rows) + 16.0
    label_width = 62.0
    axis_x = label_width + 8.0
    max_bar_width = 268.0
    parts = [
        f'<svg viewBox="0 0 {label_width + max_bar_width + 96.0:.0f} {chart_height:.0f}" role="img" aria-label="Gráfico de barras">'
    ]
    for index, (label, value) in enumerate(rows):
        row_y = 10.0 + index * row_height
        bar_width = max(1.5, (abs(value) / max_value) * max_bar_width)
        css_class = bar_class if value >= 0 else "chart-bar-negative"
        parts.append(
            f'<text class="chart-row-label" x="{label_width - 8:.1f}" y="{row_y + 13:.1f}" text-anchor="end">{escape(label)}</text>'
        )
        parts.append(f'<rect class="{css_class}" x="{axis_x:.1f}" y="{row_y:.1f}" width="{bar_width:.1f}" height="18" rx="3"/>')
        parts.append(
            f'<text class="chart-value-label" x="{axis_x + bar_width + 8:.1f}" y="{row_y + 13:.1f}">{_compact_number(value)} {unit}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_deformation_views(result: dict) -> None:
    """Puebla los selectores y dibuja planta deformada, axonometría y elevación."""
    global analysis_view_level, analysis_selected_axis_id

    if analysis_view_level is None or not (1 <= analysis_view_level <= analysis_level_count):
        analysis_view_level = analysis_level_count
    if analysis_selected_axis_id is None or not any(group.id == analysis_selected_axis_id for group in groups):
        analysis_selected_axis_id = groups[0].id if groups else None

    level_select = by_id("analysis-deform-level")
    level_select.innerHTML = "".join(
        f'<option value="{level}"{" selected" if level == analysis_view_level else ""}>Nivel {level}</option>'
        for level in range(1, analysis_level_count + 1)
    )

    plan_svg, plan_scale = _deformed_plan_svg(result, analysis_view_level - 1)
    by_id("analysis-deformed-plan").innerHTML = plan_svg
    by_id("analysis-deformed-plan-caption").textContent = (
        f"Nivel {analysis_view_level} · amplificación visual ×{format_number(plan_scale, 0)}"
    )

    axo_svg, axo_scale = _deformed_axonometric_svg(result)
    by_id("analysis-axonometric").innerHTML = axo_svg
    by_id("analysis-axonometric-caption").textContent = (
        f"Amplificación visual ×{format_number(axo_scale, 0)} · alturas de piso a escala real"
    )

    axis_options = "".join(
        f'<option value="{group.id}"{" selected" if group.id == analysis_selected_axis_id else ""}>'
        f"Eje {escape(str(group.axis))} · {escape(direction_label(group.direction))}</option>"
        for group in groups
    )
    by_id("analysis-elevation-axis").innerHTML = axis_options
    by_id("analysis-matrix-axis").innerHTML = axis_options
    by_id("analysis-frame-elevation").innerHTML = _frame_elevation_svg(result, analysis_selected_axis_id)

    selected_frame = next(
        (item for item in result["frames"] if str(item["id"]) == str(analysis_selected_axis_id)), None
    )
    if selected_frame is not None:
        stiffness_unit = "kN/m"
        by_id("analysis-frame-matrix").innerHTML = _local_matrix_development(
            selected_frame, analysis_level_count, stiffness_unit
        )
    else:
        by_id("analysis-frame-matrix").innerHTML = '<p class="matrix-caption">Selecciona un eje para ver su matriz local.</p>'


def render_action_charts(result: dict) -> None:
    """Dibuja fuerzas por piso, cortante de piso y momentos en columna del eje elegido."""
    levels = range(analysis_level_count - 1, -1, -1)

    floor_rows = [(f"Nivel {level + 1}", analysis_forces[level]) for level in levels]
    by_id("analysis-floor-forces-chart").innerHTML = _bar_chart_svg(floor_rows, "kN", "chart-bar-teal")

    shear_rows = [(f"Nivel {level + 1}", sum(analysis_forces[level:])) for level in levels]
    by_id("analysis-story-shear-chart").innerHTML = _bar_chart_svg(shear_rows, "kN", "chart-bar-amber")

    frame = next(
        (item for item in result["frames"] if str(item["id"]) == str(analysis_selected_axis_id)), None
    )
    if frame is not None and all(moment is not None for moment in frame["end_moments"]):
        moment_rows = [(f"Nivel {level + 1}", frame["end_moments"][level]) for level in levels]
        by_id("analysis-column-moment-chart").innerHTML = _bar_chart_svg(moment_rows, "kN·m", "chart-bar-violet")
    else:
        by_id("analysis-column-moment-chart").innerHTML = (
            '<p class="matrix-caption">Este eje no tiene ambos extremos empotrado–rígido, '
            "por lo que no se calcula el momento de extremo Vh/2.</p>"
        )


def _clear_analysis_results(message: str) -> None:
    warning = by_id("analysis-warning")
    warning.hidden = False
    warning.innerHTML = f"<strong>El modelo aún no puede resolverse.</strong>{escape(message)}"
    by_id("analysis-summary").innerHTML = (
        '<div class="analysis-placeholder">Completa una configuración estable: debe existir rigidez en X, en Y y frente al giro. Puedes usar el ejemplo de dos niveles para ver el flujo completo.</div>'
    )
    by_id("analysis-displacements").innerHTML = ""
    by_id("analysis-frames").innerHTML = ""
    _update_details_panel("analysis-steps", ".steps-card", '<p class="matrix-caption">El desarrollo paso a paso aparecerá cuando el sistema tenga estabilidad global.</p>')
    placeholder = '<p class="matrix-caption">Disponible cuando el modelo tenga estabilidad global.</p>'
    by_id("analysis-deformed-plan").innerHTML = placeholder
    by_id("analysis-deformed-plan-caption").textContent = ""
    by_id("analysis-axonometric").innerHTML = placeholder
    by_id("analysis-axonometric-caption").textContent = ""
    by_id("analysis-frame-elevation").innerHTML = placeholder
    by_id("analysis-frame-matrix").innerHTML = placeholder
    by_id("analysis-floor-forces-chart").innerHTML = placeholder
    by_id("analysis-story-shear-chart").innerHTML = placeholder
    by_id("analysis-column-moment-chart").innerHTML = placeholder


def render_analysis_results() -> None:
    by_id("analysis-plan").innerHTML = _analysis_plan_svg()
    try:
        result = analyze_pseudotridimensional(
            groups,
            analysis_heights,
            analysis_forces,
            analysis_alpha,
            analysis_cm_x,
            analysis_cm_y,
            analysis_ecc_x,
            analysis_ecc_y,
            units,
            {
                "X": analysis_stiffness_x,
                "Y": analysis_stiffness_y,
            },
        )
    except ValueError as error:
        _clear_analysis_results(str(error))
        return

    warning = by_id("analysis-warning")
    warning.hidden = True
    warning.textContent = ""
    by_id("analysis-plan").innerHTML = _analysis_plan_svg(result["center_rigidity"])
    displacements = result["displacements"]
    roof = displacements[-1]
    max_drift = max(
        max(abs(item["drift_x"]), abs(item["drift_y"]))
        for item in displacements
    )
    center_rigidity = result["center_rigidity"]
    center_text = (
        f"({format_number(center_rigidity['x'], 3)}; {format_number(center_rigidity['y'], 3)})"
        if center_rigidity is not None
        else "—"
    )
    by_id("analysis-summary").innerHTML = f"""
      <div class="analysis-metric"><span>Techo en X</span><strong>{format_number(roof['ux'] * 1000.0, 3)}</strong><small>mm</small></div>
      <div class="analysis-metric"><span>Techo en Y</span><strong>{format_number(roof['uy'] * 1000.0, 3)}</strong><small>mm</small></div>
      <div class="analysis-metric"><span>Deriva elástica máxima</span><strong>{format_number(max_drift * 1000.0, 4)}</strong><small>‰ · antes de factores normativos</small></div>
      <div class="analysis-metric"><span>Centro de rigidez (x; y)</span><strong>{center_text}</strong><small>m · cuadrado CR en el plano</small></div>
    """

    displacement_rows = []
    for item in reversed(displacements):
        displacement_rows.append(
            f"<tr><td>Nivel {item['level']}</td><td>{format_number(item['ux'] * 1000.0, 4)}</td><td>{format_number(item['uy'] * 1000.0, 4)}</td><td>{format_number(item['theta'] * 1000.0, 5)}</td><td>{format_number(item['drift_x'] * 1000.0, 5)}</td><td>{format_number(item['drift_y'] * 1000.0, 5)}</td></tr>"
        )
    by_id("analysis-displacements").innerHTML = f"""
      <h3>Movimiento de los diafragmas</h3>
      <p>La deriva es el desplazamiento relativo entre niveles dividido entre la altura del piso.</p>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>Nivel</th><th>u<sub>x</sub> (mm)</th><th>u<sub>y</sub> (mm)</th><th>θ (mrad)</th><th>Deriva X (‰)</th><th>Deriva Y (‰)</th></tr></thead><tbody>{''.join(displacement_rows)}</tbody></table></div>
    """

    frame_rows = []
    for frame in result["frames"]:
        for level in range(analysis_level_count - 1, -1, -1):
            moment = frame["end_moments"][level]
            moment_text = "—" if moment is None else format_number(moment, 3)
            frame_rows.append(
                f"<tr><td>Eje {escape(str(frame['axis']))}</td><td>{level + 1}</td><td>{format_number(frame['lever_arms'][level], 3)}</td><td>{format_number(frame['story_shears'][level], 3)}</td><td>{format_number(frame['column_shears'][level], 3)}</td><td>{moment_text}</td></tr>"
            )
    by_id("analysis-frames").innerHTML = f"""
      <h3>Distribución de acciones por eje</h3>
      <p>El cortante de cada eje se reparte entre sus columnas iguales. El momento Vh/2 solo se muestra para uniones empotrada–rígida.</p>
      <div class="table-scroll"><table class="data-table"><thead><tr><th>Eje</th><th>Nivel</th><th>r (m)</th><th>V eje (kN)</th><th>V/col (kN)</th><th>M extremo (kN·m)</th></tr></thead><tbody>{''.join(frame_rows)}</tbody></table></div>
    """

    _update_details_panel("analysis-steps", ".steps-card", _analysis_steps_html(result))

    render_deformation_views(result)
    render_action_charts(result)


def load_level_card(level: LevelLoad, index: int) -> str:
    floor_selected = "" if level.is_roof else " is-selected"
    roof_selected = " is-selected" if level.is_roof else ""
    preset_options = "".join(
        f'<option value="{key}"{" selected" if key == level.use_key else ""}>{escape(label)}</option>'
        for key, (label, _value) in LIVE_LOAD_PRESETS.items()
    )
    label_value = escape(str(level.label), quote=True)
    columns = column_takeoff(level.height)
    beam_volume, beam_weight = beam_takeoff(level)
    story = calculate_story(groups, level.height, units)
    stiffness_conversion = KN_PER_TONF if units == "MKS" else 1.0
    automatic_kx = float(story["totals"]["X"]) * stiffness_conversion
    automatic_ky = float(story["totals"]["Y"]) * stiffness_conversion
    return f"""
    <article class="column-card load-level-card" data-card-id="{level.id}">
      <div class="column-card__head">
        <div><span class="column-code">N{index + 1}</span><div><h3>Nivel {index + 1}</h3><p>{"Techo / azotea" if level.is_roof else "Piso"}</p></div></div>
        <span class="inherited-level-badge">Definido en Rigidez</span>
      </div>
      <div class="form-grid form-grid--compact">
        <div class="field-block">
          <label for="load-label-{level.id}">Etiqueta</label>
          <input id="load-label-{level.id}" type="text" maxlength="24" value="{label_value}" data-level-id="{level.id}" data-field="load-label" />
        </div>
        <fieldset class="field-block shape-field">
          <legend>Tipo</legend>
          <div class="shape-options load-type-options">
            <button type="button" class="shape-option{floor_selected}" data-action="load-roof" data-id="{level.id}" data-value="false">Piso</button>
            <button type="button" class="shape-option{roof_selected}" data-action="load-roof" data-id="{level.id}" data-value="true">Techo</button>
          </div>
        </fieldset>
      </div>
      <div class="form-grid">
        <div class="field-block">
          <label for="load-area-{level.id}">Área tributaria</label>
          <div class="input-with-unit"><input id="load-area-{level.id}" type="number" min="1" step="1" value="{input_number(level.area)}" data-level-id="{level.id}" data-field="load-area" /><span>m²</span></div>
        </div>
        <div class="field-block">
          <label for="load-height-{level.id}">Altura de piso</label>
          <div class="input-with-unit"><input id="load-height-{level.id}" type="number" min="1" max="12" step="0.05" value="{input_number(level.height)}" data-level-id="{level.id}" data-field="load-height" /><span>m</span></div>
        </div>
      </div>
      <div class="form-grid">
        <div class="field-block">
          <label for="load-cm-{level.id}">Carga muerta CM</label>
          <div class="input-with-unit"><input id="load-cm-{level.id}" type="number" min="0" step="0.1" value="{input_number(level.cm)}" data-level-id="{level.id}" data-field="load-cm" /><span>kN/m²</span></div>
          <small>Losa + acabados + tabiquería. No incluyas aquí columnas ni vigas.</small>
        </div>
        <div class="field-block">
          <label for="load-cv-{level.id}">Sobrecarga CV</label>
          <div class="input-with-unit"><input id="load-cv-{level.id}" type="number" min="0" step="0.1" value="{input_number(level.cv)}" data-level-id="{level.id}" data-field="load-cv" /><span>kN/m²</span></div>
        </div>
      </div>
      <div class="field-block">
        <label for="load-preset-{level.id}">Sobrecarga típica (E.020)</label>
        <select id="load-preset-{level.id}" data-level-id="{level.id}" data-field="load-preset">
          <option value=""{" selected" if not level.use_key else ""}>— elegir uso —</option>
          {preset_options}
        </select>
        <small>El uso general ya está aplicado. Usa este selector sólo si el nivel tiene un uso diferente.</small>
      </div>

      <section class="mass-geometry-card" aria-labelledby="mass-geometry-{level.id}">
        <div><strong id="mass-geometry-{level.id}">Geometría de masa del nivel</strong><small>Centro de la losa y de las cargas superficiales</small></div>
        <div class="mass-geometry-fields">
          <div class="field-block"><label for="load-center-x-{level.id}">Centro X₀</label><div class="input-with-unit"><input id="load-center-x-{level.id}" type="number" step="0.1" value="{input_number(level.center_x)}" data-level-id="{level.id}" data-field="load-center-x" /><span>m</span></div></div>
          <div class="field-block"><label for="load-center-y-{level.id}">Centro Y₀</label><div class="input-with-unit"><input id="load-center-y-{level.id}" type="number" step="0.1" value="{input_number(level.center_y)}" data-level-id="{level.id}" data-field="load-center-y" /><span>m</span></div></div>
          <div class="field-block"><label for="load-slab-thickness-{level.id}">Espesor de losa</label><div class="input-with-unit"><input id="load-slab-thickness-{level.id}" type="number" min="0" step="0.01" value="{input_number(level.slab_thickness)}" data-level-id="{level.id}" data-field="load-slab-thickness" /><span>m</span></div></div>
        </div>
        <small>CM incluye el peso de esta losa. El excedente se reporta como acabados y tabiquería.</small>
      </section>

      <section class="irregularity-level-card" aria-labelledby="irregularity-level-{level.id}">
        <div class="element-takeoff-head">
          <div><span aria-hidden="true">K</span><div><strong id="irregularity-level-{level.id}">Datos para irregularidades</strong><small>Tabla 11 · valores de este entrepiso</small></div></div>
          <span>0 en K usa el modelo · 0 en Vn deja sin evaluar</span>
        </div>
        <div class="irregularity-level-fields">
          <div class="field-block"><label for="load-plan-x-{level.id}">Dimensión resistente X</label><div class="input-with-unit"><input id="load-plan-x-{level.id}" type="number" min="0.1" step="0.1" value="{input_number(level.plan_x)}" data-level-id="{level.id}" data-field="load-plan-x" /><span>m</span></div></div>
          <div class="field-block"><label for="load-plan-y-{level.id}">Dimensión resistente Y</label><div class="input-with-unit"><input id="load-plan-y-{level.id}" type="number" min="0.1" step="0.1" value="{input_number(level.plan_y)}" data-level-id="{level.id}" data-field="load-plan-y" /><span>m</span></div></div>
          <div class="field-block"><label for="load-kx-{level.id}">Kx opcional</label><div class="input-with-unit"><input id="load-kx-{level.id}" type="number" min="0" step="100" value="{input_number(level.stiffness_x_override)}" data-level-id="{level.id}" data-field="load-kx" /><span>kN/m</span></div><small>Automática: <output id="load-kx-auto-{level.id}">{format_number(automatic_kx, 1)}</output> kN/m</small></div>
          <div class="field-block"><label for="load-ky-{level.id}">Ky opcional</label><div class="input-with-unit"><input id="load-ky-{level.id}" type="number" min="0" step="100" value="{input_number(level.stiffness_y_override)}" data-level-id="{level.id}" data-field="load-ky" /><span>kN/m</span></div><small>Automática: <output id="load-ky-auto-{level.id}">{format_number(automatic_ky, 1)}</output> kN/m</small></div>
          <div class="field-block"><label for="load-vnx-{level.id}">Resistencia Vn,x</label><div class="input-with-unit"><input id="load-vnx-{level.id}" type="number" min="0" step="10" value="{input_number(level.strength_x)}" data-level-id="{level.id}" data-field="load-vnx" /><span>kN</span></div></div>
          <div class="field-block"><label for="load-vny-{level.id}">Resistencia Vn,y</label><div class="input-with-unit"><input id="load-vny-{level.id}" type="number" min="0" step="10" value="{input_number(level.strength_y)}" data-level-id="{level.id}" data-field="load-vny" /><span>kN</span></div></div>
        </div>
      </section>

      <section class="element-takeoff-card" aria-labelledby="takeoff-{level.id}">
        <div class="element-takeoff-head">
          <div><span aria-hidden="true">▦</span><div><strong id="takeoff-{level.id}">Metrado de elementos</strong><small>Se suma a la carga muerta superficial</small></div></div>
          <span>γ vigas = 24 kN/m³</span>
        </div>
        <div class="column-takeoff-summary">
          <div><strong>Columnas heredadas de Rigidez</strong><small>Considera todos los grupos definidos en la Etapa 1.</small></div>
          <output id="load-columns-summary-{level.id}">{columns['count']} unid. · {format_number(columns['volume'], 3)} m³ · {format_number(columns['weight'], 1)} kN</output>
        </div>
        <div class="beam-takeoff-fields">
          <div class="field-block"><label for="load-beam-count-{level.id}">Cantidad de vigas</label><input id="load-beam-count-{level.id}" type="number" min="0" step="1" value="{level.beam_count}" data-level-id="{level.id}" data-field="load-beam-count" /></div>
          <div class="field-block"><label for="load-beam-width-{level.id}">Ancho b</label><div class="input-with-unit"><input id="load-beam-width-{level.id}" type="number" min="0.05" step="0.05" value="{input_number(level.beam_width)}" data-level-id="{level.id}" data-field="load-beam-width" /><span>m</span></div></div>
          <div class="field-block"><label for="load-beam-depth-{level.id}">Peralte h</label><div class="input-with-unit"><input id="load-beam-depth-{level.id}" type="number" min="0.05" step="0.05" value="{input_number(level.beam_depth)}" data-level-id="{level.id}" data-field="load-beam-depth" /><span>m</span></div></div>
          <div class="field-block"><label for="load-beam-length-{level.id}">Longitud por viga</label><div class="input-with-unit"><input id="load-beam-length-{level.id}" type="number" min="0.1" step="0.1" value="{input_number(level.beam_length)}" data-level-id="{level.id}" data-field="load-beam-length" /><span>m</span></div></div>
          <div class="field-block"><label for="load-beam-center-x-{level.id}">Centro de vigas X₀</label><div class="input-with-unit"><input id="load-beam-center-x-{level.id}" type="number" step="0.1" value="{input_number(level.beam_center_x)}" data-level-id="{level.id}" data-field="load-beam-center-x" /><span>m</span></div></div>
          <div class="field-block"><label for="load-beam-center-y-{level.id}">Centro de vigas Y₀</label><div class="input-with-unit"><input id="load-beam-center-y-{level.id}" type="number" step="0.1" value="{input_number(level.beam_center_y)}" data-level-id="{level.id}" data-field="load-beam-center-y" /><span>m</span></div></div>
        </div>
        <p class="element-takeoff-result">Vigas del nivel: <strong id="load-beams-summary-{level.id}">{level.beam_count} unid. · {format_number(beam_volume, 3)} m³ · {format_number(beam_weight, 1)} kN</strong></p>
      </section>
    </article>
    """


def render_load_levels() -> None:
    by_id("loads-level-list").innerHTML = "".join(
        load_level_card(level, index) for index, level in enumerate(load_levels)
    )
    level_word = "nivel" if len(load_levels) == 1 else "niveles"
    by_id("loads-level-count").textContent = f"{len(load_levels)} {level_word} heredados de Rigidez"


def render_loads_site_inputs() -> None:
    by_id("loads-use-global").value = loads_use_preset
    by_id("loads-zone").value = loads_zone
    by_id("loads-soil").value = loads_soil
    by_id("loads-category").value = loads_category
    by_id("loads-system").value = loads_system
    by_id("loads-ia").textContent = input_number(loads_ia)
    by_id("loads-ip").textContent = input_number(loads_ip)
    by_id("loads-discontinuity-vertical").checked = loads_discontinuity_vertical
    by_id("loads-extreme-discontinuity-vertical").checked = loads_extreme_discontinuity_vertical
    by_id("loads-reentrant-corners").checked = loads_reentrant_corners
    by_id("loads-diaphragm-discontinuity").checked = loads_diaphragm_discontinuity
    by_id("loads-nonparallel-systems").checked = loads_nonparallel_systems
    by_id("loads-period-mode").value = loads_period_mode
    period_input = by_id("loads-period-manual")
    period_input.value = input_number(loads_period_manual)
    period_input.disabled = loads_period_mode != "manual"


def _manual_irregularity_facts() -> IrregularityFacts:
    return IrregularityFacts(
        discontinuity_vertical=loads_discontinuity_vertical,
        extreme_discontinuity_vertical=loads_extreme_discontinuity_vertical,
        reentrant_corners=loads_reentrant_corners,
        diaphragm_discontinuity=loads_diaphragm_discontinuity,
        nonparallel_systems=loads_nonparallel_systems,
    )


def _current_irregularity_assessment() -> dict[str, object]:
    column_rows = [column_takeoff_rows(level.height) for level in load_levels]
    column_weights = [sum(float(row["weight"]) for row in rows) for rows in column_rows]
    weights = [
        level_seismic_weight(level, loads_category, column_weights[index])
        for index, level in enumerate(load_levels)
    ]
    stiffness_x, stiffness_y = _derived_story_stiffnesses()
    facts = _manual_irregularity_facts()
    base_assessment = assess_irregularities(
        load_levels,
        weights,
        stiffness_x,
        stiffness_y,
        [level.strength_x for level in load_levels],
        [level.strength_y for level in load_levels],
        facts,
    )
    base_regular = (
        float(base_assessment["ia"]) == 1.0
        and float(base_assessment["ip"]) == 1.0
    )

    torsion_status = "No evaluada: el modelo necesita ejes estables en X, Y y torsión."
    torsion_cases: list[dict[str, object]] = []
    try:
        regular_site = SeismicSiteParams(
            zone=loads_zone,
            soil=loads_soil,
            category=loads_category,
            system=loads_system,
            irregularity_height=float(base_assessment["ia"]),
            irregularity_plan=float(base_assessment["ip"]),
            period_override=loads_period_manual if loads_period_mode == "manual" else None,
        )
        provisional = static_seismic_forces(
            load_levels,
            regular_site,
            column_weights,
            enforce_minimum_c_over_r=False,
        )
        mass_properties = [
            _level_seismic_mass_properties(level, column_rows[index], loads_category)
            for index, level in enumerate(load_levels)
        ]
        center_x = [item["center_x"] for item in mass_properties]
        center_y = [item["center_y"] for item in mass_properties]
        torsion = assess_torsional_irregularity(
            groups,
            [level.height for level in load_levels],
            provisional.level_forces,
            center_x,
            center_y,
            [level.plan_x for level in load_levels],
            [level.plan_y for level in load_levels],
            0.005 if loads_system == "albanileria" else 0.007,
            units,
            {
                "X": [level.stiffness_x_override for level in load_levels],
                "Y": [level.stiffness_y_override for level in load_levels],
            },
            (0.75 if base_regular else 0.85) * provisional.r,
        )
        facts.torsional = bool(torsion["torsional"])
        facts.extreme_torsional = bool(torsion["extreme_torsional"])
        torsion_cases = list(torsion["cases"])
        torsion_status = (
            "Evaluada automáticamente con ±5% de excentricidad accidental y "
            "desplazamientos amplificados conforme al artículo 50."
        )
    except (ValueError, ZeroDivisionError):
        pass

    assessment = assess_irregularities(
        load_levels,
        weights,
        stiffness_x,
        stiffness_y,
        [level.strength_x for level in load_levels],
        [level.strength_y for level in load_levels],
        facts,
    )
    assessment["torsion_status"] = torsion_status
    assessment["torsion_cases"] = torsion_cases
    status, restriction = irregularity_restriction(
        loads_category,
        loads_zone,
        len(load_levels),
        sum(level.height for level in load_levels),
        assessment,
    )
    assessment["restriction_status"] = status
    assessment["restriction"] = restriction
    total_height = sum(level.height for level in load_levels)
    regular = float(assessment["ia"]) == 1.0 and float(assessment["ip"]) == 1.0
    static_allowed = (
        loads_zone == "1"
        or (regular and total_height <= 30.0)
        or (loads_system in ("muros", "albanileria") and total_height <= 15.0)
    )
    assessment["static_method_allowed"] = static_allowed
    assessment["static_method_note"] = (
        "La generación de fuerzas estáticas es admisible; la combinación direccional 100% + 30% se realiza fuera de este prototipo."
        if static_allowed
        else "El método estático equivalente no satisface el alcance del artículo 33.2; corresponde análisis dinámico modal espectral."
    )
    return assessment


def _build_site_params(assessment: dict[str, object] | None = None) -> SeismicSiteParams:
    if assessment is None:
        assessment = _current_irregularity_assessment()
    manual_period = loads_period_manual if loads_period_mode == "manual" else None
    return SeismicSiteParams(
        zone=loads_zone,
        soil=loads_soil,
        category=loads_category,
        system=loads_system,
        irregularity_height=float(assessment["ia"]),
        irregularity_plan=float(assessment["ip"]),
        period_override=manual_period,
    )


def _loads_steps_html(result, site: SeismicSiteParams) -> str:
    cv_pct = CATEGORY_CV_FACTOR.get(site.category, 0.25) * 100.0
    return f"""
      <div class="step-block">
        <h4><span class="step-badge">1</span>Parámetros de sitio (E.030)</h4>
        <p>Z = {format_number(result.z, 2)} · U = {format_number(result.u, 2)} · S = {format_number(result.s, 2)} · R = {format_number(result.r, 2)} (R₀ · I<sub>a</sub> · I<sub>p</sub>)</p>
        <p>T<sub>P</sub> = {format_number(result.tp, 2)} s · T<sub>L</sub> = {format_number(result.tl, 2)} s · T = {format_number(result.period, 3)} s → C espectral = {format_number(result.c, 3)} · C usado = {format_number(result.c_effective, 3)}</p>
      </div>
      <div class="step-block">
        <h4><span class="step-badge">2</span>Peso sísmico por nivel</h4>
        <p><code>P = CM·A + W_columnas + W_vigas + %CV·CV·A</code>, con %CV = 25% en techos y {format_number(cv_pct, 0)}% en el resto de niveles (categoría {escape(site.category)}).</p>
      </div>
      <div class="step-block">
        <h4><span class="step-badge">3</span>Masa y centro de masa</h4>
        <p><code>m_j = W_j/g</code>, <code>X_CM = Σ(m_j·X_j)/Σm_j</code> y <code>Y_CM = Σ(m_j·Y_j)/Σm_j</code>, usando g = {format_number(GRAVITY_ACCELERATION, 2)} m/s² y la fracción sísmica de la carga viva.</p>
      </div>
      <div class="step-block">
        <h4><span class="step-badge">4</span>Cortante en la base</h4>
        <p><code>V = (Z·U·C·S / R) · ΣP</code>, verificando <code>C/R ≥ 0,11</code>: {format_number(result.base_shear_coefficient, 4)} × {format_number(result.weight_total, 1)} kN = <strong>{format_number(result.base_shear, 1)} kN</strong></p>
      </div>
      <div class="step-block">
        <h4><span class="step-badge">5</span>Distribución en altura</h4>
        <p><code>F_i = V · (P_i · h_i^k) / Σ(P_j · h_j^k)</code>, k = {format_number(result.height_k, 2)}</p>
      </div>
    """


def _mass_cells(properties: dict[str, float]) -> str:
    return (
        f"<td>{format_number(properties['weight'], 2)}</td>"
        f"<td>{format_number(properties['mass'], 3)}</td>"
        f"<td>{format_number(properties['x'], 3)}</td>"
        f"<td>{format_number(properties['y'], 3)}</td>"
        f"<td>{format_number(properties['mx'], 3)}</td>"
        f"<td>{format_number(properties['my'], 3)}</td>"
    )


def _optional_ratio(value: float | None) -> str:
    return "—" if value is None else format_number(value, 3)


def render_irregularity_results(assessment: dict[str, object]) -> None:
    by_id("loads-ia").textContent = format_number(float(assessment["ia"]), 2)
    by_id("loads-ip").textContent = format_number(float(assessment["ip"]), 2)
    check_rows = []
    for item in assessment["checks"]:
        state = "IRREGULAR" if item["active"] else "Regular"
        state_class = "is-irregular" if item["active"] else "is-regular"
        check_rows.append(
            f'<tr><td>{escape(str(item["name"]))}</td><td>{escape(str(item["group"] == "height" and "Altura" or "Planta"))}</td>'
            f'<td>{format_number(float(item["factor"]), 2)}</td><td class="irregularity-state {state_class}">{state}</td>'
            f'<td>{escape(str(item["detail"]))}</td></tr>'
        )

    story_rows = []
    for row in assessment["rows"]:
        story_rows.append(
            f'<tr><td>{escape(str(row["label"]))}</td><td>{format_number(float(row["weight"]), 1)}</td>'
            f'<td>{format_number(float(row["kx"]), 1)}</td><td>{_optional_ratio(row["k_adjacent_x"])}</td><td>{_optional_ratio(row["k_average3_x"])}</td>'
            f'<td>{format_number(float(row["ky"]), 1)}</td><td>{_optional_ratio(row["k_adjacent_y"])}</td><td>{_optional_ratio(row["k_average3_y"])}</td>'
            f'<td>{_optional_ratio(row["strength_ratio_x"])}</td><td>{_optional_ratio(row["strength_ratio_y"])}</td></tr>'
        )

    torsion_cases = [case for case in assessment["torsion_cases"] if case["applicable"]]
    if torsion_cases:
        critical = max(torsion_cases, key=lambda case: float(case["ratio"]))
        torsion_detail = (
            f"Caso crítico: {critical['direction']} · signo {'+' if critical['sign'] > 0 else '−'} · "
            f"N{critical['level']} · Δmax/Δprom = {format_number(float(critical['ratio']), 3)}."
        )
    else:
        torsion_detail = "Ningún caso superó el 50% de la deriva permisible, o el modelo aún no es estable."
    restriction_status = escape(str(assessment["restriction_status"]))
    by_id("loads-irregularity-results").innerHTML = f"""
      <div class="irregularity-verdict irregularity-verdict--{restriction_status}">
        <div><span>Factores gobernantes</span><strong>I<sub>a</sub> = {format_number(float(assessment['ia']), 2)} · I<sub>p</sub> = {format_number(float(assessment['ip']), 2)}</strong></div>
        <p>{escape(str(assessment['restriction']))}<br>{escape(str(assessment['static_method_note']))}</p>
      </div>
      <p class="irregularity-auto-note"><strong>Torsión:</strong> {escape(str(assessment['torsion_status']))} {escape(torsion_detail)}</p>
      <div class="table-scroll"><table class="data-table irregularity-table"><thead><tr><th>Control E.030:2026</th><th>Tipo</th><th>Factor</th><th>Estado</th><th>Resultado / criterio</th></tr></thead><tbody>{''.join(check_rows)}</tbody></table></div>
      <details class="irregularity-details"><summary>Ver ratios numéricos por nivel</summary>
        <div class="table-scroll"><table class="data-table irregularity-story-table"><thead><tr><th>Nivel</th><th>P (kN)</th><th>Kx (kN/m)</th><th>Kx/Ksup.</th><th>Kx/Kprom.3</th><th>Ky (kN/m)</th><th>Ky/Ksup.</th><th>Ky/Kprom.3</th><th>Vnx/Vsup.</th><th>Vny/Vsup.</th></tr></thead><tbody>{''.join(story_rows)}</tbody></table></div>
      </details>
    """


def _floor_takeoff_html(
    level: LevelLoad,
    index: int,
    result,
    column_rows: list[dict[str, object]],
    site: SeismicSiteParams,
) -> tuple[str, dict[str, float]]:
    """Tablas de metrado y centro de masa de un nivel."""

    breakdown = level_gravity_breakdown(level, result.level_column_weights[index])
    beam_volume, beam_weight = beam_takeoff(level)
    beam_mass = component_mass_properties(beam_weight, level.beam_center_x, level.beam_center_y)
    slab_mass = component_mass_properties(breakdown["slab_weight"], level.center_x, level.center_y)
    other_dead_mass = component_mass_properties(
        breakdown["other_surface_dead"], level.center_x, level.center_y
    )
    live_factor = ROOF_CV_FACTOR if level.is_roof else CATEGORY_CV_FACTOR.get(site.category, 0.25)
    live_mass_full = component_mass_properties(breakdown["live_total"], level.center_x, level.center_y)
    live_mass_participating = component_mass_properties(
        breakdown["live_total"], level.center_x, level.center_y, live_factor
    )
    seismic_components = [dict(row) for row in column_rows]
    seismic_components.extend((beam_mass, slab_mass, other_dead_mass, live_mass_participating))
    mass_total = combine_mass_properties(seismic_components)

    column_table_rows = []
    for row in column_rows:
        shape_text = str(row["shape"])
        dimension_prefix = "Ø" if shape_text == "circular" else "a ="
        column_table_rows.append(
            f"<tr><td>{row['number']}</td><td>{escape(str(row['description']))}</td>"
            f"<td>{row['quantity']}</td><td>{escape(shape_text.capitalize())}</td>"
            f"<td>{dimension_prefix} {format_number(float(row['dimension']), 3)}</td>"
            f"<td>{format_number(float(row['height']), 2)}</td>"
            f"<td>{format_number(float(row['unit_weight']), 1)}</td>"
            f"<td>{format_number(float(row['volume']), 3)}</td>{_mass_cells(row)}</tr>"
        )
    column_volume = sum(float(row["volume"]) for row in column_rows)
    column_mass_total = combine_mass_properties([dict(row) for row in column_rows])

    beam_row = f"""
      <tr><td>1</td><td>Vigas del nivel</td><td>{level.beam_count}</td>
      <td>{format_number(level.beam_length, 2)}</td><td>{format_number(level.beam_width, 3)}</td>
      <td>{format_number(level.beam_depth, 3)}</td><td>{format_number(CONCRETE_UNIT_WEIGHT, 1)}</td>
      <td>{format_number(beam_volume, 3)}</td>{_mass_cells(beam_mass)}</tr>
    """
    slab_row = f"""
      <tr><td>1</td><td>Losa del nivel</td><td>{format_number(level.area, 2)}</td>
      <td>{format_number(level.slab_thickness, 3)}</td><td>{format_number(CONCRETE_UNIT_WEIGHT, 1)}</td>
      <td>{format_number(breakdown['slab_volume'], 3)}</td>{_mass_cells(slab_mass)}</tr>
    """
    other_dead_intensity = breakdown["other_surface_dead"] / level.area if level.area else 0.0
    other_dead_row = f"""
      <tr><td>1</td><td>Acabados y tabiquería</td><td>{format_number(level.area, 2)}</td>
      <td>{format_number(other_dead_intensity, 3)}</td>{_mass_cells(other_dead_mass)}</tr>
    """
    live_row = f"""
      <tr><td>1</td><td>Sobrecarga de uso</td><td>{format_number(level.area, 2)}</td>
      <td>{format_number(level.cv, 3)}</td>{_mass_cells(live_mass_full)}
      <td>{format_number(live_factor * 100.0, 0)}%</td></tr>
    """
    open_attribute = " open" if index == 0 else ""
    html = f"""
      <details class="floor-takeoff-detail"{open_attribute}>
        <summary>
          <div><span>N{index + 1}</span><div><strong>{escape(str(level.label))}</strong><small>{"Techo / azotea" if level.is_roof else "Piso"} · metrado y masa</small></div></div>
          <div><span>CM = ({format_number(mass_total['center_x'], 3)} ; {format_number(mass_total['center_y'], 3)}) m</span><b>ver detalle</b></div>
        </summary>
        <div class="floor-takeoff-body">
          <div class="takeoff-mass-summary">
            <div><span>Peso sísmico P<sub>i</sub></span><strong>{format_number(result.level_weights[index], 2)} kN</strong></div>
            <div><span>Masa sísmica</span><strong>{format_number(mass_total['mass'], 3)} t</strong></div>
            <div><span>Centro de masa X<sub>CM</sub></span><strong>{format_number(mass_total['center_x'], 3)} m</strong></div>
            <div><span>Centro de masa Y<sub>CM</sub></span><strong>{format_number(mass_total['center_y'], 3)} m</strong></div>
          </div>

          <section class="takeoff-table-section">
            <div><h4>Columnas</h4><span>Una fila por grupo definido en Rigidez</span></div>
            <div class="table-scroll"><table class="data-table detailed-takeoff-table"><thead><tr><th>N°</th><th>Descripción</th><th>Cant.</th><th>Sección</th><th>Dim. (m)</th><th>Altura (m)</th><th>γ (kN/m³)</th><th>Vol. (m³)</th><th>Peso (kN)</th><th>Masa (t)</th><th>X₀ (m)</th><th>Y₀ (m)</th><th>M·X (t·m)</th><th>M·Y (t·m)</th></tr></thead><tbody>{''.join(column_table_rows)}</tbody><tfoot><tr><th colspan="7">Total columnas</th><td>{format_number(column_volume, 3)}</td><td>{format_number(column_mass_total['weight'], 2)}</td><td>{format_number(column_mass_total['mass'], 3)}</td><td>—</td><td>—</td><td>{format_number(column_mass_total['mx'], 3)}</td><td>{format_number(column_mass_total['my'], 3)}</td></tr></tfoot></table></div>
          </section>

          <section class="takeoff-table-section">
            <div><h4>Vigas</h4><span>Grupo típico ingresado para este nivel</span></div>
            <div class="table-scroll"><table class="data-table detailed-takeoff-table"><thead><tr><th>N°</th><th>Descripción</th><th>Cant.</th><th>Largo (m)</th><th>Ancho (m)</th><th>Peralte (m)</th><th>γ (kN/m³)</th><th>Vol. (m³)</th><th>Peso (kN)</th><th>Masa (t)</th><th>X₀ (m)</th><th>Y₀ (m)</th><th>M·X (t·m)</th><th>M·Y (t·m)</th></tr></thead><tbody>{beam_row}</tbody><tfoot><tr><th colspan="7">Total vigas</th><td>{format_number(beam_volume, 3)}</td><td>{format_number(beam_mass['weight'], 2)}</td><td>{format_number(beam_mass['mass'], 3)}</td><td>—</td><td>—</td><td>{format_number(beam_mass['mx'], 3)}</td><td>{format_number(beam_mass['my'], 3)}</td></tr></tfoot></table></div>
          </section>

          <section class="takeoff-table-section">
            <div><h4>Losa</h4><span>Peso propio calculado con γ = {format_number(CONCRETE_UNIT_WEIGHT, 1)} kN/m³</span></div>
            <div class="table-scroll"><table class="data-table detailed-takeoff-table"><thead><tr><th>N°</th><th>Descripción</th><th>Área (m²)</th><th>Espesor (m)</th><th>γ (kN/m³)</th><th>Vol. (m³)</th><th>Peso (kN)</th><th>Masa (t)</th><th>X₀ (m)</th><th>Y₀ (m)</th><th>M·X (t·m)</th><th>M·Y (t·m)</th></tr></thead><tbody>{slab_row}</tbody><tfoot><tr><th colspan="5">Total losa</th><td>{format_number(breakdown['slab_volume'], 3)}</td><td>{format_number(slab_mass['weight'], 2)}</td><td>{format_number(slab_mass['mass'], 3)}</td><td>—</td><td>—</td><td>{format_number(slab_mass['mx'], 3)}</td><td>{format_number(slab_mass['my'], 3)}</td></tr></tfoot></table></div>
          </section>

          <section class="takeoff-table-section takeoff-table-section--paired">
            <div class="takeoff-paired-table"><div><h4>Carga muerta adicional</h4><span>CM menos el peso propio de la losa</span></div><div class="table-scroll"><table class="data-table detailed-takeoff-table"><thead><tr><th>N°</th><th>Descripción</th><th>Área (m²)</th><th>q (kN/m²)</th><th>Peso (kN)</th><th>Masa (t)</th><th>X₀ (m)</th><th>Y₀ (m)</th><th>M·X (t·m)</th><th>M·Y (t·m)</th></tr></thead><tbody>{other_dead_row}</tbody><tfoot><tr><th colspan="4">Total carga muerta adicional</th><td>{format_number(other_dead_mass['weight'], 2)}</td><td>{format_number(other_dead_mass['mass'], 3)}</td><td>—</td><td>—</td><td>{format_number(other_dead_mass['mx'], 3)}</td><td>{format_number(other_dead_mass['my'], 3)}</td></tr></tfoot></table></div></div>
            <div class="takeoff-paired-table"><div><h4>Carga viva</h4><span>La participación indicada se usa en la masa sísmica</span></div><div class="table-scroll"><table class="data-table detailed-takeoff-table"><thead><tr><th>N°</th><th>Descripción</th><th>Área (m²)</th><th>q (kN/m²)</th><th>Peso (kN)</th><th>Masa total (t)</th><th>X₀ (m)</th><th>Y₀ (m)</th><th>M·X (t·m)</th><th>M·Y (t·m)</th><th>% E.030</th></tr></thead><tbody>{live_row}</tbody><tfoot><tr><th colspan="4">Total carga viva</th><td>{format_number(live_mass_full['weight'], 2)}</td><td>{format_number(live_mass_full['mass'], 3)}</td><td>—</td><td>—</td><td>{format_number(live_mass_full['mx'], 3)}</td><td>{format_number(live_mass_full['my'], 3)}</td><td>{format_number(live_factor * 100.0, 0)}%</td></tr></tfoot></table></div></div>
          </section>
          <p class="takeoff-gravity-note">Conversión de peso a masa: m = W / g, con g = {format_number(GRAVITY_ACCELERATION, 2)} m/s². Para X<sub>CM</sub>,Y<sub>CM</sub> se usa la masa sísmica, incluida la fracción de carga viva que corresponde.</p>
        </div>
      </details>
    """
    return html, mass_total


def render_loads_results() -> None:
    global loads_ia, loads_ip
    warning = by_id("loads-warning")
    column_rows_by_level = [column_takeoff_rows(level.height) for level in load_levels]
    column_takeoffs = column_takeoffs_for_levels()
    column_weights = [float(item["weight"]) for item in column_takeoffs]
    for level, takeoff in zip(load_levels, column_takeoffs):
        column_summary = by_id(f"load-columns-summary-{level.id}")
        if column_summary is not None:
            column_summary.textContent = (
                f"{takeoff['count']} unid. · {format_number(takeoff['volume'], 3)} m³ · "
                f"{format_number(takeoff['weight'], 1)} kN"
            )
        beam_summary = by_id(f"load-beams-summary-{level.id}")
        if beam_summary is not None:
            beam_volume, beam_weight = beam_takeoff(level)
            beam_summary.textContent = (
                f"{level.beam_count} unid. · {format_number(beam_volume, 3)} m³ · "
                f"{format_number(beam_weight, 1)} kN"
            )
    try:
        if not load_levels:
            raise ValueError("Agrega al menos un nivel para calcular el metrado.")
        assessment = _current_irregularity_assessment()
        loads_ia = float(assessment["ia"])
        loads_ip = float(assessment["ip"])
        site = _build_site_params(assessment)
        result = static_seismic_forces(load_levels, site, column_weights)
    except (ValueError, ZeroDivisionError) as error:
        warning.hidden = False
        warning.textContent = str(error)
        by_id("loads-summary").innerHTML = (
            '<div class="analysis-placeholder">Completa los datos del metrado para calcular el peso sísmico.</div>'
        )
        by_id("loads-weight-chart").innerHTML = ""
        by_id("loads-force-chart").innerHTML = ""
        by_id("loads-table").innerHTML = ""
        by_id("loads-irregularity-results").innerHTML = (
            '<div class="analysis-placeholder">Completa datos válidos para evaluar las irregularidades.</div>'
        )
        _update_details_panel("loads-steps", ".steps-card", "")
        return

    warning.hidden = True
    warning.textContent = ""
    render_irregularity_results(assessment)

    period_source = "estimado T = hn/CT" if loads_period_mode == "auto" else "manual"
    by_id("loads-summary").innerHTML = f"""
      <div class="analysis-metric"><span>Peso sísmico total ΣP</span><strong>{format_number(result.weight_total, 1)}</strong><small>kN</small></div>
      <div class="analysis-metric"><span>Cortante basal V</span><strong>{format_number(result.base_shear, 1)}</strong><small>kN</small></div>
      <div class="analysis-metric"><span>Periodo T</span><strong>{format_number(result.period, 3)}</strong><small>s · {period_source}</small></div>
      <div class="analysis-metric"><span>Coef. Z·U·C·S/R</span><strong>{format_number(result.base_shear_coefficient, 4)}</strong><small>C usado = {format_number(result.c_effective, 3)} · k = {format_number(result.height_k, 2)}</small></div>
    """

    order = list(reversed(range(len(load_levels))))
    weight_rows = [(f"Nivel {index + 1}", result.level_weights[index]) for index in order]
    by_id("loads-weight-chart").innerHTML = _bar_chart_svg(weight_rows, "kN", "chart-bar-amber")

    force_rows = [(f"Nivel {index + 1}", result.level_forces[index]) for index in order]
    by_id("loads-force-chart").innerHTML = _bar_chart_svg(force_rows, "kN", "chart-bar-teal")

    takeoff_cards = []
    mass_properties_by_level: list[dict[str, float]] = []
    for index, level in enumerate(load_levels):
        card_html, mass_properties = _floor_takeoff_html(
            level, index, result, column_rows_by_level[index], site
        )
        takeoff_cards.append(card_html)
        mass_properties_by_level.append(mass_properties)

    seismic_rows = []
    cumulative_shear = 0.0
    for index in order:
        level = load_levels[index]
        cumulative_shear += result.level_forces[index]
        mass_properties = mass_properties_by_level[index]
        seismic_rows.append(
            f"<tr><td>{escape(str(level.label))}</td><td>{format_number(level.area, 1)}</td>"
            f"<td>{format_number(result.level_weights[index], 1)}</td>"
            f"<td>{format_number(mass_properties['mass'], 3)}</td>"
            f"<td>{format_number(mass_properties['center_x'], 3)}</td>"
            f"<td>{format_number(mass_properties['center_y'], 3)}</td>"
            f"<td>{format_number(result.level_forces[index], 1)}</td>"
            f"<td>{format_number(cumulative_shear, 1)}</td></tr>"
        )
    by_id("loads-table").innerHTML = f"""
      <h3>Metrado de cargas y centro de masa por piso</h3>
      <p>Abre un nivel para revisar columnas, vigas, losa, carga muerta, carga viva y sus momentos de masa.</p>
      <div class="floor-takeoff-list">{"".join(takeoff_cards)}</div>
      <h3 class="secondary-table-title">Resumen sísmico por nivel</h3>
      <p>El centro de masa se obtiene con X<sub>CM</sub> = Σ(M·X)/ΣM y Y<sub>CM</sub> = Σ(M·Y)/ΣM. El cortante se acumula de techo a base.</p>
      <div class="table-scroll"><table class="data-table seismic-summary-table"><thead><tr><th>Nivel</th><th>Área (m²)</th><th>P (kN)</th><th>Masa (t)</th><th>X<sub>CM</sub> (m)</th><th>Y<sub>CM</sub> (m)</th><th>F (kN)</th><th>V acumulado (kN)</th></tr></thead><tbody>{"".join(seismic_rows)}</tbody></table></div>
    """

    _update_details_panel("loads-steps", ".steps-card", _loads_steps_html(result, site))


def configure_building_levels(levels: int, render: bool = True) -> None:
    """Mantiene una sola cantidad de niveles para Rigidez, Metrado y Análisis."""

    global next_load_level_number, analysis_level_count
    global analysis_heights, analysis_forces
    global analysis_stiffness_x, analysis_stiffness_y

    target = max(1, min(12, int(levels)))

    if not load_levels:
        load_levels.append(
            LevelLoad(
                id=f"lv{next_load_level_number}",
                label="Azotea",
                area=200.0,
                cm=5.0,
                cv=live_load_preset("azotea_no_transitable"),
                height=story_height,
                is_roof=True,
                use_key="azotea_no_transitable",
            )
        )
        next_load_level_number += 1

    roof = next((level for level in reversed(load_levels) if level.is_roof), load_levels[-1])
    regular_levels = [level for level in load_levels if level is not roof]
    for level in regular_levels:
        level.is_roof = False
    roof.is_roof = True
    roof.use_key = "azotea_no_transitable"
    roof.cv = live_load_preset(roof.use_key)
    load_levels[:] = regular_levels + [roof]

    while len(load_levels) > target:
        load_levels.pop(-2 if len(load_levels) > 1 else -1)

    while len(load_levels) < target:
        insertion_index = len(load_levels) - 1
        reference = load_levels[0] if len(load_levels) > 1 else roof
        load_levels.insert(
            insertion_index,
            LevelLoad(
                id=f"lv{next_load_level_number}",
                label=f"Nivel {insertion_index + 1}",
                area=reference.area,
                cm=6.5,
                cv=live_load_preset(loads_use_preset),
                height=story_height,
                is_roof=False,
                use_key=loads_use_preset,
                center_x=reference.center_x,
                center_y=reference.center_y,
                plan_x=reference.plan_x,
                plan_y=reference.plan_y,
            ),
        )
        next_load_level_number += 1

    previous_forces = list(analysis_forces)
    analysis_level_count = target
    analysis_heights = [level.height for level in load_levels]
    analysis_forces = [
        previous_forces[index] if index < len(previous_forces) else 100.0 * (index + 1)
        for index in range(target)
    ]
    analysis_stiffness_x = [level.stiffness_x_override for level in load_levels]
    analysis_stiffness_y = [level.stiffness_y_override for level in load_levels]

    if render:
        render_load_levels()
        render_loads_results()
        render_analysis_inputs()
        render_analysis_results()


def add_load_level() -> None:
    """Compatibilidad interna: la interfaz cambia los niveles desde Rigidez."""

    configure_building_levels(len(load_levels) + 1)


def apply_loads_to_analysis() -> None:
    """Copia el peso sísmico calculado hacia la Etapa 3 (Análisis)."""
    global analysis_level_count, analysis_heights, analysis_forces, analysis_alpha
    global analysis_stiffness_x, analysis_stiffness_y
    global analysis_cm_x, analysis_cm_y, analysis_ecc_x, analysis_ecc_y
    try:
        assessment = _current_irregularity_assessment()
        site = _build_site_params(assessment)
        column_weights = [float(item["weight"]) for item in column_takeoffs_for_levels()]
        result = static_seismic_forces(load_levels, site, column_weights)
    except (ValueError, ZeroDivisionError):
        return
    count = min(len(load_levels), 12)
    analysis_level_count = count
    analysis_heights = [level.height for level in load_levels[:count]]
    analysis_forces = [result.level_forces[index] for index in range(count)]
    analysis_stiffness_x = [
        level.stiffness_x_override for level in load_levels[:count]
    ]
    analysis_stiffness_y = [
        level.stiffness_y_override for level in load_levels[:count]
    ]
    level_rows = [column_takeoff_rows(level.height) for level in load_levels[:count]]
    level_masses = [
        _level_seismic_mass_properties(level, level_rows[index], loads_category)
        for index, level in enumerate(load_levels[:count])
    ]
    total_mass = sum(item["mass"] for item in level_masses)
    if total_mass > 0:
        analysis_cm_x = sum(item["mass"] * item["center_x"] for item in level_masses) / total_mass
        analysis_cm_y = sum(item["mass"] * item["center_y"] for item in level_masses) / total_mass
    analysis_alpha = 0.0
    average_plan_y = sum(
        level_masses[index]["mass"] * load_levels[index].plan_y for index in range(count)
    ) / total_mass if total_mass > 0 else load_levels[0].plan_y
    analysis_ecc_x = 0.0
    analysis_ecc_y = 0.05 * average_plan_y
    render_analysis_inputs()
    render_analysis_results()
    set_stage("analysis")


STAGE_INTRO = {
    "rigidity": {
        "title": "SismoLab · Rigidez lateral",
        "eyebrow": "RIGIDEZ LATERAL · MODELO DE CORTE",
        "heading": "Rigidez lateral del entrepiso",
        "copy": "Calcula el aporte elástico de columnas cuadradas y circulares de concreto armado, mostrando el procedimiento para comprobarlo a mano.",
        "note_title": "Hipótesis principal",
        "note_copy": "Viga o losa infinitamente rígida; los giros dependen de las conexiones seleccionadas.",
    },
    "loads": {
        "title": "SismoLab · Metrado de cargas",
        "eyebrow": "METRADO DE CARGAS · E.020 / E.030",
        "heading": "Metrado, centro de masa y fuerza por nivel",
        "copy": "Desglosa columnas, vigas, losa, cargas muertas y vivas para obtener el peso, el centro de masa y la fuerza sísmica de cada piso.",
        "note_title": "Método actual",
        "note_copy": "Metrado por componentes y método estático equivalente (E.030), con %CV según categoría de edificación.",
    },
    "analysis": {
        "title": "SismoLab · Análisis estructural",
        "eyebrow": "ANÁLISIS ESTRUCTURAL · DIAFRAGMA RÍGIDO",
        "heading": "Análisis pseudotridimensional del edificio",
        "copy": "Combina la rigidez de los ejes, su posición en planta y las fuerzas por nivel para obtener desplazamientos, giros y cortantes.",
        "note_title": "Modelo actual",
        "note_copy": "Tres grados de libertad por nivel y comportamiento elástico lineal.",
    },
}


def set_stage(stage: str) -> None:
    global current_stage
    if stage not in ("rigidity", "loads", "analysis"):
        return
    current_stage = stage

    stage_ids = {"rigidity": "rigidity-stage", "loads": "loads-stage", "analysis": "analysis-stage"}
    buttons = {name: by_id(f"stage-{name}-button") for name in stage_ids}
    for name, element_id in stage_ids.items():
        by_id(element_id).hidden = name != stage
    for name, button in buttons.items():
        active = name == stage
        button.classList.toggle("is-active", active)
        if active:
            button.setAttribute("aria-current", "step")
        else:
            button.removeAttribute("aria-current")

    info = STAGE_INTRO[stage]
    document.title = info["title"]
    by_id("intro-eyebrow").textContent = info["eyebrow"]
    by_id("intro-title").textContent = info["heading"]
    by_id("intro-copy").textContent = info["copy"]
    by_id("model-note-title").textContent = info["note_title"]
    by_id("model-note-copy").textContent = info["note_copy"]

    if stage == "loads":
        render_loads_site_inputs()
        render_load_levels()
        render_loads_results()
    elif stage == "analysis":
        render_analysis_inputs()
        render_analysis_results()


def resize_analysis_levels(levels: int) -> None:
    configure_building_levels(levels)


def load_analysis_example() -> None:
    global units, groups, next_group_number, analysis_level_count
    global analysis_heights, analysis_forces, analysis_alpha
    global analysis_stiffness_x, analysis_stiffness_y
    global analysis_cm_x, analysis_cm_y, analysis_ecc_x, analysis_ecc_y
    units = "SI"
    configure_building_levels(2, render=False)
    analysis_level_count = 2
    analysis_heights = [3.0, 3.0]
    analysis_forces = [100.0, 200.0]
    analysis_stiffness_x = [0.0, 0.0]
    analysis_stiffness_y = [0.0, 0.0]
    analysis_alpha = 0.0
    analysis_cm_x, analysis_cm_y = 2.5, 2.0
    analysis_ecc_x, analysis_ecc_y = 0.0, 0.0
    common = {
        "quantity": 2,
        "shape": "square",
        "dimension": 300.0,
        "fc": 21.0,
        "base": "fixed",
        "top": "fixed",
        "material": "concrete",
    }
    groups = [
        ColumnGroup(id="c1", direction="X", axis="A", x0=2.5, y0=0.0, beta=0.0, **common),
        ColumnGroup(id="c2", direction="X", axis="B", x0=2.5, y0=4.0, beta=0.0, **common),
        ColumnGroup(id="c3", direction="Y", axis="C", x0=0.0, y0=2.0, beta=90.0, **common),
        ColumnGroup(id="c4", direction="Y", axis="D", x0=5.0, y0=2.0, beta=90.0, **common),
    ]
    next_group_number = 5
    render_unit_toggle()
    render_groups()
    render_results()
    render_load_levels()
    render_loads_results()
    render_analysis_inputs()
    render_analysis_results()


def render_unit_toggle() -> None:
    for system in ("SI", "MKS"):
        button = by_id(f"units-{system.lower()}")
        active = units == system
        button.classList.toggle("is-active", active)
        button.setAttribute("aria-pressed", "true" if active else "false")


def change_units(target: str) -> None:
    global units, groups
    if target == units or target not in ("SI", "MKS"):
        return
    try:
        groups = [convert_group_units(group, units, target) for group in groups]
    except ValueError as error:
        show_warning(f"Corrige los datos antes de cambiar de unidades. {error}")
        return
    units = target
    render_unit_toggle()
    render_groups()
    render_results()
    render_loads_results()
    render_analysis_results()


def add_group() -> None:
    global next_group_number
    if len(groups) >= 8:
        return
    shape = "circle" if len(groups) % 2 else "square"
    groups.append(
        ColumnGroup(
            id=f"c{next_group_number}",
            quantity=1,
            shape=shape,
            dimension=400.0 if units == "SI" else 40.0,
            fc=21.0 if units == "SI" else 210.0,
            base="fixed",
            top="fixed",
            material="concrete",
            direction="X",
            axis=str(next_group_number),
            x0=0.0,
            y0=float(next_group_number - 1) * 4.0,
            beta=0.0,
        )
    )
    next_group_number += 1
    render_groups()
    render_results()
    render_loads_results()
    render_analysis_inputs()
    render_analysis_results()


def reset() -> None:
    global units, story_height, groups, next_group_number, analysis_level_count
    global analysis_heights, analysis_forces, analysis_alpha
    global analysis_stiffness_x, analysis_stiffness_y
    global analysis_cm_x, analysis_cm_y, analysis_ecc_x, analysis_ecc_y
    global load_levels, next_load_level_number
    global loads_use_preset, loads_zone, loads_soil, loads_category, loads_system
    global loads_ia, loads_ip, loads_period_mode, loads_period_manual
    global loads_discontinuity_vertical, loads_extreme_discontinuity_vertical
    global loads_reentrant_corners, loads_diaphragm_discontinuity, loads_nonparallel_systems
    units = "SI"
    story_height = 3.0
    next_group_number = 2
    analysis_level_count = 2
    analysis_heights = [3.0, 3.0]
    analysis_forces = [100.0, 200.0]
    analysis_stiffness_x = [0.0, 0.0]
    analysis_stiffness_y = [0.0, 0.0]
    analysis_alpha = 0.0
    analysis_cm_x, analysis_cm_y = 2.5, 2.0
    analysis_ecc_x, analysis_ecc_y = 0.0, 0.0
    groups = [ColumnGroup("c1", 2, "square", 300.0, 21.0, "fixed", "fixed", "concrete", "X", "1", 0.0, 0.0, 0.0)]
    load_levels = [
        LevelLoad(id="lv1", label="Nivel 1", area=200.0, cm=6.5, cv=2.0, height=3.0, is_roof=False, use_key="vivienda"),
        LevelLoad(id="lv2", label="Azotea", area=200.0, cm=5.0, cv=1.0, height=3.0, is_roof=True, use_key="azotea_no_transitable"),
    ]
    next_load_level_number = 3
    loads_use_preset = "vivienda"
    loads_zone, loads_soil, loads_category, loads_system = "3", "S2", "C", "muros"
    loads_ia, loads_ip = 1.0, 1.0
    loads_discontinuity_vertical = False
    loads_extreme_discontinuity_vertical = False
    loads_reentrant_corners = False
    loads_diaphragm_discontinuity = False
    loads_nonparallel_systems = False
    loads_period_mode, loads_period_manual = "auto", 0.30
    by_id("story-height").value = "3"
    render_unit_toggle()
    render_groups()
    render_results()
    render_load_levels()
    render_loads_site_inputs()
    render_loads_results()
    render_analysis_inputs()
    render_analysis_results()
    set_stage("rigidity")


@when("click", "#calculator")
def handle_click(event):
    action_element = event.target.closest("[data-action]")
    if not hasattr(action_element, "getAttribute"):
        return
    action = str(action_element.getAttribute("data-action"))
    if action == "units":
        change_units(str(action_element.getAttribute("data-value")))
    elif action == "toggle-details":
        toggle_details_panel(str(action_element.getAttribute("data-target")))
    elif action == "stage":
        set_stage(str(action_element.getAttribute("data-value")))
    elif action == "load-analysis-example":
        load_analysis_example()
    elif action == "add":
        add_group()
    elif action == "reset":
        reset()
    elif action == "remove":
        group_id = str(action_element.getAttribute("data-id"))
        if len(groups) > 1:
            groups[:] = [group for group in groups if group.id != group_id]
            render_groups()
            render_results()
            render_loads_results()
            render_analysis_inputs()
            render_analysis_results()
    elif action == "shape":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.shape = str(action_element.getAttribute("data-value"))
            render_groups()
            render_results()
            render_loads_results()
            render_analysis_results()
    elif action == "material":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.material = str(action_element.getAttribute("data-value"))
            render_groups()
            render_results()
            render_loads_results()
            render_analysis_results()
    elif action == "direction":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.direction = str(action_element.getAttribute("data-value"))
            group.beta = 0.0 if group.direction == "X" else 90.0
            render_groups()
            render_results()
            render_loads_results()
            render_analysis_results()
    elif action == "load-roof":
        level_id = str(action_element.getAttribute("data-id"))
        level = get_load_level(level_id)
        if level is not None:
            make_roof = str(action_element.getAttribute("data-value")) == "true"
            if make_roof:
                for other_level in load_levels:
                    other_level.is_roof = False
                    if other_level is not level:
                        other_level.use_key = loads_use_preset
                        other_level.cv = live_load_preset(loads_use_preset)
                level.is_roof = True
                level.use_key = "azotea_no_transitable"
                level.cv = live_load_preset(level.use_key)
                load_levels.remove(level)
                load_levels.append(level)
            configure_building_levels(len(load_levels))
    elif action == "apply-loads":
        apply_loads_to_analysis()


@when("input", "#calculator")
def handle_input(event):
    global story_height, analysis_alpha, analysis_cm_x, analysis_cm_y
    global analysis_ecc_x, analysis_ecc_y
    target = event.target
    field = target.getAttribute("data-field")
    if field is None:
        return
    field = str(field)
    if field == "story-height":
        story_height = parse_number(target.value)
        for level in load_levels:
            level.height = story_height
        analysis_heights[:] = [story_height] * analysis_level_count
        render_results()
        render_loads_results()
        render_analysis_results()
        return
    if field == "analysis-height":
        level = int(str(target.getAttribute("data-level")))
        analysis_heights[level] = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-force":
        level = int(str(target.getAttribute("data-level")))
        analysis_forces[level] = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-alpha":
        analysis_alpha = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-cm-x":
        analysis_cm_x = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-cm-y":
        analysis_cm_y = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-ecc-x":
        analysis_ecc_x = parse_number(target.value)
        render_analysis_results()
        return
    if field == "analysis-ecc-y":
        analysis_ecc_y = parse_number(target.value)
        render_analysis_results()
        return
    if field == "loads-period-manual":
        global loads_period_manual
        loads_period_manual = parse_number(target.value, 0.3)
        render_loads_results()
        return
    if field in (
        "load-area",
        "load-cm",
        "load-cv",
        "load-height",
        "load-label",
        "load-beam-count",
        "load-beam-width",
        "load-beam-depth",
        "load-beam-length",
        "load-slab-thickness",
        "load-center-x",
        "load-center-y",
        "load-beam-center-x",
        "load-beam-center-y",
        "load-plan-x",
        "load-plan-y",
        "load-kx",
        "load-ky",
        "load-vnx",
        "load-vny",
    ):
        level = get_load_level(str(target.getAttribute("data-level-id")))
        if level is None:
            return
        if field == "load-label":
            level.label = str(target.value)[:24]
        elif field == "load-beam-count":
            level.beam_count = max(0, int(parse_number(target.value)))
        else:
            attribute = {
                "load-area": "area",
                "load-cm": "cm",
                "load-cv": "cv",
                "load-height": "height",
                "load-beam-width": "beam_width",
                "load-beam-depth": "beam_depth",
                "load-beam-length": "beam_length",
                "load-slab-thickness": "slab_thickness",
                "load-center-x": "center_x",
                "load-center-y": "center_y",
                "load-beam-center-x": "beam_center_x",
                "load-beam-center-y": "beam_center_y",
                "load-plan-x": "plan_x",
                "load-plan-y": "plan_y",
                "load-kx": "stiffness_x_override",
                "load-ky": "stiffness_y_override",
                "load-vnx": "strength_x",
                "load-vny": "strength_y",
            }[field]
            setattr(level, attribute, parse_number(target.value))
            if field == "load-height":
                level_index = load_levels.index(level)
                if level_index < len(analysis_heights):
                    analysis_heights[level_index] = level.height
        render_loads_results()
        if field == "load-height":
            render_analysis_results()
        return
    group_id = str(target.getAttribute("data-group"))
    group = get_group(group_id)
    if group is None:
        return
    if field == "quantity":
        group.quantity = int(parse_number(target.value))
    elif field in ("dimension", "fc"):
        setattr(group, field, parse_number(target.value))
    elif field == "axis":
        group.axis = str(target.value)[:12]
    elif field == "analysis-frame-x":
        group.x0 = parse_number(target.value)
    elif field == "analysis-frame-y":
        group.y0 = parse_number(target.value)
    elif field == "analysis-frame-beta":
        group.beta = parse_number(target.value)
    render_results()
    if field in ("quantity", "dimension", "fc", "axis", "analysis-frame-x", "analysis-frame-y", "analysis-frame-beta"):
        render_loads_results()
    render_analysis_results()


@when("change", "#calculator")
def handle_change(event):
    global loads_use_preset
    global loads_discontinuity_vertical, loads_extreme_discontinuity_vertical
    global loads_reentrant_corners, loads_diaphragm_discontinuity, loads_nonparallel_systems
    target = event.target
    field = target.getAttribute("data-field")
    if field is None:
        return
    field = str(field)
    if field == "building-levels":
        resize_analysis_levels(int(parse_number(target.value, 2.0)))
        return
    if field == "analysis-deform-level":
        global analysis_view_level
        analysis_view_level = int(parse_number(target.value, 1.0))
        render_analysis_results()
        return
    if field in ("analysis-elevation-axis", "analysis-matrix-axis"):
        global analysis_selected_axis_id
        analysis_selected_axis_id = str(target.value)
        render_analysis_results()
        return
    if field == "loads-zone":
        global loads_zone
        loads_zone = str(target.value)
        render_loads_results()
        return
    if field == "loads-soil":
        global loads_soil
        loads_soil = str(target.value)
        render_loads_results()
        return
    if field == "loads-category":
        global loads_category
        loads_category = str(target.value)
        render_loads_results()
        return
    if field == "loads-system":
        global loads_system
        loads_system = str(target.value)
        render_loads_results()
        return
    if field == "loads-use-global":
        loads_use_preset = str(target.value)
        for level in load_levels:
            level.use_key = "azotea_no_transitable" if level.is_roof else loads_use_preset
            level.cv = live_load_preset(level.use_key)
        render_load_levels()
        render_loads_results()
        return
    if field == "loads-period-mode":
        global loads_period_mode
        loads_period_mode = str(target.value)
        render_loads_site_inputs()
        render_loads_results()
        return
    if field == "loads-discontinuity-vertical":
        loads_discontinuity_vertical = bool(target.checked)
        render_loads_results()
        return
    if field == "loads-extreme-discontinuity-vertical":
        loads_extreme_discontinuity_vertical = bool(target.checked)
        render_loads_results()
        return
    if field == "loads-reentrant-corners":
        loads_reentrant_corners = bool(target.checked)
        render_loads_results()
        return
    if field == "loads-diaphragm-discontinuity":
        loads_diaphragm_discontinuity = bool(target.checked)
        render_loads_results()
        return
    if field == "loads-nonparallel-systems":
        loads_nonparallel_systems = bool(target.checked)
        render_loads_results()
        return
    if field == "load-preset":
        level = get_load_level(str(target.getAttribute("data-level-id")))
        preset_key = str(target.value)
        if level is not None and preset_key:
            level.use_key = preset_key
            level.cv = live_load_preset(preset_key)
            render_load_levels()
            render_loads_results()
        return
    if field not in ("base", "top"):
        return
    group = get_group(str(target.getAttribute("data-group")))
    if group is None:
        return
    setattr(group, field, str(target.value))
    render_groups()
    render_results()
    render_loads_results()
    render_analysis_results()


def initialize() -> None:
    render_unit_toggle()
    render_groups()
    render_results()
    render_load_levels()
    render_loads_site_inputs()
    render_loads_results()
    render_analysis_inputs()
    render_analysis_results()
    by_id("calculator").setAttribute("aria-busy", "false")


initialize()

"""Interfaz web de SismoLab ejecutada por Python en el navegador."""

from __future__ import annotations

from html import escape
from math import isfinite

from pyscript import document, when

from stiffness import (
    ColumnGroup,
    STEEL_MODULUS_MKS,
    STEEL_MODULUS_SI,
    boundary_description,
    boundary_factor,
    calculate_story,
    convert_group_units,
    direction_label,
    material_label,
    resistance_bounds,
    resistance_label,
)


units = "SI"
story_height = 3.0
next_group_number = 2
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
    )
]


def by_id(element_id: str):
    return document.getElementById(element_id)


def format_number(value: float, digits: int = 2) -> str:
    if not isfinite(float(value)):
        return "—"
    rendered = f"{float(value):,.{digits}f}"
    if digits:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered.replace(",", "§").replace(".", ",").replace("§", ".")


def input_number(value: float, digits: int = 6) -> str:
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def parse_number(value, fallback: float = 0.0) -> float:
    try:
        number = float(str(value).replace(",", "."))
        return number if isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def get_group(group_id: str) -> ColumnGroup | None:
    return next((group for group in groups if group.id == group_id), None)


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
          <small>Las columnas del grupo se repartirán sobre esta línea en el plano.</small>
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

    dim_base = point(min_grid_x - 0.7, min_grid_y, 0)
    dim_top = point(min_grid_x - 0.7, min_grid_y, 1)
    parts.append(
        f'<path class="iso-dim" d="M{dim_base[0]:.1f} {dim_base[1]:.1f} L{dim_top[0]:.1f} {dim_top[1]:.1f}"/>'
    )
    parts.append(
        f'<text class="iso-dim-label" x="{dim_top[0] - 7:.1f}" y="{(dim_base[1] + dim_top[1]) / 2:.1f}" '
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
        )
    )
    next_group_number += 1
    render_groups()
    render_results()


def reset() -> None:
    global units, story_height, groups, next_group_number
    units = "SI"
    story_height = 3.0
    next_group_number = 2
    groups = [ColumnGroup("c1", 2, "square", 300.0, 21.0, "fixed", "fixed", "concrete", "X", "1")]
    by_id("story-height").value = "3"
    render_unit_toggle()
    render_groups()
    render_results()


@when("click", "#calculator")
def handle_click(event):
    action_element = event.target.closest("[data-action]")
    if not hasattr(action_element, "getAttribute"):
        return
    action = str(action_element.getAttribute("data-action"))
    if action == "units":
        change_units(str(action_element.getAttribute("data-value")))
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
    elif action == "shape":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.shape = str(action_element.getAttribute("data-value"))
            render_groups()
            render_results()
    elif action == "material":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.material = str(action_element.getAttribute("data-value"))
            render_groups()
            render_results()
    elif action == "direction":
        group_id = str(action_element.getAttribute("data-id"))
        group = get_group(group_id)
        if group is not None:
            group.direction = str(action_element.getAttribute("data-value"))
            render_groups()
            render_results()


@when("input", "#calculator")
def handle_input(event):
    global story_height
    target = event.target
    field = target.getAttribute("data-field")
    if field is None:
        return
    field = str(field)
    if field == "story-height":
        story_height = parse_number(target.value)
        render_results()
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
    render_results()


@when("change", "#calculator")
def handle_change(event):
    target = event.target
    field = target.getAttribute("data-field")
    if field is None or str(field) not in ("base", "top"):
        return
    group = get_group(str(target.getAttribute("data-group")))
    if group is None:
        return
    setattr(group, str(field), str(target.value))
    render_groups()
    render_results()


def initialize() -> None:
    render_unit_toggle()
    render_groups()
    render_results()
    status = by_id("python-status")
    status.classList.add("is-ready")
    status.innerHTML = "<i></i> Motor Python activo"
    by_id("calculator").setAttribute("aria-busy", "false")


initialize()

"""Espectros de respuesta de un acelerograma y espectro de diseño E.030.

Métodos para el oscilador de un grado de libertad
    ü + 2ξω·u̇ + ω²·u = −ü_g(t)
* "analitico": solución exacta para una excitación lineal por tramos
  (método de interpolación de la excitación, Nigam y Jennings; Chopra §5.2).
* "newmark_promedio": Newmark-β con aceleración promedio (γ = 1/2, β = 1/4).
* "newmark_lineal": Newmark-β con aceleración lineal (γ = 1/2, β = 1/6).

Sin dependencias del navegador. Unidades internas: m, s, m/s².
"""

from __future__ import annotations

import re
from math import ceil, cos, exp, pi, sin, sqrt

G = 9.80665

UNIT_FACTORS = {"g": G, "m/s2": 1.0, "gal": 0.01}  # a m/s²
METHODS = {
    "analitico": "Método analítico (interpolación lineal de la excitación)",
    "newmark_promedio": "Newmark · aceleración promedio (γ = ½, β = ¼)",
    "newmark_lineal": "Newmark · aceleración lineal (γ = ½, β = ⅙)",
}

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?")


def _numbers(line: str) -> list[float]:
    return [float(token.replace("D", "E").replace("d", "e")) for token in _NUMBER.findall(line)]


def parse_record(text: str, dt: float | None = None) -> tuple[float, list[float], str]:
    """Lee un acelerograma en texto.

    Acepta: (a) dos columnas tiempo–aceleración; (b) una columna o varias
    columnas de aceleración con Δt conocido; (c) formato PEER (.AT2) con la
    línea "NPTS= …, DT= …" en la cabecera. Devuelve (Δt, aceleraciones, nota).
    """
    lines = [line.strip() for line in str(text).replace(",", " ").replace(";", " ").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError("Pega o carga un registro con al menos dos valores.")
    header_dt = None
    for line in lines[:12]:
        match = re.search(r"DT\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", line, re.IGNORECASE)
        if match:
            header_dt = float(match.group(1))
            break
    data_lines = []
    for line in lines:
        if re.search(r"[A-DF-Za-df-z]", line.replace("E+", "").replace("E-", "").replace("e+", "").replace("e-", "")):
            continue  # cabeceras con texto
        values = _numbers(line)
        if values:
            data_lines.append(values)
    if not data_lines:
        raise ValueError("No se encontraron números en el registro.")
    widths = {len(values) for values in data_lines}
    if header_dt is not None:
        acc = [value for values in data_lines for value in values]
        return header_dt, acc, f"Formato PEER: Δt = {header_dt} s leído de la cabecera."
    if widths == {2} and len(data_lines) >= 3:
        times = [values[0] for values in data_lines]
        steps = [b - a for a, b in zip(times, times[1:])]
        increasing = min(steps) > 0
        if increasing or dt is None:
            if not increasing:
                raise ValueError("La columna de tiempo debe ser creciente.")
            step = sum(steps) / len(steps)
            if max(abs(s - step) for s in steps) > 0.01 * step:
                raise ValueError("El paso de tiempo no es constante; remuestrea el registro a Δt fijo.")
            acc = [values[1] for values in data_lines]
            return step, acc, f"Dos columnas tiempo–aceleración: Δt = {step:.4g} s (leído de la columna de tiempo)."
    if dt is None or dt <= 0:
        raise ValueError("Indica el Δt del registro (no se encontró columna de tiempo ni cabecera DT).")
    acc = [value for values in data_lines for value in values]
    return float(dt), acc, f"Una o varias columnas de aceleración con Δt = {dt} s."


def default_periods() -> list[float]:
    periods = []
    t = 0.02
    while t < 0.5 - 1e-9:
        periods.append(round(t, 3))
        t += 0.02
    while t < 1.5 - 1e-9:
        periods.append(round(t, 3))
        t += 0.05
    while t <= 4.0 + 1e-9:
        periods.append(round(t, 3))
        t += 0.1
    return periods


def _exact_coefficients(omega: float, xi: float, dt: float):
    wd = omega * sqrt(1.0 - xi * xi)
    e = exp(-xi * omega * dt)
    s, c = sin(wd * dt), cos(wd * dt)
    r = xi / sqrt(1.0 - xi * xi)
    k = omega * omega
    A = e * (r * s + c)
    B = e * (s / wd)
    C = (1.0 / k) * (2 * xi / (omega * dt) + e * (((1 - 2 * xi * xi) / (wd * dt) - r) * s - (1 + 2 * xi / (omega * dt)) * c))
    D = (1.0 / k) * (1 - 2 * xi / (omega * dt) + e * ((2 * xi * xi - 1) / (wd * dt) * s + 2 * xi / (omega * dt) * c))
    Ap = -e * (omega / sqrt(1 - xi * xi)) * s
    Bp = e * (c - r * s)
    Cp = (1.0 / k) * (-1.0 / dt + e * ((omega / sqrt(1 - xi * xi) + xi / (dt * sqrt(1 - xi * xi))) * s + c / dt))
    Dp = (1.0 / (k * dt)) * (1 - e * (r * s + c))
    return A, B, C, D, Ap, Bp, Cp, Dp


def sdof_response(acc: list[float], dt: float, period: float, xi: float, method: str = "analitico") -> dict[str, float]:
    """Máximos |u|, |u̇| y |ü_t| del oscilador ante ü_g (m/s²)."""
    if period <= 0 or dt <= 0:
        raise ValueError("El periodo y el Δt deben ser positivos.")
    if not 0 <= xi < 1:
        raise ValueError("El amortiguamiento debe estar entre 0 y 1.")
    omega = 2 * pi / period
    k = omega * omega
    c = 2 * xi * omega
    u = v = 0.0
    umax = vmax = amax = 0.0
    if method == "analitico":
        A, B, C, D, Ap, Bp, Cp, Dp = _exact_coefficients(omega, max(xi, 1e-9), dt)
        p_prev = -acc[0]
        amax = abs(acc[0])
        for value in acc[1:]:
            p = -value
            u, v = A * u + B * v + C * p_prev + D * p, Ap * u + Bp * v + Cp * p_prev + Dp * p
            p_prev = p
            at = -(c * v + k * u)
            if abs(u) > umax:
                umax = abs(u)
            if abs(v) > vmax:
                vmax = abs(v)
            if abs(at) > amax:
                amax = abs(at)
        return {"Sd": umax, "Sv": vmax, "Sa": amax}

    if method == "newmark_promedio":
        gamma, beta = 0.5, 0.25
    elif method == "newmark_lineal":
        gamma, beta = 0.5, 1.0 / 6.0
    else:
        raise ValueError("Método desconocido.")
    # Subdivide el paso para que Δt ≤ T/40 (precisión y estabilidad).
    sub = max(1, int(ceil(dt / (period / 40.0))))
    h = dt / sub
    khat = k + gamma / (beta * h) * c + 1.0 / (beta * h * h)
    a_coef = 1.0 / (beta * h) + gamma / beta * c
    b_coef = 1.0 / (2 * beta) + h * (gamma / (2 * beta) - 1.0) * c
    p_prev = -acc[0]
    a = p_prev - c * v - k * u
    amax = abs(acc[0])
    for index in range(1, len(acc)):
        p_start, p_end = -acc[index - 1], -acc[index]
        for step in range(1, sub + 1):
            p = p_start + (p_end - p_start) * step / sub
            dp_hat = (p - p_prev) + a_coef * v + b_coef * a
            du = dp_hat / khat
            dv = gamma / (beta * h) * du - gamma / beta * v + h * (1 - gamma / (2 * beta)) * a
            da = du / (beta * h * h) - v / (beta * h) - a / (2 * beta)
            u += du
            v += dv
            a += da
            p_prev = p
        at = -(c * v + k * u)
        if abs(u) > umax:
            umax = abs(u)
        if abs(v) > vmax:
            vmax = abs(v)
        if abs(at) > amax:
            amax = abs(at)
    return {"Sd": umax, "Sv": vmax, "Sa": amax}


def response_spectrum(acc: list[float], dt: float, periods: list[float], xi: float, method: str) -> list[dict[str, float]]:
    rows = []
    for period in periods:
        result = sdof_response(acc, dt, period, xi, method)
        omega = 2 * pi / period
        rows.append(
            {
                "T": period,
                "Sd": result["Sd"],
                "Sv": result["Sv"],
                "Sa": result["Sa"],
                "PSv": omega * result["Sd"],
                "PSa": omega * omega * result["Sd"],
            }
        )
    return rows


def interpolate(rows: list[dict[str, float]], period: float, key: str = "PSa") -> float:
    """Interpola linealmente una ordenada espectral (constante fuera del rango)."""
    if not rows:
        return 0.0
    if period <= rows[0]["T"]:
        return rows[0][key]
    for first, second in zip(rows, rows[1:]):
        if first["T"] <= period <= second["T"]:
            ratio = (period - first["T"]) / (second["T"] - first["T"])
            return first[key] + ratio * (second[key] - first[key])
    return rows[-1][key]


def e030_spectrum(periods: list[float], z: float, u: float, s: float, tp: float, tl: float, r: float = 1.0) -> list[dict[str, float]]:
    """Sa = Z·U·C·S/R·g con C de la Tabla N° 6 de la E.030:2026 (m/s²)."""
    rows = []
    for period in periods:
        if period < 0.2 * tp:
            c = 1.0 + 7.5 * period / tp
        elif period <= tp:
            c = 2.5
        elif period <= tl:
            c = 2.5 * tp / period
        else:
            c = 2.5 * tp * tl / period**2
        rows.append({"T": period, "C": c, "PSa": z * u * c * s / r * G})
    return rows

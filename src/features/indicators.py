"""Indicadores del tablero: variación esperada, mes de mayor y menor venta,
confiabilidad y tabla de exportación. Funciones puras (sin base de datos ni
Streamlit). Ubicación: src/features/indicators.py

Proyecciones: tabla `pronosticos` (ver src/db/repository.py), columnas clave, fecha_corte, fecha, cantidad.
El semáforo de confiabilidad (reliability_*) queda listo pero sin usar hasta que se publique el error.
"""
import math
from datetime import date

import pandas as pd

from src.config import HORIZONS, RELIABILITY_HIGH_MAX, RELIABILITY_MEDIUM_MAX

MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def month_label(f: date, short: bool = False) -> str:
    """date(2026, 9, 1) -> 'septiembre 2026' (o 'sep-2026' con short=True)."""
    name = MONTH_NAMES[f.month - 1]
    return f"{name[:3]}-{f.year}" if short else f"{name} {f.year}"


def months_ahead(cutoff: date, f: date) -> int:
    """Meses entre el último mes cerrado y el mes proyectado (1 = el siguiente)."""
    return (f.year - cutoff.year) * 12 + f.month - cutoff.month


def latest_forecasts(forecasts: pd.DataFrame, months: int) -> pd.DataFrame:
    """Proyecciones de la corrida más reciente, limitadas a los primeros `months` meses
    (1 = solo el siguiente; 2 = los dos siguientes; 3 = los tres)."""
    if months not in HORIZONS:
        raise ValueError(f"months debe ser uno de {HORIZONS}")
    if forecasts.empty:
        return forecasts.copy()
    run = forecasts[forecasts["fecha_corte"] == forecasts["fecha_corte"].max()].copy()
    run["horizonte"] = [months_ahead(c, f) for c, f in zip(run["fecha_corte"], run["fecha"])]
    run = run[run["horizonte"].between(1, months)]
    return run.sort_values(["clave", "fecha"]).reset_index(drop=True)


def expected_change(projected: float, last_closed: float) -> float:
    """Variación esperada (%) del mes proyectado contra el último mes cerrado.
    NaN si el último mes cerrado no tuvo venta (no se puede expresar en %)."""
    if last_closed == 0:
        return math.nan
    return (projected - last_closed) / last_closed * 100


def peak_and_low(sales: pd.DataFrame) -> tuple:
    """Mes de mayor y de menor venta de un producto en el periodo recibido (ya filtrado).
    Devuelve ((fecha, cantidad), (fecha, cantidad)); en empate gana el mes más antiguo."""
    if sales.empty:
        raise ValueError("No hay ventas en el periodo seleccionado")
    s = sales.sort_values("fecha").reset_index(drop=True)
    hi, lo = s.loc[s["cantidad"].idxmax()], s.loc[s["cantidad"].idxmin()]
    return (hi["fecha"], float(hi["cantidad"])), (lo["fecha"], float(lo["cantidad"]))


def reliability_level(error_pct: float) -> str | None:
    """'alta', 'media' o 'baja' según la desviación promedio en la prueba; None si no se conoce."""
    if error_pct is None or math.isnan(error_pct):
        return None
    if error_pct <= RELIABILITY_HIGH_MAX:
        return "alta"
    if error_pct <= RELIABILITY_MEDIUM_MAX:
        return "media"
    return "baja"


def reliability_message(error_pct: float) -> str | None:
    """Aviso en lenguaje de negocio; None si la confiabilidad es alta o desconocida."""
    level = reliability_level(error_pct)
    if level in (None, "alta"):
        return None
    text = (f"Confiabilidad {level}: en las pruebas con ventas pasadas, la proyección de este "
            f"producto se desvió en promedio {error_pct:.0f} % de lo que realmente se vendió.")
    if level == "baja":
        return text + " Tómala solo como referencia y contrástala con tu experiencia antes de decidir."
    return text + " Revísala junto con tu criterio antes de decidir."


def forecast_table(forecasts: pd.DataFrame, sales: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    """Tabla por producto y mes proyectado, con variación contra el último mes cerrado.
    `forecasts` ya viene de latest_forecasts; `sales` trae al menos el último mes cerrado."""
    cols = ["clave", "descripcion", "mes", "piezas_proyectadas", "ultimo_mes_cerrado",
            "piezas_ultimo_mes", "variacion_pct"]
    if forecasts.empty:
        return pd.DataFrame(columns=cols)
    last = sales.set_index(["clave", "fecha"])["cantidad"]
    desc = products.set_index("clave")["descripcion"]
    rows = []
    for r in forecasts.itertuples():
        base = float(last.get((r.clave, r.fecha_corte), math.nan))
        rows.append({
            "clave": r.clave,
            "descripcion": desc.get(r.clave, ""),
            "mes": month_label(r.fecha),
            "piezas_proyectadas": round(float(r.cantidad)),
            "ultimo_mes_cerrado": month_label(r.fecha_corte),
            "piezas_ultimo_mes": base,
            "variacion_pct": round(expected_change(float(r.cantidad), base), 1),
        })
    return pd.DataFrame(rows, columns=cols)


def export_csv(table: pd.DataFrame) -> bytes:
    """CSV para descargar, con encabezados de negocio. utf-8-sig para que Excel lea los acentos."""
    out = table.rename(columns={
        "clave": "Clave", "descripcion": "Producto", "mes": "Mes proyectado",
        "piezas_proyectadas": "Piezas proyectadas", "ultimo_mes_cerrado": "Último mes cerrado",
        "piezas_ultimo_mes": "Piezas del último mes cerrado",
        "variacion_pct": "Variación esperada (%)",
    })
    return out.to_csv(index=False).encode("utf-8-sig")

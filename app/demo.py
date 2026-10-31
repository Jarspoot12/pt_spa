"""Modo DEMO del tablero: proyecciones SINTÉTICAS, solo en memoria, para ver la interfaz
completa sin depender de la tabla `pronosticos`. No es un modelo, no escribe en Supabase
y no debe usarse para decidir compras. Ubicación: app/demo.py
Activar desde la raíz: streamlit run app/streamlit_app.py -- --demo
"""
from datetime import date

import numpy as np
import pandas as pd

from src.config import HORIZONS, SEED
from src.db.repository import COLUMNAS_PRONOSTICOS
from src.etl.transform import sumar_meses

DEMO_NOTICE = "DATOS SINTÉTICOS DE DEMOSTRACIÓN: no son proyecciones reales"


def synthetic_forecasts(sales: pd.DataFrame, cutoff: date, claves: list) -> pd.DataFrame:
    """Inventa un mes por horizonte (HORIZONS) y producto: venta promedio del producto en ese mes del año
    multiplicada por un factor aleatorio (semilla fija). Mismo formato que repo.pronosticos()."""
    rng = np.random.default_rng(SEED)
    rows = []
    for clave in claves:
        s = sales[sales["clave"] == clave]
        by_month = s.groupby(s["fecha"].map(lambda f: f.month))["cantidad"].mean()
        for h in HORIZONS:
            f = sumar_meses(cutoff, h)
            qty = by_month.get(f.month, s["cantidad"].mean()) * rng.uniform(0.8, 1.2)
            rows.append((clave, cutoff, f, round(float(qty), 2)))
    return pd.DataFrame(rows, columns=COLUMNAS_PRONOSTICOS)


def mark_export(table: pd.DataFrame) -> pd.DataFrame:
    """Agrega una primera columna con el aviso para que el CSV descargado no se confunda con datos reales."""
    return table.assign(AVISO=DEMO_NOTICE)[["AVISO", *table.columns]]

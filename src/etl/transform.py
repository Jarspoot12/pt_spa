"""Transformación: construye `productos` y `ventas` a partir de las hojas ya
validadas. Funciones puras (sin base de datos). Ubicación: src/etl/transform.py
"""
from datetime import date

import pandas as pd

from .extract import Hoja, valores_mensuales

UNIDAD_PIEZAS = "PZA"
UNIDAD_KILOS = "KG"


def parse_mes(texto) -> date:
    """'2026-09' o '2026-09-01' -> date(2026, 9, 1)."""
    if isinstance(texto, date):
        return texto.replace(day=1)
    p = str(texto).split("-")
    return date(int(p[0]), int(p[1]), 1)


def sumar_meses(f: date, n: int) -> date:
    i = f.year * 12 + (f.month - 1) + n
    return date(i // 12, i % 12 + 1, 1)


def meses_entre(desde: date, hasta: date) -> list:
    out, f = [], desde
    while f <= hasta:
        out.append(f)
        f = sumar_meses(f, 1)
    return out


def tiene_decimales(matriz: pd.DataFrame) -> pd.Series:
    """True por clave si algún mes trae fracciones (regla de unidad: KG)."""
    return ((matriz - matriz.round()).abs() > 1e-9).any(axis=1)


def _descripciones(hoja: Hoja) -> pd.Series:
    return hoja.filas.set_index("clave")["DESCRIPCION"].astype(str).str.strip()


def _a_largo(matriz: pd.DataFrame, anio: int, meses: list, claves) -> pd.DataFrame:
    """Matriz clave × mes de un año -> filas (clave, fecha, cantidad). Lo que no
    aparece en la hoja es una venta de 0 para productos ya conocidos."""
    sub = matriz.reindex(index=list(claves), columns=[f.month for f in meses]).fillna(0.0)
    sub.columns = meses
    sub.index.name, sub.columns.name = "clave", "fecha"
    largo = sub.stack().rename("cantidad").reset_index()
    largo["cantidad"] = largo["cantidad"].astype(float).round(2)
    return largo


def construir_inicial(hojas: dict, hasta: date):
    """Carga inicial. Devuelve (productos, ventas).
    productos: los vigentes (hoja más reciente) con historial_completo y unidad.
    ventas: solo los de historial completo, de enero del primer año a `hasta`."""
    anios = sorted(hojas)
    mats = {a: valores_mensuales(hojas[a]) for a in anios}
    vigentes = _descripciones(hojas[anios[-1]])
    en_todas = set.intersection(*[set(m.index) for m in mats.values()])

    # unidad: decimales en cualquier año
    kg = set()
    for m in mats.values():
        d = tiene_decimales(m)
        kg |= set(d[d].index)

    productos = pd.DataFrame({
        "clave": vigentes.index,
        "descripcion": vigentes.values,
        "historial_completo": [int(c in en_todas) for c in vigentes.index],
        "unidad": [UNIDAD_KILOS if c in kg else UNIDAD_PIEZAS for c in vigentes.index],
    })

    claves = productos.loc[productos["historial_completo"] == 1, "clave"].tolist()
    partes = []
    for a in anios:
        meses = [f for f in meses_entre(date(a, 1, 1), min(hasta, date(a, 12, 1)))]
        if meses:
            partes.append(_a_largo(mats[a], a, meses, claves))
    ventas = pd.concat(partes, ignore_index=True)
    return productos, ventas


def construir_incremental(hoja: Hoja, productos_bd: pd.DataFrame, meses: list):
    """Carga mensual con la hoja del año en curso.
    Devuelve (productos_nuevos, descripciones_actualizadas, ventas_nuevas).
    - Los de historial completo que no aparecen en la hoja se cargan con 0.
    - Los productos que no estaban en `productos` entran con historial_completo = 0
      y sin ventas.
    - Los de historial_completo = 0 no generan ventas."""
    m = valores_mensuales(hoja)
    desc = _descripciones(hoja)
    conocidas = set(productos_bd["clave"])

    nuevos_claves = [c for c in desc.index if c not in conocidas]
    dec = tiene_decimales(m)
    nuevos = pd.DataFrame({
        "clave": nuevos_claves,
        "descripcion": [desc[c] for c in nuevos_claves],
        "historial_completo": 0,
        "unidad": [UNIDAD_KILOS if dec.get(c, False) else UNIDAD_PIEZAS for c in nuevos_claves],
    })

    actual = productos_bd.set_index("clave")["descripcion"]
    comunes = [c for c in desc.index if c in conocidas]
    cambian = [c for c in comunes if actual[c] != desc[c]]
    descripciones = pd.DataFrame({"clave": cambian, "descripcion": [desc[c] for c in cambian]})

    analizados = productos_bd.loc[productos_bd["historial_completo"] == 1, "clave"].tolist()
    ventas = _a_largo(m, hoja.anio_hoja, meses, analizados)
    return nuevos, descripciones, ventas
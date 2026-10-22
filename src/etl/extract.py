"""Extracción: lee las hojas 'VTAS AAAA' del Excel sin transformar.
Ubicación: src/etl/extract.py
"""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]


@dataclass
class Hoja:
    nombre: str            # p. ej. "VTAS 2026"
    anio_hoja: int         # año según el nombre de la hoja
    anio_declarado: object # valor de la celda "AÑO:" (B1)
    filas: pd.DataFrame    # productos (sin la fila TOTAL), con columna `clave` normalizada
    totales: pd.Series     # fila "TOTAL: N"
    total_declarado: object  # N de "TOTAL: N"


def _anio_de_nombre(nombre: str) -> int:
    return int(nombre.strip()[-4:])


def leer_hoja(ruta: Path, nombre: str) -> Hoja:
    encabezado = pd.read_excel(ruta, sheet_name=nombre, header=None, nrows=1, dtype=object)
    df = pd.read_excel(ruta, sheet_name=nombre, header=1, dtype={"CLAVE": object})
    es_total = df["CLAVE"].astype(str).str.upper().str.startswith("TOTAL")
    if es_total.sum() != 1:
        raise ValueError(f"La hoja '{nombre}' debe tener exactamente una fila TOTAL (tiene {es_total.sum()}).")
    totales = df[es_total].iloc[0]
    filas = df[~es_total].copy()
    filas["clave"] = filas["CLAVE"].astype(str).str.strip().str.upper()
    declarado = str(totales["CLAVE"]).split(":")[-1].strip()
    return Hoja(
        nombre=nombre,
        anio_hoja=_anio_de_nombre(nombre),
        anio_declarado=encabezado.iloc[0, 1],
        filas=filas,
        totales=totales,
        total_declarado=declarado,
    )


def leer_excel(ruta, anios=None) -> dict:
    """Devuelve {anio: Hoja}. Si `anios` es None lee todas las hojas del libro."""
    ruta = Path(ruta)
    hojas = {}
    for nombre in pd.ExcelFile(ruta).sheet_names:
        anio = _anio_de_nombre(nombre)
        if anios is None or anio in anios:
            hojas[anio] = leer_hoja(ruta, nombre)
    if anios is not None:
        faltan = sorted(set(anios) - set(hojas))
        if faltan:
            raise ValueError(f"Faltan hojas en el Excel para los años: {faltan}")
    return hojas


def valores_mensuales(hoja: Hoja) -> pd.DataFrame:
    """Matriz clave × mes (1..12) como número. Los vacíos quedan en NaN para que
    los controles los detecten."""
    m = hoja.filas.set_index("clave")[MESES].apply(pd.to_numeric, errors="coerce")
    m.columns = range(1, 13)
    return m
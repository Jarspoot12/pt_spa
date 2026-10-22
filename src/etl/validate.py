"""Controles automáticos de 5.3.2. Si alguno falla, el pipeline se detiene
y no se escribe nada en la base. Ubicación: src/etl/validate.py
"""
from dataclasses import dataclass

import pandas as pd

from .extract import MESES, Hoja, valores_mensuales

# Tolerancia de las sumas (el Excel redondea a 2 decimales; la diferencia máxima observada fue 0.03).
TOLERANCIA = 0.05


@dataclass
class Falla:
    control: str
    hoja: str
    detalle: str

    def __str__(self):
        return f"[{self.control}] {self.hoja}: {self.detalle}"


class ControlError(Exception):
    """La carga se detiene. `fallas` dice qué control falló y dónde."""

    def __init__(self, fallas):
        self.fallas = fallas
        super().__init__("Controles fallidos:\n" + "\n".join(f"  - {f}" for f in fallas))


def _claves(serie, tope=8):
    lista = [str(x) for x in list(serie)[:tope]]
    extra = len(serie) - tope
    return ", ".join(lista) + (f" (+{extra} más)" if extra > 0 else "")


def controles_hoja(hoja: Hoja) -> list:
    f = []
    n = hoja.nombre
    filas = hoja.filas
    m = valores_mensuales(hoja)

    # 1. El año de la hoja coincide con la fila "AÑO:"
    if str(hoja.anio_declarado).strip() != str(hoja.anio_hoja):
        f.append(Falla("año", n, f"el nombre dice {hoja.anio_hoja} y la celda AÑO dice {hoja.anio_declarado}"))

    # 2. Número de filas = total declarado
    if str(len(filas)) != str(hoja.total_declarado):
        f.append(Falla("filas", n, f"hay {len(filas)} productos y la fila TOTAL declara {hoja.total_declarado}"))

    # 3. Claves duplicadas o vacías
    dup = filas.loc[filas["clave"].duplicated(keep=False), "clave"].unique()
    if len(dup):
        f.append(Falla("duplicados", n, f"claves repetidas: {_claves(dup)}"))
    vacias = filas["clave"].isin(["", "NAN", "NONE"])
    if vacias.any():
        f.append(Falla("claves vacías", n, f"{int(vacias.sum())} filas sin clave"))

    # 4. Sin nulos ni valores no numéricos
    nulos = m.isna()
    if nulos.any().any():
        claves = m.index[nulos.any(axis=1)]
        meses = [MESES[c - 1] for c in m.columns[nulos.any(axis=0)]]
        f.append(Falla("nulos", n, f"valores vacíos o no numéricos en meses {meses}; claves: {_claves(claves)}"))

    # 5. Sin negativos
    neg = m < 0
    if neg.any().any():
        f.append(Falla("negativos", n, f"valores negativos en claves: {_claves(m.index[neg.any(axis=1)])}"))

    # 6. Suma de cada mes = fila TOTAL
    declarados = pd.to_numeric(hoja.totales[MESES], errors="coerce")
    dif_mes = (m.sum() - declarados.values).abs()
    for mes, d in zip(MESES, dif_mes.values):
        if not d <= TOLERANCIA:
            f.append(Falla("suma por mes", n, f"{mes}: la suma de productos difiere {d:.2f} de la fila TOTAL"))

    # 7. Suma de los 12 meses de cada producto = columna TOTAL
    total_prod = pd.to_numeric(filas.set_index("clave")["TOTAL"], errors="coerce")
    dif_prod = (m.sum(axis=1) - total_prod).abs()
    malas = dif_prod[~(dif_prod <= TOLERANCIA)]
    if len(malas):
        f.append(Falla("suma por producto", n, f"{len(malas)} productos no cuadran con su TOTAL: {_claves(malas.index)}"))
    return f


def validar_hojas(hojas: dict) -> None:
    fallas = []
    for anio in sorted(hojas):
        fallas += controles_hoja(hojas[anio])
    if fallas:
        raise ControlError(fallas)


def validar_postcarga(esperado_filas, esperado_suma, real_filas, real_suma, contexto="ventas"):
    """Control posterior a la inserción (dentro de la transacción)."""
    fallas = []
    if esperado_filas != real_filas:
        fallas.append(Falla("filas cargadas", contexto, f"se esperaban {esperado_filas} y la base tiene {real_filas}"))
    if abs(float(esperado_suma) - float(real_suma)) > TOLERANCIA:
        fallas.append(Falla("piezas cargadas", contexto, f"se esperaban {esperado_suma:.2f} y la base tiene {real_suma:.2f}"))
    if fallas:
        raise ControlError(fallas)
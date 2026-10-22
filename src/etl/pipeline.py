"""Orquesta extraer -> validar -> transformar -> cargar y es el punto de entrada.
Ubicación: src/etl/pipeline.py

  python -m src.etl.pipeline inicial     --hasta 2026-09 [--simular]
  python -m src.etl.pipeline incremental --hasta 2026-10 [--simular]
--simular corre los controles sin escribir en la base. Si un control falla, el
programa termina con código 1 y muestra cuál y dónde.

Reglas (5.4):
- Carga inicial: Excel completo (5 hojas). `productos` = vigentes; `ventas` = solo
  los de historial completo, de enero de 2022 al último mes cerrado.
- Cargas siguientes: solo la hoja del año en curso. Se agregan únicamente los meses
  posteriores al último mes cargado; los meses ya cargados NO se modifican.
- Cualquier control fallido detiene la carga y no se escribe nada.
"""
import argparse
import sys
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .extract import leer_excel, valores_mensuales
from .transform import (UNIDAD_PIEZAS, construir_incremental, construir_inicial, meses_entre,
                        parse_mes, sumar_meses, tiene_decimales)
from .validate import TOLERANCIA, ControlError, Falla, validar_hojas, validar_postcarga

RUTA_EXCEL = "data/raw/HISTORICOS_DE_VENTAS.xlsx"
# Hojas de la carga inicial; tiene historial completo el producto presente en todas.
ANIOS_INICIALES = [2022, 2023, 2024, 2025, 2026]


@dataclass
class Resumen:
    modo: str
    simulado: bool = False
    productos_nuevos: int = 0
    productos_total: int = 0
    productos_analizados: int = 0
    descripciones_actualizadas: int = 0
    ventas_insertadas: int = 0
    desde: date = None
    hasta: date = None
    piezas: float = 0.0
    avisos: list = field(default_factory=list)

    def texto(self):
        L = [f"Carga {self.modo}{' (SIMULACIÓN, no se escribió nada)' if self.simulado else ''}"]
        if self.ventas_insertadas or self.modo == "inicial":
            L.append(f"  Meses: {self.desde:%Y-%m} a {self.hasta:%Y-%m}")
        L.append(f"  Productos nuevos: {self.productos_nuevos}")
        if self.productos_total:
            L.append(f"  Productos en la tabla: {self.productos_total} ({self.productos_analizados} con historial completo)")
        L.append(f"  Descripciones actualizadas: {self.descripciones_actualizadas}")
        L.append(f"  Filas de ventas insertadas: {self.ventas_insertadas}")
        L.append(f"  Cantidad insertada (piezas y kg): {self.piezas:,.2f}")
        for a in self.avisos:
            L.append(f"  AVISO: {a}")
        return "\n".join(L)


def _control_mes_con_ventas(hoja, ultimo: date):
    """El último mes a cargar debe tener ventas; si está en 0 casi seguro no ha cerrado."""
    total = pd.to_numeric(hoja.totales.iloc[2:14], errors="coerce").values[ultimo.month - 1]
    if not total > 0:
        raise ControlError([Falla("mes sin ventas", hoja.nombre,
                                  f"el mes {ultimo:%Y-%m} suma 0 en la fila TOTAL; ¿el mes ya cerró?")])


def preparar_inicial(ruta, hasta: date, anios=ANIOS_INICIALES):
    """Extrae, valida y transforma sin tocar la base. Devuelve (productos, ventas)."""
    hojas = leer_excel(ruta, anios)
    validar_hojas(hojas)
    _control_mes_con_ventas(hojas[max(hojas)], hasta)
    if hasta.year != max(hojas):
        raise ControlError([Falla("corte", "inicial", f"`hasta` {hasta:%Y-%m} no cae en la hoja más reciente ({max(hojas)})")])
    return construir_inicial(hojas, hasta)


def cargar_inicial(ruta, hasta, repo, simular=False, anios=ANIOS_INICIALES) -> Resumen:
    hasta = parse_mes(hasta)
    productos, ventas = preparar_inicial(ruta, hasta, anios)
    r = Resumen("inicial", simular, desde=date(min(anios), 1, 1), hasta=hasta)
    with repo.transaccion(simular):
        repo.crear_esquema()
        n0, _ = repo.resumen_ventas()
        if n0 or not repo.productos().empty:
            raise ControlError([Falla("carga inicial", "base", "la base ya tiene datos; usa la carga incremental")])
        repo.insertar_productos(productos)
        repo.insertar_ventas(ventas)
        n, s = repo.resumen_ventas()
        validar_postcarga(len(ventas), ventas["cantidad"].sum(), n, s)
    r.productos_nuevos = r.productos_total = len(productos)
    r.productos_analizados = int(productos["historial_completo"].sum())
    r.ventas_insertadas, r.piezas = len(ventas), float(ventas["cantidad"].sum())
    return r


def cargar_incremental(ruta, hasta, repo, simular=False) -> Resumen:
    hasta = parse_mes(hasta)
    productos_bd = repo.productos()
    ultima = repo.ultima_fecha()
    if ultima is None:
        raise ControlError([Falla("carga incremental", "base", "no hay ventas cargadas; haz primero la carga inicial")])

    primero = sumar_meses(ultima, 1)
    r = Resumen("incremental", simular, desde=primero, hasta=hasta)
    if hasta < primero:
        r.avisos.append(f"No hay meses nuevos: el último mes cargado es {ultima:%Y-%m} y `hasta` es {hasta:%Y-%m}.")
        return r
    if hasta.year != primero.year:
        raise ControlError([Falla("corte", "incremental",
                                  f"se cargan los meses de un solo año por vez: pide `hasta` ≤ {primero.year}-12")])

    anio = primero.year
    hojas = leer_excel(ruta, [anio])
    hoja = hojas[anio]
    validar_hojas(hojas)
    _control_mes_con_ventas(hoja, hasta)
    meses = meses_entre(primero, hasta)

    nuevos, descripciones, ventas = construir_incremental(hoja, productos_bd, meses)

    # Un producto en piezas no debe traer fracciones (cambio de unidad).
    m = valores_mensuales(hoja)
    dec = tiene_decimales(m[[f.month for f in meses]])
    unidad = productos_bd.set_index("clave")["unidad"]
    mal = [c for c in dec[dec].index if unidad.get(c) == UNIDAD_PIEZAS]
    if mal:
        raise ControlError([Falla("unidad", hoja.nombre, f"productos en piezas con decimales: {', '.join(mal[:8])}")])

    # Meses ya cargados del mismo año: no se modifican; solo se avisa si el Excel cambió.
    if ultima.year == anio:
        previos = meses_entre(date(anio, 1, 1), ultima)
        bd = repo.ventas(previos[0], previos[-1])
        analizados = productos_bd.loc[productos_bd["historial_completo"] == 1, "clave"]
        hoja_prev = m.reindex(index=analizados, columns=[f.month for f in previos]).fillna(0.0)
        esperado = hoja_prev.stack().rename("hoja").reset_index()
        esperado.columns = ["clave", "mes", "hoja"]
        esperado["fecha"] = esperado["mes"].map(lambda k: date(anio, k, 1))
        comp = esperado.merge(bd, on=["clave", "fecha"], how="left")
        dif = comp[(comp["hoja"] - comp["cantidad"]).abs() > TOLERANCIA]
        if len(dif):
            r.avisos.append(f"{len(dif)} celdas de meses ya cargados difieren del Excel; NO se modificaron "
                            f"(ej.: {', '.join(sorted(set(dif['clave']))[:5])}).")

    with repo.transaccion(simular):
        n0, s0 = repo.resumen_ventas()
        repo.insertar_productos(nuevos)
        r.descripciones_actualizadas = repo.actualizar_descripciones(descripciones)
        repo.insertar_ventas(ventas)
        n, s = repo.resumen_ventas()
        validar_postcarga(n0 + len(ventas), s0 + ventas["cantidad"].sum(), n, s)

    p = repo.productos()
    r.productos_nuevos = len(nuevos)
    r.productos_total = len(p)
    r.productos_analizados = int(p["historial_completo"].sum())
    r.ventas_insertadas, r.piezas = len(ventas), float(ventas["cantidad"].sum())
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="ETL de ventas históricas")
    ap.add_argument("modo", choices=["inicial", "incremental"])
    ap.add_argument("--excel", default=RUTA_EXCEL)
    ap.add_argument("--hasta", required=True, help="último mes cerrado, AAAA-MM")
    ap.add_argument("--simular", action="store_true", help="corre controles y no escribe en la base")
    a = ap.parse_args(argv)
    try:
        if a.modo == "inicial" and a.simular:
            productos, ventas = preparar_inicial(a.excel, parse_mes(a.hasta))
            print(f"SIMULACIÓN inicial (sin base de datos): productos={len(productos)} "
                  f"(historial completo={int(productos.historial_completo.sum())}), ventas={len(ventas)}, "
                  f"cantidad={ventas.cantidad.sum():,.2f}")
            return 0
        from src.db.repository import Repositorio, conectar
        repo = Repositorio(conectar())
        fn = cargar_inicial if a.modo == "inicial" else cargar_incremental
        print(fn(a.excel, a.hasta, repo, simular=a.simular).texto())
        return 0
    except ControlError as e:
        print(f"CARGA DETENIDA. No se escribió nada en la base.\n{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
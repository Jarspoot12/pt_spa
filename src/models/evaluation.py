"""Funciones comunes para comparar modelos del top 10: carga de la serie mensual,
tratamiento de atípicos, orígenes móviles, métricas y tabla de resultados.
Todo es puro salvo `load_top10`, que lee Supabase (solo lectura).
Ubicación: src/models/evaluation.py
"""
from collections.abc import Callable, Iterable
from datetime import date

import numpy as np
import pandas as pd

from src import config

RESULT_COLUMNS = ["clave", "modelo", "horizonte", "mes", "real", "pronostico"]
ALL = "todos"

# Pronóstico de un modelo: (clave, historia hasta el origen, h) -> valor en origen + h
ForecastFn = Callable[[str, pd.Series, int], float]


# --- Carga ---

def build_monthly_matrix(ventas: pd.DataFrame, claves: Iterable[str], start: date, end: date) -> pd.DataFrame:
    """Matriz mes × producto (freq MS) con las ventas en piezas. Exige meses completos y sin huecos."""
    claves = list(claves)
    v = ventas.assign(clave=ventas["clave"].astype(str), fecha=pd.to_datetime(ventas["fecha"]))
    v = v[v["clave"].isin(claves)]
    assert v["fecha"].max() <= pd.Timestamp(end), f"Hay fechas posteriores a {end:%Y-%m}"
    assert v["fecha"].min() >= pd.Timestamp(start), f"Hay fechas anteriores a {start:%Y-%m}"
    meses = pd.date_range(start, end, freq="MS")
    matriz = v.pivot(index="fecha", columns="clave", values="cantidad").reindex(index=meses, columns=claves)
    matriz.index.freq = "MS"
    huecos = matriz.isna().sum()
    assert (huecos == 0).all(), f"Productos con meses faltantes: {huecos[huecos > 0].to_dict()}"
    return matriz.astype(float)


def load_top10(repo) -> pd.DataFrame:
    """Lee de Supabase la serie mensual de los 10 productos (ene-2022 a dic-2025)."""
    productos = repo.productos()
    unidad = productos.assign(clave=productos["clave"].astype(str)).set_index("clave")["unidad"]
    faltan = [c for c in config.TOP10_CLAVES if c not in unidad.index]
    no_pza = [c for c in config.TOP10_CLAVES if c in unidad.index and unidad[c] != "PZA"]
    if faltan or no_pza:
        raise RuntimeError(f"Productos no encontrados: {faltan}; no están en PZA: {no_pza}")
    ventas = repo.ventas(config.TRAIN_START, config.TEST_END)
    return build_monthly_matrix(ventas, config.TOP10_CLAVES, config.TRAIN_START, config.TEST_END)


def read_top10() -> pd.DataFrame:
    """Abre la conexión a Supabase, lee la serie del top 10 y la cierra."""
    from src.db.repository import Repositorio, conectar

    conn = conectar()
    try:
        return load_top10(Repositorio(conn))
    finally:
        conn.close()


# --- Atípicos ---

def tukey_limit(values: pd.Series, k: float = config.TUKEY_K) -> float:
    """Q3 + k × RIC calculado sobre los meses con venta (> 0)."""
    con_venta = values[values > 0]
    q1, q3 = con_venta.quantile([0.25, 0.75])
    return float(q3 + k * (q3 - q1))


def train_limits(matrix: pd.DataFrame, train_end: date = config.TRAIN_END) -> pd.Series:
    """Límite de Tukey por producto, usando solo los meses de entrenamiento."""
    train = matrix.loc[: pd.Timestamp(train_end)]
    return pd.Series({c: tukey_limit(train[c]) for c in matrix.columns})


def treat_outliers(matrix: pd.DataFrame, outliers: Iterable[tuple[str, date]], limits: pd.Series) -> pd.DataFrame:
    """Copia de la matriz con cada mes atípico sustituido por min(original, límite). Lo demás no cambia."""
    treated = matrix.copy()
    for clave, mes in outliers:
        f = pd.Timestamp(mes)
        treated.loc[f, clave] = min(matrix.loc[f, clave], limits[clave])
    return treated


def outlier_report(matrix: pd.DataFrame, treated: pd.DataFrame, outliers: Iterable[tuple[str, date]],
                   limits: pd.Series) -> pd.DataFrame:
    """Valor original, límite y valor tratado de cada mes atípico."""
    return pd.DataFrame([
        {"clave": c, "mes": pd.Timestamp(m).strftime("%Y-%m"), "original": matrix.loc[pd.Timestamp(m), c],
         "limite": limits[c], "tratado": treated.loc[pd.Timestamp(m), c]}
        for c, m in outliers
    ])


def other_exceedances(matrix: pd.DataFrame, outliers: Iterable[tuple[str, date]], limits: pd.Series,
                      train_end: date = config.TRAIN_END) -> pd.DataFrame:
    """Meses de entrenamiento que superan su límite y no están en la lista de atípicos (solo se reportan)."""
    tratados = {(c, pd.Timestamp(m)) for c, m in outliers}
    train = matrix.loc[: pd.Timestamp(train_end)]
    filas = [{"clave": c, "mes": f.strftime("%Y-%m"), "valor": train.loc[f, c], "limite": limits[c]}
             for c in train.columns for f in train.index[train[c] > limits[c]] if (c, f) not in tratados]
    return pd.DataFrame(filas, columns=["clave", "mes", "valor", "limite"])


# --- Orígenes móviles ---

def forecast_origin(target: pd.Timestamp, h: int) -> pd.Timestamp:
    """Último mes de datos disponible para pronosticar `target` a h meses."""
    return pd.Timestamp(target) - pd.DateOffset(months=h)


def history_until(series: pd.Series, origin: pd.Timestamp) -> pd.Series:
    """Serie hasta el origen, inclusive (ventana creciente)."""
    return series.loc[: pd.Timestamp(origin)]


def rolling_forecasts(forecast: ForecastFn, original: pd.DataFrame, treated: pd.DataFrame,
                      targets: Iterable[pd.Timestamp], horizons: Iterable[int], model: str) -> pd.DataFrame:
    """Pronósticos con origen móvil: se ajusta con la serie tratada y se compara con la original."""
    targets, horizons = list(targets), list(horizons)
    filas = []
    for clave in original.columns:
        for h in horizons:
            for target in targets:
                historia = history_until(treated[clave], forecast_origin(target, h))
                filas.append((clave, model, h, pd.Timestamp(target), original.loc[target, clave],
                              float(forecast(clave, historia, h))))
    return results_table(filas)


def results_table(rows: Iterable[tuple]) -> pd.DataFrame:
    """Tabla en el formato común: clave, modelo, horizonte, mes (AAAA-MM-01), real, pronostico."""
    df = pd.DataFrame(list(rows), columns=RESULT_COLUMNS)
    df["clave"] = df["clave"].astype(str)
    df["horizonte"] = df["horizonte"].astype(int)
    df["mes"] = pd.to_datetime(df["mes"]).dt.strftime("%Y-%m-01")
    return df


# --- Métricas ---

def mae(real: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(real) - np.asarray(pred))))


def rmse(real: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(real) - np.asarray(pred)) ** 2)))


def mape(real: np.ndarray, pred: np.ndarray) -> float:
    """Error porcentual absoluto medio, en %. Falla si hay ventas reales en cero."""
    real, pred = np.asarray(real, dtype=float), np.asarray(pred, dtype=float)
    if (real == 0).any():
        raise ZeroDivisionError("MAPE indefinido: hay meses con venta real igual a 0")
    return float(np.mean(np.abs(real - pred) / np.abs(real)) * 100)


def wape(real: np.ndarray, pred: np.ndarray) -> float:
    """Suma de errores absolutos entre suma de ventas reales, en %."""
    real, pred = np.asarray(real, dtype=float), np.asarray(pred, dtype=float)
    return float(np.abs(real - pred).sum() / np.abs(real).sum() * 100)


def summarize(results: pd.DataFrame) -> dict:
    r, p = results["real"].to_numpy(), results["pronostico"].to_numpy()
    return {"n": len(results), "mae": mae(r, p), "rmse": rmse(r, p), "mape": mape(r, p), "wape": wape(r, p)}


def metrics_table(results: pd.DataFrame) -> pd.DataFrame:
    """Métricas por producto, por producto y horizonte, globales y globales por horizonte."""
    filas = []
    for clave, g in results.groupby("clave", sort=False):
        filas.append({"nivel": "producto", "clave": clave, "horizonte": ALL, **summarize(g)})
    for (clave, h), g in results.groupby(["clave", "horizonte"], sort=False):
        filas.append({"nivel": "producto_horizonte", "clave": clave, "horizonte": h, **summarize(g)})
    filas.append({"nivel": "global", "clave": ALL, "horizonte": ALL, **summarize(results)})
    for h, g in results.groupby("horizonte"):
        filas.append({"nivel": "global_horizonte", "clave": ALL, "horizonte": h, **summarize(g)})
    df = pd.DataFrame(filas)
    df.insert(0, "modelo", results["modelo"].iloc[0])
    df["cumple_mape"] = df["mape"] <= config.MAPE_TARGET
    return df


def relative_reduction(model_metrics: pd.DataFrame, base_metrics: pd.DataFrame) -> pd.DataFrame:
    """Reducción relativa frente al base en cada métrica: 1 − modelo / base (positiva = mejor que el base)."""
    keys = ["nivel", "clave", "horizonte"]
    m = model_metrics.assign(horizonte=model_metrics["horizonte"].astype(str), clave=model_metrics["clave"].astype(str))
    b = base_metrics.assign(horizonte=base_metrics["horizonte"].astype(str), clave=base_metrics["clave"].astype(str))
    both = m.merge(b, on=keys, suffixes=("", "_base"), validate="one_to_one")
    for metric in ("mae", "rmse", "mape", "wape"):
        both[f"red_{metric}"] = 1 - both[metric] / both[f"{metric}_base"]
    return both


def wape_threshold(base_metrics: pd.DataFrame) -> float:
    """Umbral de WAPE: WAPE global del base × (1 − reducción mínima exigida)."""
    wape_base = base_metrics.loc[base_metrics["nivel"] == "global", "wape"].iloc[0]
    return float(wape_base * (1 - config.MIN_REDUCTION))


def comparison_table(model_metrics: pd.DataFrame, base_metrics: pd.DataFrame) -> pd.DataFrame:
    """Reducciones frente al base en todos los niveles y, en los globales, si el WAPE cumple el umbral."""
    comp = relative_reduction(model_metrics, base_metrics)
    threshold = wape_threshold(base_metrics)
    es_global = comp["nivel"].isin(["global", "global_horizonte"])
    comp["umbral_wape"] = np.where(es_global, threshold, np.nan)
    comp["cumple_umbral_wape"] = pd.Series(comp["wape"] <= threshold, dtype="boolean").where(es_global)
    return comp

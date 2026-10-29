"""Modelo SARIMA para los 10 productos con más piezas vendidas.

Qué hace este archivo, en orden:
  1. Lee las ventas mensuales de Supabase (solo lectura) y elige el top 10.
  2. Limpia los atípicos del periodo de entrenamiento (regla de Tukey).
  3. Por cada producto, elige una configuración SARIMA usando solo datos de entrenamiento.
  4. Pronostica cada mes de 2025 con anticipación de 1, 2 y 3 meses (origen móvil).
  5. Calcula el modelo base (promedio del mismo mes en años anteriores) para comparar.
  6. Guarda los resultados en CSV locales y muestra las métricas.

Reglas comunes del equipo (para que todos los modelos sean comparables):
  - Entrenamiento: ene-2022 a dic-2024. Prueba: ene-2025 a dic-2025. Nada de 2025 se usa para
    elegir configuraciones ni para calcular el umbral de atípicos.
  - Horizontes: 1, 2 y 3 meses (la vista de 3 meses del tablero muestra los pasos 1 a 3).
  - Métricas: MAE, RMSE, MAPE por producto y WAPE global.

Uso (desde la raíz del proyecto, con DATABASE_URL en .env):
    python -m src.models.sarima

Este archivo no escribe nada en la base de datos. Los resultados quedan en data/processed/
(carpeta ignorada por git: son ventas por producto, datos de la empresa).
"""

from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from src.db.repository import Repositorio, conectar

# ----------------------------------------------------------------------------------------
# 1. Parámetros del experimento
#    (cuando el equipo defina src/config.py, estas constantes se migran allí)
# ----------------------------------------------------------------------------------------

TOP_N = 10
FIRST_MONTH = date(2022, 1, 1)
LAST_MONTH = date(2026, 9, 1)  # último mes cerrado cargado en la base

TRAIN_END = pd.Timestamp("2024-12-01")
TEST_START = pd.Timestamp("2025-01-01")
TEST_END = pd.Timestamp("2025-12-01")
HORIZONS = (1, 2, 3)

# Atípicos (misma regla de 5.3.4): un mes es atípico si supera Q3 + 3 x RIC, con los cuartiles
# calculados solo sobre los meses con venta. Con menos de 8 meses con venta no se calcula.
TUKEY_K = 3.0
MIN_MONTHS_WITH_SALES = 8

# Configuraciones SARIMA candidatas: nombre -> (order, seasonal_order).
#   order = (p, d, q): memoria de los valores recientes (p), veces que se resta el mes anterior
#                      para quitar la tendencia (d) y memoria de los errores recientes (q).
#   seasonal_order = (P, D, Q, 12): lo mismo, pero comparando con el mismo mes del año anterior.
# Son pocas a propósito: con 36 meses de entrenamiento, más opciones solo producen sobreajuste.
CONFIGS = {
    # Pronostica el nivel reciente, corregido por el último error. Sirve cuando el nivel cambia.
    "(0,1,1)": ((0, 1, 1), (0, 0, 0, 0)),
    # Igual que la anterior, pero además deja que el último cambio "continúe" un poco.
    "(1,1,1)": ((1, 1, 1), (0, 0, 0, 0)),
    # Sin quitar tendencia: asume que las ventas oscilan alrededor de un promedio fijo.
    "(1,0,0)": ((1, 0, 0), (0, 0, 0, 0)),
    # SARIMA clásico: quita tendencia y patrón anual; "como el mismo mes del año pasado".
    "(0,1,1)(0,1,1,12)": ((0, 1, 1), (0, 1, 1, 12)),
    # Sin quitar tendencia, con memoria del mes anterior y del mismo mes del año pasado.
    "(1,0,0)(1,0,0,12)": ((1, 0, 0), (1, 0, 0, 12)),
}

MAX_ITER = 100  # límite de iteraciones del ajuste; con series cortas no hace falta más
OUTPUT_DIR = Path("data/processed")


# ----------------------------------------------------------------------------------------
# 2. Datos
# ----------------------------------------------------------------------------------------

def load_monthly_matrix(repo: Repositorio) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (productos, matriz) con la matriz de piezas: una fila por mes, una columna por clave."""
    products = repo.productos()
    sales = repo.ventas(FIRST_MONTH, LAST_MONTH)
    sales["fecha"] = pd.to_datetime(sales["fecha"])
    months = pd.date_range(FIRST_MONTH, LAST_MONTH, freq="MS")
    matrix = sales.pivot(index="fecha", columns="clave", values="cantidad").reindex(months)
    matrix.index.freq = "MS"  # statsmodels necesita saber que la serie es mensual
    return products, matrix


def select_top_products(products: pd.DataFrame, matrix: pd.DataFrame, n: int = TOP_N) -> list[str]:
    """Los n productos con más piezas en todo el historial (solo unidad PZA; los kg no se comparan)."""
    pieces = products.loc[products["unidad"] == "PZA", "clave"]
    totals = matrix[matrix.columns.intersection(pieces)].sum()
    return list(totals.nlargest(n).index)


# ----------------------------------------------------------------------------------------
# 3. Atípicos
# ----------------------------------------------------------------------------------------

def cap_outliers(series: pd.Series) -> tuple[pd.Series, int]:
    """Sustituye los meses atípicos por el límite de Tukey (Q3 + 3 x RIC).

    Se usa solo sobre el periodo de entrenamiento: así el umbral no "ve" el futuro. Un pedido
    extraordinario (por ejemplo 1,250 piezas cuando lo normal es 250) distorsionaría el ajuste
    del modelo, que lo interpretaría como un comportamiento que se repetirá.
    """
    with_sales = series[series > 0]
    if len(with_sales) < MIN_MONTHS_WITH_SALES:
        return series, 0
    q1, q3 = with_sales.quantile([0.25, 0.75])
    limit = q3 + TUKEY_K * (q3 - q1)
    return series.clip(upper=limit), int((series > limit).sum())


def prepare_series(raw: pd.Series) -> tuple[pd.Series, int]:
    """Limpia atípicos solo en entrenamiento; los meses de 2025 en adelante quedan sin tocar."""
    train, n_capped = cap_outliers(raw.loc[:TRAIN_END])
    series = pd.concat([train, raw.loc[TRAIN_END + pd.offsets.MonthBegin():]]).asfreq("MS")
    return series, n_capped


# ----------------------------------------------------------------------------------------
# 4. Ajuste y pronóstico de una configuración
# ----------------------------------------------------------------------------------------

def fit_forecast(history: pd.Series, config: str, steps: int = max(HORIZONS)):
    """Ajusta SARIMA con la historia dada y pronostica los siguientes `steps` meses.

    Devuelve (pronóstico, convergió). Si el ajuste falla devuelve (None, False): con series
    cortas algunas configuraciones estacionales a veces no se pueden estimar, y eso es esperable.
    """
    order, seasonal_order = CONFIGS[config]

    # Se divide entre el promedio para que la serie quede cerca de 1. No cambia el modelo
    # (SARIMA es lineal), pero ayuda al optimizador a converger. Al final se regresa a piezas.
    scale = float(history.mean()) or 1.0

    # Sin ninguna diferenciación (d = 0 y D = 0) el modelo necesita una constante ("trend='c'");
    # si no, los pronósticos tenderían a 0 en vez de al promedio de ventas.
    trend = "c" if order[1] == 0 and seasonal_order[1] == 0 else None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # avisos de convergencia: se cuentan abajo
            model = SARIMAX(history / scale, order=order, seasonal_order=seasonal_order, trend=trend)
            result = model.fit(disp=False, maxiter=MAX_ITER)
            forecast = result.get_forecast(steps).predicted_mean * scale
    except Exception:  # noqa: BLE001  (errores numéricos de statsmodels)
        return None, False

    converged = bool(getattr(result, "mle_retvals", {}).get("converged", True))
    return np.clip(forecast.to_numpy(), 0, None), converged  # las ventas no pueden ser negativas


def rolling_forecasts(series: pd.Series, config: str, first_target: pd.Timestamp,
                      last_target: pd.Timestamp) -> tuple[pd.DataFrame, int, int]:
    """Pronósticos de origen móvil con ventana creciente.

    Para cada mes objetivo y cada horizonte h (1, 2, 3) el pronóstico se hace desde el mes
    `objetivo - h`, usando solo los datos hasta ese mes. Cada vez que avanza el origen se
    vuelve a ajustar el modelo con un mes más de historia, como se haría en producción.

    Devuelve (pronósticos, ajustes fallidos, ajustes sin convergencia).
    """
    first_origin = first_target - pd.DateOffset(months=max(HORIZONS))
    last_origin = last_target - pd.DateOffset(months=min(HORIZONS))
    rows, failed, not_converged = [], 0, 0

    for origin in pd.date_range(first_origin, last_origin, freq="MS"):
        forecast, converged = fit_forecast(series.loc[:origin], config)
        if forecast is None:
            failed += 1
            continue
        not_converged += int(not converged)
        for h in HORIZONS:
            target = origin + pd.DateOffset(months=h)
            if first_target <= target <= last_target:
                rows.append({"mes": target, "horizonte": h, "pronostico": forecast[h - 1]})

    return pd.DataFrame(rows, columns=["mes", "horizonte", "pronostico"]), failed, not_converged


# ----------------------------------------------------------------------------------------
# 5. Elección de la configuración (solo con datos de entrenamiento)
# ----------------------------------------------------------------------------------------

def choose_config(train_series: pd.Series) -> tuple[str, pd.DataFrame]:
    """Elige la configuración con menor error en una validación dentro del entrenamiento.

    Se simula lo mismo que se hará en 2025, pero un año antes: se pronostican los meses de 2024
    con los datos disponibles en cada momento, y se compara el error absoluto medio (MAE).

    Por qué no se usa AIC: el AIC solo compara modelos con el mismo grado de diferenciación
    (d y D), y aquí las configuraciones cambian justo eso. Comparar su AIC daría una elección
    sin sentido, así que se compara su error al pronosticar.

    Una configuración que no se pueda ajustar en algún origen queda descartada.
    """
    errors = {}
    for name in CONFIGS:
        forecasts, failed, _ = rolling_forecasts(
            train_series, name, TRAIN_END - pd.DateOffset(months=11), TRAIN_END
        )
        actual = train_series.reindex(forecasts["mes"]).to_numpy()
        valid = failed == 0 and len(forecasts) == 12 * len(HORIZONS)
        errors[name] = float(np.mean(np.abs(forecasts["pronostico"].to_numpy() - actual))) if valid else np.inf

    table = pd.DataFrame({"mae_validacion": errors})
    best = table["mae_validacion"].idxmin() if np.isfinite(table["mae_validacion"]).any() else "(0,1,1)"
    return best, table


# ----------------------------------------------------------------------------------------
# 6. Modelo base
# ----------------------------------------------------------------------------------------

def base_forecasts(raw: pd.Series) -> pd.DataFrame:
    """Modelo base: promedio del mismo mes en los años de entrenamiento (replica el método actual).

    Se calcula con los datos originales (sin limpiar atípicos), porque así trabaja hoy compras.
    El valor depende solo del mes del año, así que es igual para los horizontes 1, 2 y 3.
    """
    average = raw.loc[:TRAIN_END].groupby(raw.loc[:TRAIN_END].index.month).mean()
    rows = [
        {"mes": month, "horizonte": h, "pronostico": float(average[month.month])}
        for month in pd.date_range(TEST_START, TEST_END, freq="MS")
        for h in HORIZONS
    ]
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------
# 7. Métricas
# ----------------------------------------------------------------------------------------

def compute_metrics(results: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """MAE, RMSE, MAPE y WAPE agrupando por las columnas indicadas en `by`.

    WAPE = suma de errores absolutos / suma de ventas reales. A diferencia del MAPE, no se
    distorsiona con meses de ventas bajas, y por eso se usa para el resultado global.
    """
    df = results.assign(error=results["real"] - results["pronostico"])
    df["abs_error"] = df["error"].abs()
    df["sq_error"] = df["error"] ** 2
    # El MAPE divide entre lo vendido: solo se calcula en meses con venta.
    df["ape"] = (df["abs_error"] / df["real"]).where(df["real"] > 0) * 100

    grouped = df.groupby(by)
    return pd.DataFrame({
        "MAE": grouped["abs_error"].mean(),
        "RMSE": np.sqrt(grouped["sq_error"].mean()),
        "MAPE_%": grouped["ape"].mean(),
        "WAPE_%": grouped["abs_error"].sum() / grouped["real"].sum() * 100,
    })


# ----------------------------------------------------------------------------------------
# 8. Ejecución
# ----------------------------------------------------------------------------------------

def run(repo: Repositorio) -> tuple[pd.DataFrame, pd.DataFrame]:
    products, matrix = load_monthly_matrix(repo)
    top = select_top_products(products, matrix)
    print(f"Top {TOP_N}: {', '.join(top)}\n")

    results, chosen = [], []
    for code in top:
        raw = matrix[code].astype(float)
        series, n_capped = prepare_series(raw)

        best, validation = choose_config(series.loc[:TRAIN_END])
        forecasts, failed, not_converged = rolling_forecasts(series, best, TEST_START, TEST_END)
        print(f"{code}: configuración {best} | atípicos recortados: {n_capped} | "
              f"ajustes fallidos: {failed} | sin convergencia: {not_converged}")

        actual = raw.reindex(forecasts["mes"]).to_numpy()
        results.append(forecasts.assign(clave=code, modelo="SARIMA", real=actual))
        base = base_forecasts(raw)
        results.append(base.assign(clave=code, modelo="base", real=raw.reindex(base["mes"]).to_numpy()))
        chosen.append({"clave": code, "configuracion": best, "atipicos_recortados": n_capped,
                       **{f"mae_val {k}": v for k, v in validation["mae_validacion"].items()}})

    columns = ["clave", "modelo", "horizonte", "mes", "real", "pronostico"]
    return pd.concat(results)[columns].reset_index(drop=True), pd.DataFrame(chosen)


def main() -> None:
    conn = conectar()
    try:
        results, chosen = run(Repositorio(conn))
    finally:
        conn.close()  # solo se leyó

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTPUT_DIR / "sarima_evaluacion.csv", index=False)
    chosen.to_csv(OUTPUT_DIR / "sarima_configuraciones.csv", index=False)

    per_product = compute_metrics(results, ["clave", "modelo"]).round(2)
    per_horizon = compute_metrics(results, ["modelo", "horizonte"]).round(2)
    overall = compute_metrics(results, ["modelo"]).round(2)
    print("\nMétricas por producto (36 pronósticos cada uno):\n", per_product.to_string())
    print("\nMétricas por horizonte:\n", per_horizon.to_string())
    print("\nMétricas globales (10 productos):\n", overall.to_string())
    print(f"\nResultados guardados en {OUTPUT_DIR}/ (sarima_evaluacion.csv, sarima_configuraciones.csv)")


if __name__ == "__main__":
    main()
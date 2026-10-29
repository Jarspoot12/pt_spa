"""Modelo base: pronóstico de un mes = promedio de ese mismo mes en los años
anteriores de la historia (replica el método actual de compras). Usa los valores
ORIGINALES, sin tratar atípicos, porque el método de la empresa no los trata.
Con el esquema de 2025 promedia siempre 2022, 2023 y 2024.
Ubicación: src/models/baseline.py
Ejecutar con: python -m src.models.baseline
"""
import pandas as pd

from src import config
from src.models import evaluation as ev

MODEL = "base"


def seasonal_mean_forecast(clave: str, history: pd.Series, h: int) -> float:
    """Promedio de los meses de la historia que caen en el mismo mes del calendario que el objetivo."""
    target = history.index[-1] + pd.DateOffset(months=h)
    same_month = history[history.index.month == target.month]
    if same_month.empty:
        raise ValueError(f"{clave}: no hay años anteriores para el mes {target:%Y-%m}")
    return float(same_month.mean())


def baseline_forecasts(original: pd.DataFrame, targets: pd.DatetimeIndex) -> pd.DataFrame:
    """Pronósticos del base con origen móvil: se calcula y se mide con la serie original."""
    return ev.rolling_forecasts(seasonal_mean_forecast, original, original, targets, config.HORIZONS, MODEL)


def main() -> None:
    original = ev.read_top10()
    targets = pd.date_range(config.TEST_START, config.TEST_END, freq="MS")
    results = baseline_forecasts(original, targets)
    metrics = ev.metrics_table(results)

    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(config.RESULTS_DIR / "base_top10.csv", index=False)
    metrics.to_csv(config.RESULTS_DIR / "metricas_base.csv", index=False)

    pd.set_option("display.width", 140)
    g = metrics[metrics["nivel"].isin(["global", "global_horizonte"])]
    print("WAPE del base (%):")
    print(g[["nivel", "horizonte", "n", "wape"]].round(4).to_string(index=False))
    wape_global = g.loc[g["nivel"] == "global", "wape"].iloc[0]
    print(f"Umbral de WAPE = {wape_global:.4f} × {1 - config.MIN_REDUCTION:.2f} = "
          f"{wape_global * (1 - config.MIN_REDUCTION):.4f} %")

    p = metrics[metrics["nivel"] == "producto"]
    print("\nMétricas del base por producto (36 pronósticos):")
    print(p[["clave", "n", "mae", "rmse", "mape", "wape", "cumple_mape"]].round(2).to_string(index=False))
    print(f"\nResultados guardados en {config.RESULTS_DIR}")


if __name__ == "__main__":
    main()

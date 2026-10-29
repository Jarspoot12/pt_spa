"""Prophet para el top 10: selección de parámetros por producto (solo con train)
y evaluación con origen móvil. Ubicación: src/models/prophet_model.py
Ejecutar con: python -m src.models.prophet_model [seleccion|evaluacion|comparacion]
(sin argumento: selección y evaluación; `comparacion` solo recalcula reducciones_prophet.csv, sin reentrenar)
"""
import argparse
import json
import logging

import numpy as np
import pandas as pd

from src import config
from src.models import evaluation as ev

MODEL = "prophet"
SEASONALITIES = ("ninguna", "fourier", "mes")   # en orden de simplicidad
MODES = ("additive", "multiplicative")
CHANGEPOINT_PRIOR_SCALES = (0.01, 0.05, 0.2)
FOURIER_ORDER = 3
MONTH_COLUMNS = [f"mes_{m:02d}" for m in range(2, 13)]   # enero es la referencia
PARAMS_FILE = config.RESULTS_DIR / "prophet_parametros.json"
REDUCTIONS_FILE = config.RESULTS_DIR / "reducciones_prophet.csv"


def silence_logs() -> None:
    """Silencia los mensajes de cmdstanpy y prophet (miles de ajustes)."""
    logging.getLogger("cmdstanpy").disabled = True
    logging.getLogger("prophet").setLevel(logging.CRITICAL)


# --- Rejilla y selección ---

def param_grid() -> list[dict]:
    """Las 15 combinaciones, ordenadas de la más simple a la más compleja."""
    return [{"estacionalidad": s, "modo": mode, "changepoint_prior_scale": cps}
            for s in SEASONALITIES
            for mode in ((None,) if s == "ninguna" else MODES)
            for cps in CHANGEPOINT_PRIOR_SCALES]


def complexity_rank(params: dict) -> tuple:
    """Desempate: ninguna < fourier < mes; aditivo < multiplicativo; menor changepoint_prior_scale."""
    return (SEASONALITIES.index(params["estacionalidad"]), int(params["modo"] == "multiplicative"),
            params["changepoint_prior_scale"])


def select_best(scores: list[tuple[dict, float]]) -> tuple[dict, float]:
    """Combinación con menor MAE; en empate, la más simple."""
    return min(scores, key=lambda s: (s[1], complexity_rank(s[0])))


# --- Ajuste y pronóstico ---

def month_dummies(dates: pd.Series) -> pd.DataFrame:
    """11 indicadoras del mes (febrero a diciembre); enero queda en cero en todas."""
    months = pd.DatetimeIndex(dates).month
    return pd.DataFrame({c: (months == m).astype(float) for c, m in zip(MONTH_COLUMNS, range(2, 13))},
                        index=dates.index)


def make_frame(dates: pd.Series, params: dict) -> pd.DataFrame:
    """Columnas de entrada de Prophet: `ds` y, con estacionalidad `mes`, las indicadoras."""
    frame = pd.DataFrame({"ds": dates})
    if params["estacionalidad"] == "mes":
        frame = frame.join(month_dummies(frame["ds"]))
    return frame


def build_model(params: dict):
    from prophet import Prophet

    mode = params["modo"] or "additive"
    model = Prophet(growth="linear", yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False,
                    seasonality_mode=mode, changepoint_prior_scale=params["changepoint_prior_scale"],
                    n_changepoints=5, changepoint_range=0.8, uncertainty_samples=0)
    if params["estacionalidad"] == "fourier":
        model.add_seasonality(name="anual", period=365.25, fourier_order=FOURIER_ORDER, mode=mode)
    elif params["estacionalidad"] == "mes":
        for c in MONTH_COLUMNS:
            model.add_regressor(c, mode=mode)
    return model


class ProphetForecaster:
    """Pronóstico con la interfaz de `ev.rolling_forecasts`. Ajusta una vez por (producto, origen):
    los horizontes de un mismo origen comparten el ajuste. Recorta negativos a 0 y los registra."""

    def __init__(self, params_by_clave: dict[str, dict]):
        self.params_by_clave = params_by_clave
        self.fitted = {}
        self.negatives = []   # (clave, mes objetivo, h, valor original)

    def __call__(self, clave: str, history: pd.Series, h: int) -> float:
        params = self.params_by_clave[clave]
        origin = history.index[-1]
        if (clave, origin) not in self.fitted:
            train = make_frame(pd.Series(history.index), params).assign(y=history.to_numpy())
            model = build_model(params)
            np.random.seed(config.SEED)
            model.fit(train, seed=config.SEED)
            self.fitted[(clave, origin)] = model
        model = self.fitted[(clave, origin)]
        future = model.make_future_dataframe(periods=h, freq="MS")
        target = make_frame(future["ds"], params).iloc[[-1]]
        yhat = float(model.predict(target)["yhat"].iloc[0])
        if yhat < 0:
            self.negatives.append((clave, target["ds"].iloc[0].strftime("%Y-%m"), h, yhat))
            return 0.0
        return yhat


# --- Selección con validación interna (2024) ---

def select_params(original: pd.DataFrame, treated: pd.DataFrame) -> dict:
    """Elige por producto la combinación con menor MAE en 2024 (h = 1, 2, 3), sin ver 2025."""
    train_end = pd.Timestamp(config.TRAIN_END)
    original, treated = original.loc[:train_end], treated.loc[:train_end]
    targets = pd.date_range(config.VALIDATION_START, config.VALIDATION_END, freq="MS")
    chosen = {}
    for i, clave in enumerate(original.columns, 1):
        scores, negatives = [], 0
        for params in param_grid():
            f = ProphetForecaster({clave: params})
            res = ev.rolling_forecasts(f, original[[clave]], treated[[clave]], targets, config.HORIZONS, MODEL)
            scores.append((params, ev.mae(res["real"], res["pronostico"])))
            negatives += len(f.negatives)
        best, best_mae = select_best(scores)
        chosen[clave] = {**best, "mae_validacion": best_mae, "mae_referencia": scores[0][1],
                         "negativos_recortados": negatives}
        print(f"[{i}/{len(original.columns)}] {clave}: {best['estacionalidad']}, {best['modo']}, "
              f"cps={best['changepoint_prior_scale']} · MAE {best_mae:.2f} (referencia {scores[0][1]:.2f})")
    return chosen


def run_selection() -> None:
    import prophet

    original = ev.read_top10()
    treated = ev.treat_outliers(original, config.OUTLIER_MONTHS, ev.train_limits(original))
    chosen = select_params(original, treated)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"prophet": prophet.__version__, "semilla": config.SEED,
            "validacion": f"{config.VALIDATION_START:%Y-%m} a {config.VALIDATION_END:%Y-%m}",
            "horizontes": list(config.HORIZONS), "criterio": "menor MAE (36 pronósticos)"}
    PARAMS_FILE.write_text(json.dumps({"meta": meta, "productos": chosen}, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    tabla = pd.DataFrame.from_dict(chosen, orient="index")
    print("\nEstacionalidad elegida:")
    print(tabla["estacionalidad"].value_counts().to_string())
    print(f"Pronósticos negativos recortados en la validación: {int(tabla['negativos_recortados'].sum())}")
    print(f"Parámetros guardados en {PARAMS_FILE}")


def load_params() -> dict[str, dict]:
    """Configuración elegida por producto (archivo de la selección)."""
    productos = json.loads(PARAMS_FILE.read_text(encoding="utf-8"))["productos"]
    return {c: {k: p[k] for k in ("estacionalidad", "modo", "changepoint_prior_scale")} for c, p in productos.items()}


# --- Evaluación en test (2025) ---

def evaluate(original: pd.DataFrame, treated: pd.DataFrame, params: dict[str, dict]) -> tuple[pd.DataFrame, list]:
    """Origen móvil sobre 2025 con los parámetros fijos: se reajusta con más datos, no se vuelven a elegir."""
    f = ProphetForecaster(params)
    targets = pd.date_range(config.TEST_START, config.TEST_END, freq="MS")
    return ev.rolling_forecasts(f, original, treated, targets, config.HORIZONS, MODEL), f.negatives


def run_evaluation() -> None:
    original = ev.read_top10()
    treated = ev.treat_outliers(original, config.OUTLIER_MONTHS, ev.train_limits(original))
    params = load_params()
    results, negatives = evaluate(original, treated, params)
    repeat, _ = evaluate(original, treated, params)
    reproducible = results.equals(repeat)
    metrics = ev.metrics_table(results)
    results.to_csv(config.RESULTS_DIR / "prophet_top10.csv", index=False)
    metrics.to_csv(config.RESULTS_DIR / "metricas_prophet.csv", index=False)

    ph = metrics[metrics["nivel"] == "producto_horizonte"]
    print("MAE por producto y horizonte:")
    print(ph.pivot(index="clave", columns="horizonte", values="mae").round(2).loc[list(config.TOP10_CLAVES)]
          .to_string())

    por_h = results.pivot_table(index=["clave", "mes"], columns="horizonte", values="pronostico")
    identicos = int(((por_h[1] == por_h[2]) & (por_h[2] == por_h[3])).sum())
    print(f"\nNegativos recortados: {len(negatives)} {negatives if negatives else ''}")
    print(f"(clave, mes) con pronóstico idéntico en h=1, 2 y 3: {identicos} de {len(por_h)}")
    print(f"Reproducible (dos corridas idénticas): {reproducible}")
    print(f"Resultados guardados en {config.RESULTS_DIR}\n")
    run_comparison()


# --- Comparación con el base (sin reentrenar) ---

def run_comparison() -> None:
    """Lee las métricas guardadas de Prophet y del base y guarda reducciones_prophet.csv."""
    read = {"dtype": {"clave": str, "horizonte": str}}
    metrics = pd.read_csv(config.RESULTS_DIR / "metricas_prophet.csv", **read)
    base = pd.read_csv(config.RESULTS_DIR / "metricas_base.csv", **read)
    comp = ev.comparison_table(metrics, base)
    comp.to_csv(REDUCTIONS_FILE, index=False)

    pd.set_option("display.width", 160)
    g = comp[comp["nivel"].isin(["global", "global_horizonte"])]
    print(f"WAPE (%), umbral = {ev.wape_threshold(base):.4f}:")
    print(g[["horizonte", "wape", "wape_base", "red_wape", "cumple_umbral_wape"]].round(4).to_string(index=False))
    p = comp[comp["nivel"] == "producto"]
    print("\nPor producto (36 pronósticos):")
    print(p[["clave", "mae", "mae_base", "red_mae", "rmse", "rmse_base", "red_rmse", "mape", "mape_base",
             "red_mape", "wape", "wape_base", "red_wape", "cumple_mape"]].round(4).to_string(index=False))
    print(f"Comparación guardada en {REDUCTIONS_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prophet para el top 10")
    parser.add_argument("fase", nargs="?", default="todo",
                        choices=["seleccion", "evaluacion", "comparacion", "todo"])
    args = parser.parse_args()
    silence_logs()
    if args.fase in ("seleccion", "todo"):
        run_selection()
    if args.fase in ("evaluacion", "todo"):
        run_evaluation()
    if args.fase == "comparacion":
        run_comparison()


if __name__ == "__main__":
    main()

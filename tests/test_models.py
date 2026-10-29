"""Pruebas de las funciones comunes de modelado y del modelo base, con datos
sintéticos y sin base de datos. Ubicación: tests/test_models.py
Ejecutar con: python -m pytest tests
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.models import evaluation as ev
from src.models.baseline import baseline_forecasts, seasonal_mean_forecast

MESES_48 = pd.date_range("2022-01-01", "2025-12-01", freq="MS")


def matriz_sintetica():
    """Dos productos, 48 meses. 'A' vale 100 + mes del calendario; 'B' vale 10 salvo un pico."""
    a = pd.Series(100.0 + MESES_48.month, index=MESES_48)
    b = pd.Series(10.0, index=MESES_48)
    b[pd.Timestamp("2023-10-01")] = 500.0
    b[pd.Timestamp("2025-03-01")] = 900.0  # pico en test: nunca se trata
    m = pd.DataFrame({"A": a, "B": b})
    m.index.freq = "MS"
    return m


def ventas_largas(m):
    return m.reset_index(names="fecha").melt(id_vars="fecha", var_name="clave", value_name="cantidad")


# --- Carga ---

def test_matriz_mensual_completa():
    m = matriz_sintetica()
    out = ev.build_monthly_matrix(ventas_largas(m), ["A", "B"], date(2022, 1, 1), date(2025, 12, 1))
    assert out.shape == (48, 2) and out.index.freqstr == "MS"
    pd.testing.assert_frame_equal(out, m, check_names=False, check_freq=False, check_index_type=False)


def test_matriz_con_hueco_falla():
    v = ventas_largas(matriz_sintetica())
    v = v[~((v["clave"] == "A") & (v["fecha"] == "2023-05-01"))]
    with pytest.raises(AssertionError, match="faltantes"):
        ev.build_monthly_matrix(v, ["A", "B"], date(2022, 1, 1), date(2025, 12, 1))


def test_matriz_con_fecha_posterior_falla():
    v = ventas_largas(matriz_sintetica())
    with pytest.raises(AssertionError, match="posteriores"):
        ev.build_monthly_matrix(v, ["A", "B"], date(2022, 1, 1), date(2025, 11, 1))


def test_clave_se_lee_como_texto():
    v = ventas_largas(matriz_sintetica().rename(columns={"A": 1014, "B": 8811}))
    out = ev.build_monthly_matrix(v, ["1014", "8811"], date(2022, 1, 1), date(2025, 12, 1))
    assert list(out.columns) == ["1014", "8811"]


# --- Atípicos ---

def test_limite_tukey_ignora_ceros():
    s = pd.Series([0, 0, 1, 2, 3, 4, 5])
    q1, q3 = pd.Series([1, 2, 3, 4, 5]).quantile([0.25, 0.75])
    assert ev.tukey_limit(s) == pytest.approx(q3 + 3 * (q3 - q1))


def test_limite_solo_con_train():
    m = matriz_sintetica()
    lim = ev.train_limits(m, date(2024, 12, 1))
    m2 = m.copy()
    m2.loc["2025-01-01":, "B"] = 10_000.0  # cambiar el test no mueve el límite
    pd.testing.assert_series_equal(lim, ev.train_limits(m2, date(2024, 12, 1)))
    assert lim["B"] == pytest.approx(10.0)


def test_tratamiento_solo_meses_listados():
    m = matriz_sintetica()
    lim = ev.train_limits(m, date(2024, 12, 1))
    t = ev.treat_outliers(m, [("B", date(2023, 10, 1))], lim)
    assert t.loc["2023-10-01", "B"] == lim["B"] == pytest.approx(10.0)
    assert m.loc["2023-10-01", "B"] == 500.0  # el original no se toca
    assert t.loc["2025-03-01", "B"] == 900.0  # el test nunca se modifica
    assert (t.drop(index=pd.Timestamp("2023-10-01")) == m.drop(index=pd.Timestamp("2023-10-01"))).all().all()


def test_tratado_es_el_menor():
    m = matriz_sintetica()
    lim = pd.Series({"A": 1_000.0, "B": 1_000.0})
    t = ev.treat_outliers(m, [("B", date(2023, 10, 1))], lim)
    assert t.loc["2023-10-01", "B"] == 500.0


def test_otros_excesos_se_reportan():
    m = matriz_sintetica()
    lim = ev.train_limits(m, date(2024, 12, 1))
    assert ev.other_exceedances(m, [("B", date(2023, 10, 1))], lim, date(2024, 12, 1)).empty
    otros = ev.other_exceedances(m, [], lim, date(2024, 12, 1))
    assert otros[["clave", "mes"]].values.tolist() == [["B", "2023-10"]]


# --- Orígenes móviles ---

@pytest.mark.parametrize("h", [1, 2, 3])
def test_origen_sin_fuga(h):
    m = matriz_sintetica()
    target = pd.Timestamp("2025-01-01")
    origin = ev.forecast_origin(target, h)
    hist = ev.history_until(m["A"], origin)
    assert origin == target - pd.DateOffset(months=h)
    assert hist.index.max() == origin < target
    assert len(hist) == 36 - h + 1  # ventana creciente desde 2022-01


def test_rolling_ajusta_con_tratada_y_mide_con_original():
    m = matriz_sintetica()
    lim = ev.train_limits(m, date(2024, 12, 1))
    t = ev.treat_outliers(m, [("B", date(2023, 10, 1))], lim)
    vistos = []

    def espia(clave, history, h):
        vistos.append((clave, h, history.index.max(), history.max()))
        return 0.0

    # Validación interna: el objetivo 2023-10 se mide contra el original (500)
    res = ev.rolling_forecasts(espia, m, t, [pd.Timestamp("2023-10-01"), pd.Timestamp("2024-01-01")],
                               [1, 2, 3], "x")
    assert len(res) == 2 * 3 * 2
    assert res.loc[(res["clave"] == "B") & (res["mes"] == "2023-10-01"), "real"].eq(500.0).all()
    assert all(fin <= pd.Timestamp("2024-01-01") - pd.DateOffset(months=h) for _, h, fin, _ in vistos)
    assert max(mx for c, _, _, mx in vistos if c == "B") == pytest.approx(10.0)  # nunca vio el 500


def test_tabla_resultados_formato():
    res = ev.results_table([(1014, "base", 1, pd.Timestamp("2025-01-01"), 5.0, 4.0)])
    assert list(res.columns) == ev.RESULT_COLUMNS
    assert res.loc[0, "clave"] == "1014" and res.loc[0, "mes"] == "2025-01-01"


# --- Métricas ---

def test_metricas_valores_conocidos():
    real, pred = np.array([10, 20, 40]), np.array([12, 15, 40])
    assert ev.mae(real, pred) == pytest.approx(7 / 3)
    assert ev.rmse(real, pred) == pytest.approx(np.sqrt((4 + 25) / 3))
    assert ev.mape(real, pred) == pytest.approx((0.2 + 0.25 + 0) / 3 * 100)
    assert ev.wape(real, pred) == pytest.approx(7 / 70 * 100)


def test_mape_con_cero_falla():
    with pytest.raises(ZeroDivisionError):
        ev.mape(np.array([0, 10]), np.array([1, 10]))


def test_tabla_metricas_niveles():
    filas = [(c, "m", h, pd.Timestamp(f"2025-{i:02d}-01"), 10.0, 10.0 + (h if c == "A" else 0))
             for c in ["A", "B"] for h in [1, 2, 3] for i in range(1, 13)]
    met = ev.metrics_table(ev.results_table(filas))
    n = met.set_index(["nivel", "clave", "horizonte"])["n"]
    assert n["producto", "A", ev.ALL] == 36 and n["producto_horizonte", "A", 2] == 12
    assert n["global", ev.ALL, ev.ALL] == 72 and n["global_horizonte", ev.ALL, 3] == 24
    w = met.set_index(["nivel", "clave", "horizonte"])["wape"]
    assert w["global", ev.ALL, ev.ALL] == pytest.approx((12 * (1 + 2 + 3)) / 720 * 100)
    assert w["global_horizonte", ev.ALL, 3] == pytest.approx(36 / 240 * 100)
    assert met.loc[met["clave"] == "B", "cumple_mape"].all()


# --- Modelo base ---

def test_base_promedia_mismo_mes_de_anios_anteriores():
    m = matriz_sintetica()
    m.loc["2022-03-01", "A"], m.loc["2023-03-01", "A"], m.loc["2024-03-01", "A"] = 30.0, 60.0, 90.0
    hist = ev.history_until(m["A"], pd.Timestamp("2025-02-01"))
    assert seasonal_mean_forecast("A", hist, 1) == pytest.approx(60.0)


def test_base_no_depende_del_horizonte():
    m = matriz_sintetica()
    res = baseline_forecasts(m, pd.date_range("2025-01-01", "2025-12-01", freq="MS"))
    assert len(res) == 2 * 3 * 12
    por_h = res.pivot_table(index=["clave", "mes"], columns="horizonte", values="pronostico")
    assert (por_h[1] == por_h[2]).all() and (por_h[1] == por_h[3]).all()
    # 'A' = 100 + mes en todos los años: el promedio es exacto
    a = res[res["clave"] == "A"]
    assert np.allclose(a["pronostico"], 100 + pd.to_datetime(a["mes"]).dt.month)


def test_base_usa_valores_originales_en_meses_atipicos():
    # 'B' tiene un atípico de 500 en 2023-10: el base no lo trata (replica el método de la empresa)
    m = matriz_sintetica()
    res = baseline_forecasts(m, pd.date_range("2025-01-01", "2025-12-01", freq="MS"))
    b = res[res["clave"] == "B"].set_index(["mes", "horizonte"])["pronostico"]
    for h in (1, 2, 3):
        assert b["2025-10-01", h] == pytest.approx((10.0 + 500.0 + 10.0) / 3)
        assert b["2025-09-01", h] == pytest.approx(10.0)  # los demás meses no cambian
    # y el error se mide contra el original de 2025 (el pico de 900 en marzo no se toca)
    assert res.loc[(res["clave"] == "B") & (res["mes"] == "2025-03-01"), "real"].eq(900.0).all()


# --- Prophet ---

def test_rejilla_prophet_15_en_orden_de_simplicidad():
    from src.models import prophet_model as pm
    grid = pm.param_grid()
    assert len(grid) == 15 and len({tuple(p.values()) for p in grid}) == 15
    assert grid[0] == {"estacionalidad": "ninguna", "modo": None, "changepoint_prior_scale": 0.01}
    assert sum(p["estacionalidad"] == "ninguna" for p in grid) == 3
    assert grid == sorted(grid, key=pm.complexity_rank)


def test_seleccion_desempata_por_simplicidad():
    from src.models import prophet_model as pm
    g = pm.param_grid()
    assert pm.select_best([(g[14], 5.0), (g[3], 5.0), (g[1], 5.0)])[0] == g[1]
    assert pm.select_best([(g[0], 6.0), (g[14], 5.0)])[0] == g[14]


def test_indicadoras_del_mes():
    from src.models import prophet_model as pm
    d = pm.month_dummies(pd.Series(pd.date_range("2024-01-01", "2024-12-01", freq="MS")))
    assert list(d.columns) == pm.MONTH_COLUMNS and len(pm.MONTH_COLUMNS) == 11
    assert d.iloc[0].sum() == 0 and (d.iloc[1:].sum(axis=1) == 1).all()


def test_prophet_ajusta_una_vez_por_origen_y_llena_indicadoras_futuras():
    from src.models import prophet_model as pm
    pm.silence_logs()
    m = matriz_sintetica()
    params = {"estacionalidad": "mes", "modo": "additive", "changepoint_prior_scale": 0.05}
    f = pm.ProphetForecaster({"A": params})
    hist = ev.history_until(m["A"], pd.Timestamp("2024-09-01"))
    preds = [f("A", hist, h) for h in (1, 2, 3)]
    assert len(f.fitted) == 1
    # 'A' = 100 + mes: con indicadoras del mes el pronóstico de oct, nov y dic debe acercarse a 110, 111, 112
    assert np.allclose(preds, [110, 111, 112], atol=1.0)


def test_prophet_recorta_negativos():
    from src.models import prophet_model as pm
    pm.silence_logs()
    idx = pd.date_range("2022-01-01", periods=36, freq="MS")
    serie = pd.Series(np.linspace(1000, 10, 36), index=idx)
    params = {"estacionalidad": "ninguna", "modo": None, "changepoint_prior_scale": 0.2}
    f = pm.ProphetForecaster({"X": params})
    assert f("X", serie, 3) == 0.0
    assert len(f.negatives) == 1 and f.negatives[0][3] < 0


def test_reduccion_relativa():
    mod = pd.DataFrame({"nivel": ["producto"], "clave": ["A"], "horizonte": [ev.ALL],
                        "mae": [8.0], "rmse": [12.0], "mape": [30.0], "wape": [20.0]})
    base = pd.DataFrame({"nivel": ["producto"], "clave": ["A"], "horizonte": [ev.ALL],
                         "mae": [10.0], "rmse": [10.0], "mape": [40.0], "wape": [25.0]})
    r = ev.relative_reduction(mod, base).iloc[0]
    assert r["red_mae"] == pytest.approx(0.2) and r["red_rmse"] == pytest.approx(-0.2)
    assert r["red_mape"] == pytest.approx(0.25) and r["red_wape"] == pytest.approx(0.2)


def test_reduccion_relativa_cruza_horizonte_texto_y_entero():
    mod = pd.DataFrame({"nivel": ["global_horizonte"], "clave": [ev.ALL], "horizonte": [2],
                        "mae": [5.0], "rmse": [5.0], "mape": [5.0], "wape": [5.0]})
    base = mod.assign(horizonte="2", mae=10.0)  # como se lee de un CSV
    assert ev.relative_reduction(mod, base)["red_mae"].iloc[0] == pytest.approx(0.5)


def test_umbral_wape_y_cumplimiento():
    base = pd.DataFrame({"nivel": ["global", "global_horizonte", "producto"], "clave": [ev.ALL, ev.ALL, "A"],
                         "horizonte": [ev.ALL, "1", ev.ALL], "mae": 1.0, "rmse": 1.0, "mape": 1.0,
                         "wape": [40.0, 40.0, 40.0]})
    assert ev.wape_threshold(base) == pytest.approx(34.0)
    mod = base.assign(wape=[33.0, 35.0, 10.0], horizonte=[ev.ALL, 1, ev.ALL])
    comp = ev.comparison_table(mod, base).set_index("nivel")
    assert comp.loc["global", "cumple_umbral_wape"] and not comp.loc["global_horizonte", "cumple_umbral_wape"]
    assert pd.isna(comp.loc["producto", "cumple_umbral_wape"])  # el umbral es solo global
    assert comp.loc["global", "umbral_wape"] == pytest.approx(34.0)

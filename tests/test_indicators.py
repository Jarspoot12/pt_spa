"""Pruebas de los indicadores del tablero con datos sintéticos.
Ubicación: tests/test_indicators.py
Ejecutar con: python -m pytest tests
"""
import math
from datetime import date

import pandas as pd
import pytest

from src.db.repository import COLUMNAS_PRONOSTICOS
from src.features.indicators import (
    expected_change,
    export_csv,
    forecast_table,
    latest_forecasts,
    month_label,
    months_ahead,
    peak_and_low,
    reliability_level,
    reliability_message,
)

SEP, OCT, NOV, DIC = date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)


def hacer_proyecciones():
    """Dos corridas: la vieja (corte agosto) y la vigente (corte septiembre, 3 meses)."""
    filas = [("A", date(2026, 8, 1), SEP, 50.0)]
    filas += [("A", SEP, f, q) for f, q in ((OCT, 110.0), (NOV, 120.0), (DIC, 130.0))]
    filas += [("B", SEP, f, q) for f, q in ((OCT, 40.0), (NOV, 45.0), (DIC, 50.0))]
    return pd.DataFrame(filas, columns=COLUMNAS_PRONOSTICOS)


def test_month_label():
    assert month_label(SEP) == "septiembre 2026"
    assert month_label(SEP, short=True) == "sep-2026"


def test_months_ahead_cruza_anio():
    assert months_ahead(date(2026, 11, 1), date(2027, 1, 1)) == 2


@pytest.mark.parametrize("months, esperados", [(1, [OCT]), (2, [OCT, NOV]), (3, [OCT, NOV, DIC])])
def test_latest_forecasts_acumula_meses_de_la_ultima_corrida(months, esperados):
    out = latest_forecasts(hacer_proyecciones(), months)
    assert set(out["fecha_corte"]) == {SEP}
    assert list(out[out["clave"] == "A"]["fecha"]) == esperados


def test_latest_forecasts_vacio_y_fuera_de_rango():
    vacio = hacer_proyecciones().iloc[0:0]
    assert latest_forecasts(vacio, 3).empty
    with pytest.raises(ValueError):
        latest_forecasts(hacer_proyecciones(), 4)


def test_expected_change():
    assert expected_change(110, 100) == pytest.approx(10.0)
    assert expected_change(80, 100) == pytest.approx(-20.0)
    assert math.isnan(expected_change(50, 0))


def test_peak_and_low_en_periodo_filtrado_y_empate():
    ventas = pd.DataFrame({"fecha": [date(2025, m, 1) for m in (3, 1, 2, 4)], "cantidad": [90, 10, 90, 10]})
    (f_hi, q_hi), (f_lo, q_lo) = peak_and_low(ventas)
    assert (f_hi, q_hi) == (date(2025, 2, 1), 90)  # empate: gana el mes más antiguo
    assert (f_lo, q_lo) == (date(2025, 1, 1), 10)
    with pytest.raises(ValueError):
        peak_and_low(ventas.iloc[0:0])


@pytest.mark.parametrize("error, nivel", [(20.0, "alta"), (20.1, "media"), (40.0, "media"),
                                          (40.1, "baja"), (math.nan, None), (None, None)])
def test_reliability_level(error, nivel):
    assert reliability_level(error) == nivel


def test_reliability_message_solo_si_no_es_alta():
    assert reliability_message(15.0) is None
    assert "Confiabilidad media" in reliability_message(30.0)
    assert "56 %" in reliability_message(55.6)


def test_forecast_table_y_csv():
    ventas = pd.DataFrame({"clave": ["A", "B"], "fecha": [SEP, SEP], "cantidad": [100.0, 0.0]})
    productos = pd.DataFrame({"clave": ["A", "B"], "descripcion": ["Aceite", "Jabón"]})
    tabla = forecast_table(latest_forecasts(hacer_proyecciones(), 2), ventas, productos)
    a = tabla[tabla["clave"] == "A"]
    assert list(a["variacion_pct"]) == [10.0, 20.0]
    assert tabla[tabla["clave"] == "B"]["variacion_pct"].isna().all()  # último mes en 0
    csv = export_csv(tabla).decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("Clave,Producto,Mes proyectado,Piezas proyectadas")
    assert "Jabón" in csv


def test_forecast_table_sin_proyecciones():
    vacio = latest_forecasts(hacer_proyecciones().iloc[0:0], 1)
    assert forecast_table(vacio, pd.DataFrame(), pd.DataFrame()).empty

"""Tablero de proyección de demanda para compras y finanzas (Objetivo 6).
Solo lee resultados ya calculados en Supabase y llama a src/; no entrena ni calcula modelos.
Ubicación: app/streamlit_app.py
Ejecutar desde la raíz: streamlit run app/streamlit_app.py
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # para importar src/ al ejecutar con streamlit

from src.config import CACHE_MINUTES, HORIZONS, TOP10_CLAVES
from src.db.repository import Repositorio, conectar
from src.features.indicators import (
    export_csv,
    forecast_table,
    latest_forecasts,
    month_label,
    peak_and_low,
)

HISTORY_COLOR = "#2a78d6"   # azul: lo que ya se vendió
FORECAST_COLOR = "#eb6834"  # naranja: lo que se espera vender
HISTORY_START = date(2022, 1, 1)
# Tarjetas (st.metric) con borde y sombra ligera; los grises translúcidos funcionan en tema claro y oscuro.
CARD_CSS = """
<style>
div[data-testid="stMetric"] {
    border: 1px solid rgba(128, 128, 128, 0.28);
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.05);
}
</style>
"""
HORIZON_LABELS = {1: "Próximo mes", 2: "Próximos 2 meses", 3: "Próximos 3 meses"}


@st.cache_data(ttl=CACHE_MINUTES * 60, show_spinner="Cargando datos…")
def load_data():
    """Lee una sola vez productos, ventas y proyecciones de los 10 productos modelados."""
    with conectar() as conn:
        repo = Repositorio(conn)
        last_closed = repo.ultima_fecha()
        products = repo.productos()
        sales = repo.ventas(HISTORY_START, last_closed)
        forecasts = repo.pronosticos()
    products = products[products["clave"].isin(TOP10_CLAVES)]
    sales = sales[sales["clave"].isin(TOP10_CLAVES)]
    forecasts = forecasts[forecasts["clave"].isin(TOP10_CLAVES)]
    return products, sales, forecasts, last_closed


def product_label(clave: str, products: pd.DataFrame) -> str:
    desc = products.set_index("clave")["descripcion"].get(clave, "")
    return f"{clave} · {desc}"


def build_chart(history: pd.DataFrame, forecasts: pd.DataFrame, peak, low, last_point) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=history["fecha"], y=history["cantidad"], name="Ventas reales",
        mode="lines+markers", line={"color": HISTORY_COLOR, "width": 2}, marker={"size": 6},
        customdata=[month_label(f) for f in history["fecha"]],
        hovertemplate="%{customdata}<br>%{y:,.0f} piezas vendidas<extra></extra>",
    ))
    if not forecasts.empty:
        # La línea de proyección arranca en el último mes cerrado para que se lea como continuación.
        x = [last_point[0]] + list(forecasts["fecha"])
        y = [last_point[1]] + list(forecasts["cantidad"])
        fig.add_trace(go.Scatter(
            x=x, y=y, name="Proyección", mode="lines+markers",
            line={"color": FORECAST_COLOR, "width": 2, "dash": "dash"}, marker={"size": 8},
            customdata=[month_label(f) for f in x],
            hovertemplate="%{customdata}<br>%{y:,.0f} piezas<extra></extra>",
        ))
    for (f, qty), text in ((peak, "Mayor venta"), (low, "Menor venta")):
        fig.add_annotation(x=f, y=qty, text=f"{text}<br>{qty:,.0f}", showarrow=True, arrowhead=0,
                           ay=-36 if text == "Mayor venta" else 36, font={"size": 12})
    ticks = sorted(set(history["fecha"]) | set(forecasts["fecha"]))
    step = max(1, len(ticks) // 12)
    fig.update_layout(
        height=420, margin={"l": 8, "r": 8, "t": 24, "b": 8}, hovermode="closest",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        yaxis={"title": "Piezas por mes", "rangemode": "tozero", "separatethousands": True},
        xaxis={"tickvals": ticks[::step], "ticktext": [month_label(f, short=True) for f in ticks[::step]]},
    )
    return fig


def show_change_metrics(table: pd.DataFrame) -> None:
    cols = st.columns(len(table))
    for col, r in zip(cols, table.itertuples()):
        delta = None if pd.isna(r.variacion_pct) else f"{r.variacion_pct:+.1f} % vs. {r.ultimo_mes_cerrado}"
        col.metric(f"Proyección {r.mes}", f"{r.piezas_proyectadas:,} piezas", delta)


def main() -> None:
    st.set_page_config(page_title="Proyección de demanda", page_icon="📦", layout="wide")
    st.markdown(CARD_CSS, unsafe_allow_html=True)
    products, sales, forecasts, last_closed = load_data()

    st.title("Proyección de demanda por producto")
    st.caption(f"Datos al cierre de {month_label(last_closed)}. Se actualizan una vez al mes, "
               "cuando se cierra el mes. La proyección es una referencia para planear compras; "
               "la decisión final es del equipo.")

    months = sorted(sales["fecha"].unique())
    f1, f2a, f2b, f3 = st.columns([2, 1.25, 1.25, 2])
    clave = f1.selectbox("Producto", TOP10_CLAVES, format_func=lambda c: product_label(c, products))
    start = f2a.selectbox("Ventas desde", months, index=0, format_func=month_label)
    end_options = [f for f in months if f >= start]  # "hasta" nunca puede quedar antes de "desde"
    end = f2b.selectbox("Ventas hasta", end_options, index=len(end_options) - 1, format_func=month_label)
    horizon = f3.radio("Meses a proyectar", HORIZONS, index=len(HORIZONS) - 1,
                       format_func=HORIZON_LABELS.get, horizontal=True)

    product_sales = sales[sales["clave"] == clave].sort_values("fecha")
    history = product_sales[product_sales["fecha"].between(start, end)]
    selected = latest_forecasts(forecasts, horizon)
    table_all = forecast_table(selected, sales, products)
    product_forecasts = selected[selected["clave"] == clave]
    table = table_all[table_all["clave"] == clave]

    st.subheader(product_label(clave, products))
    if product_forecasts.empty:
        st.info("Las proyecciones todavía no están disponibles. Aparecerán aquí en cuanto se publiquen; "
                "mientras tanto puedes consultar las ventas reales.")
    else:
        show_change_metrics(table)

    peak, low = peak_and_low(history)
    m1, m2 = st.columns(2)
    m1.metric("Mes de mayor venta en el periodo", month_label(peak[0]), f"{peak[1]:,.0f} piezas", delta_color="off", delta_arrow="off")
    m2.metric("Mes de menor venta en el periodo", month_label(low[0]), f"{low[1]:,.0f} piezas", delta_color="off", delta_arrow="off")

    last_row = product_sales.iloc[-1]
    st.plotly_chart(build_chart(history, product_forecasts, peak, low, (last_row["fecha"], last_row["cantidad"])),
                    width="stretch")

    st.subheader("Resumen de los 10 productos")
    if table_all.empty:
        st.info("El resumen y la descarga se habilitan cuando se publiquen las proyecciones.")
        return
    st.dataframe(table_all, hide_index=True, width="stretch", column_config={
        "clave": "Clave", "descripcion": "Producto", "mes": "Mes proyectado",
        "piezas_proyectadas": st.column_config.NumberColumn("Piezas proyectadas", format="%d"),
        "ultimo_mes_cerrado": "Último mes cerrado",
        "piezas_ultimo_mes": st.column_config.NumberColumn("Piezas del último mes", format="%d"),
        "variacion_pct": st.column_config.NumberColumn("Variación esperada", format="%+.1f %%"),
    })
    d1, d2 = st.columns(2)
    d1.download_button("Descargar proyección de este producto (CSV)", export_csv(table),
                       file_name=f"proyeccion_{clave}.csv", mime="text/csv")
    d2.download_button("Descargar proyecciones de los 10 productos (CSV)", export_csv(table_all),
                       file_name="proyecciones_top10.csv", mime="text/csv")


main()

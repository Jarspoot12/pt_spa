"""Constantes globales del modelado (reglas comunes para comparar modelos del top 10) y del tablero.
Ubicación: src/config.py
"""
from datetime import date
from pathlib import Path

# --- Periodos (serie mensual, fecha = día 01) ---
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2024, 12, 1)
TEST_START = date(2025, 1, 1)
TEST_END = date(2025, 12, 1)
# Validación interna para elegir parámetros: meses objetivo de 2024, dentro de train
VALIDATION_START = date(2024, 1, 1)
VALIDATION_END = TRAIN_END

# --- Horizontes de pronóstico (meses) ---
HORIZONS = (1, 2, 3)

# --- Productos modelados: top 10 en piezas (notebook 02_stl_top10) ---
TOP10_CLAVES = ("1014", "11082", "731511", "731611", "11011", "8811", "8311", "919411", "919211", "919111")

# --- Atípicos de Tukey que se tratan (clave, mes) ---
OUTLIER_MONTHS = (
    ("919411", date(2023, 10, 1)),
    ("919211", date(2023, 10, 1)),
    ("919111", date(2023, 10, 1)),
    ("919411", date(2024, 3, 1)),
)
TUKEY_K = 3.0  # límite = Q3 + K × RIC sobre los meses con venta (5.3.4)

# --- Criterios de éxito ---
MAPE_TARGET = 20.0      # MAPE ≤ 20 % en test
MIN_REDUCTION = 0.15    # error ≥ 15 % menor que el modelo base

# --- Reproducibilidad ---
SEED = 42

# --- Resultados (CSV ignorados por git; son datos de la empresa) ---
RESULTS_DIR = Path(__file__).resolve().parents[1] / "data" / "resultados"

# --- Tablero (app/) ---
# Confiabilidad según la desviación promedio de la proyección en la prueba (%). Semáforo pendiente:
# se activa cuando `pronosticos` publique ese error. Hasta 20 % = alta (MAPE_TARGET); hasta 40 % = media.
RELIABILITY_HIGH_MAX = MAPE_TARGET
RELIABILITY_MEDIUM_MAX = 40.0
CACHE_MINUTES = 60  # minutos que el tablero guarda en memoria lo leído de Supabase

"""Todo lo que toca la base de datos: conexión y acceso a las tablas `productos` y `ventas`,
y lectura de `pronosticos` para el tablero. Ubicación: src/db/repository.py
Toda escritura ocurre dentro de `transaccion()`: si algo falla (o es simulación)
se deshace por completo. Las ventas se insertan con DO NOTHING: un mes ya
cargado nunca se modifica. Solo este archivo habla con la BD.
"""
import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

SCHEMA = Path(__file__).with_name("schema.sql")
COLUMNAS_PRONOSTICOS = ["clave", "fecha_corte", "fecha", "cantidad"]


def conectar():
    """Conexión a Supabase. La URL va en DATABASE_URL (archivo .env, que NO se versiona)."""
    import psycopg  # importación diferida: las pruebas no la necesitan
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Falta DATABASE_URL en el entorno o en el archivo .env")
    return psycopg.connect(url)


class Repositorio:
    def __init__(self, conn):
        self.conn = conn

    @contextmanager
    def transaccion(self, simular=False):
        try:
            yield
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.rollback() if simular else self.conn.commit()

    def crear_esquema(self):
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))

    def productos(self) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute("SELECT clave, descripcion, historial_completo, unidad FROM productos ORDER BY clave")
            filas = cur.fetchall()
        return pd.DataFrame(filas, columns=["clave", "descripcion", "historial_completo", "unidad"])

    def ultima_fecha(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT MAX(fecha) FROM ventas")
            return cur.fetchone()[0]

    def ventas(self, desde, hasta) -> pd.DataFrame:
        with self.conn.cursor() as cur:
            cur.execute("SELECT clave, fecha, cantidad FROM ventas WHERE fecha BETWEEN %s AND %s", (desde, hasta))
            filas = cur.fetchall()
        df = pd.DataFrame(filas, columns=["clave", "fecha", "cantidad"])
        df["cantidad"] = df["cantidad"].astype(float)
        return df

    def pronosticos(self) -> pd.DataFrame:
        """Pronósticos que publica el modelo: clave, fecha_corte (último mes cerrado usado),
        fecha (mes proyectado, día 01) y cantidad (piezas). Incluye todas las corridas."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT clave, fecha_corte, fecha, cantidad FROM pronosticos")
            filas = cur.fetchall()
        df = pd.DataFrame(filas, columns=COLUMNAS_PRONOSTICOS)
        df["cantidad"] = df["cantidad"].astype(float)
        return df

    def resumen_ventas(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(cantidad), 0) FROM ventas")
            n, s = cur.fetchone()
        return int(n), float(s)

    def insertar_productos(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO productos (clave, descripcion, historial_completo, unidad) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (clave) DO NOTHING",
                [(r.clave, r.descripcion, int(r.historial_completo), r.unidad) for r in df.itertuples()],
            )
        return len(df)

    def actualizar_descripciones(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany("UPDATE productos SET descripcion = %s WHERE clave = %s",
                            [(r.descripcion, r.clave) for r in df.itertuples()])
        return len(df)

    def insertar_ventas(self, df: pd.DataFrame) -> int:
        if df.empty:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ventas (clave, fecha, cantidad) VALUES (%s, %s, %s) "
                "ON CONFLICT (clave, fecha) DO NOTHING",
                [(r.clave, r.fecha, float(r.cantidad)) for r in df.itertuples()],
            )
        return len(df)
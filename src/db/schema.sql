-- Esquema de Supabase / PostgreSQL. Ubicación: src/db/schema.sql
-- Ejecutar una vez (el ETL también lo aplica con `crear_esquema`).

CREATE TABLE IF NOT EXISTS productos (
    clave               text PRIMARY KEY,
    descripcion         text NOT NULL,
    historial_completo  smallint NOT NULL CHECK (historial_completo IN (0, 1)),
    unidad              text NOT NULL CHECK (unidad IN ('PZA', 'KG'))
);

CREATE TABLE IF NOT EXISTS ventas (
    clave     text    NOT NULL REFERENCES productos (clave),
    fecha     date    NOT NULL CHECK (EXTRACT(DAY FROM fecha) = 1),
    cantidad  numeric(12, 2) NOT NULL CHECK (cantidad >= 0),
    PRIMARY KEY (clave, fecha)
);

-- Pronósticos que escribe el modelo (src/models) y lee el tablero (app/).
-- fecha_corte = último mes cerrado usado; fecha = mes proyectado. Se conservan las corridas anteriores.
CREATE TABLE IF NOT EXISTS pronosticos (
    clave        text    NOT NULL REFERENCES productos (clave),
    fecha_corte  date    NOT NULL CHECK (EXTRACT(DAY FROM fecha_corte) = 1),
    fecha        date    NOT NULL CHECK (EXTRACT(DAY FROM fecha) = 1),
    cantidad     numeric(12, 2) NOT NULL CHECK (cantidad >= 0),
    PRIMARY KEY (clave, fecha_corte, fecha),
    CHECK (fecha > fecha_corte)
);

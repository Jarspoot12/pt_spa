# AGENTS.md — pt_spa

Contexto persistente para agentes de IA. **Fuente de verdad:** informe técnico del proyecto terminal (local, no versionado). Lo marcado **[Informe]** es obligatorio y no se cambia sin aprobación del equipo; lo marcado **[Convención]** es una decisión del equipo, modificable. Reglas adicionales y decisiones vivas: ver `MEMORY.md`.

## 1. Proyecto

- **Título:** Modelado de demanda de productos para la planeación estratégica en una empresa distribuidora de productos para spa. Proyecto Terminal, Ing. en Datos e Inteligencia Organizacional (UNICARIBE).
- **Problema:** compras ajusta pedidos a mano en Excel promediando el mismo mes de años anteriores (~10 h/semana, sensible a atípicos, sin tendencia ni desplazamientos de calendario como Semana Santa). Hubo 2 quiebres de stock confirmados en temporada alta.
- **Solución:** sistema end-to-end: ETL → proyección de demanda **por producto** → tablero Streamlit para compras y finanzas.
- **Usuario final:** equipo de compras y finanzas, **no técnico**.
- **Principio:** la proyección es un **insumo** para la decisión de compra; no sustituye el criterio del equipo ni determina cantidades de pedido.
- **Metodología [Informe]:** CRISP-DM — Entendimiento del negocio → Requerimientos → Comprensión de datos → Preparación → Modelado → Evaluación → Despliegue.

## 2. Datos [Informe]

- Disponible: **solo `producto`, `cantidad`, `fecha` de venta**, 5 años de historial, en varios Excel de un sistema interno.
- **No hay:** compras, inventario, precios, canal de venta, listado de materiales. No inventar ni asumir estas variables.
- Sesgo conocido: en meses con quiebre de stock las ventas **subestiman** la demanda real.
- Calidad mínima del dataset de modelado: **≤5 % nulos** por variable relevante, **100 %** consistencia de formatos, **0 %** duplicados exactos en `producto`+`fecha`.
- Variables derivadas: mes, temporada alta/baja, día festivo. Temporada (preliminar, se valida en EDA): **alta = dic–abr y jul–ago**; baja = resto.

## 3. Stack tecnológico [Informe]

Un solo lenguaje: **Python**. Costo cero: solo herramientas gratuitas / free tier.

| Capa | Tecnología |
|---|---|
| Presentación | Streamlit (cliente web, enlace público, sin instalación) |
| Aplicación | Streamlit Community Cloud (redeploy automático desde GitHub) · ETL con pandas · modelos con statsmodels (SARIMA), Prophet, XGBoost · gráficas con Plotly |
| Datos | Supabase (PostgreSQL administrado, free tier) — repositorio analítico **único**; acceso por SQL |

- Dependencias en `requirements.txt`; instrucciones en `README.md`.
- No agregar herramientas de pago, otra plataforma de BI, ni otro lenguaje/framework de UI.

## 4. Arquitectura [Informe]

- **Tres capas** desacopladas (presentación / aplicación / datos). El pipeline y el modelo se ejecutan **de forma programada**; el tablero **solo lee resultados precalculados** de Supabase. Nunca entrenar ni recalcular el modelo dentro de una interacción del usuario.
- Los tres módulos (ETL, modelado, tablero) leen/escriben sobre la **misma** base Supabase; no depender de copias locales de archivos.
- Esquema de BD **como código versionado** en `src/db/`.

### Estructura del repositorio [Informe]

```
data/          # Copias procesadas de apoyo para pruebas locales (raw EXCLUIDO)
notebooks/     # EDA y comparación inicial de modelos (Objetivo 2)
src/
  etl/         # Extracción, limpieza y carga a Supabase (Obj. 3)
  features/    # Variables derivadas, reutilizables en entrenamiento y proyección (Obj. 3)
  models/      # Entrenamiento, comparación, selección y reporte vs. base (Obj. 4 y 5)
  db/          # Esquema y acceso a la BD analítica (Obj. 3)
app/           # Tablero Streamlit (Obj. 6)
tests/         # Pruebas unitarias de funciones de cálculo
requirements.txt
README.md
```

No mezclar responsabilidades: la lógica de cálculo vive en `src/`; `app/` solo orquesta visualización y llama a `src/`. Las features deben ser **las mismas funciones** en entrenamiento y en proyección.

## 5. Modelado y evaluación [Informe]

- **Modelo base (obligatorio):** pronóstico de un producto para un mes = promedio de ese mismo mes en los años anteriores disponibles (replica el método actual, calculado con ventas).
- Entrenar **≥2 modelos candidatos por producto** (series de tiempo y/o ML con variables de calendario) y **seleccionar el mejor por producto**.
- Validación: **holdout temporal** (división cronológica). Prohibido el split aleatorio y cualquier fuga de información futura.
- Métricas: **MAE, RMSE, MAPE** por producto y **WAPE** global.
- Criterios de éxito:
  - MAPE **≤ 20 %** en test, en productos con ventas suficientes.
  - Error **≥ 15 % menor (relativo)** que el modelo base.
  - Umbral de WAPE: se fija **después** de calcular el modelo base y **antes** de entrenar candidatos (no ajustarlo a posteriori).
- Horizonte de proyección: **1 y 3 meses**.

## 6. Tablero [Informe]

Funcionalidades requeridas:
- Histórico de ventas vs. demanda proyectada (1 y 3 meses), por producto.
- Filtros por producto y periodo.
- Top K productos con mayores y menores proyecciones.
- Variación esperada vs. periodo anterior.
- Mes histórico de mayor y menor venta por producto.
- Exportar proyecciones por producto.

Requisitos no funcionales (ISO/IEC 25010):
- Respuesta a un filtro **≤ 5 s**; **≥ 2 usuarios concurrentes**; enlace público.
- Usuario no técnico completa tareas clave **sin asistencia en ≤ 2 intentos** → lenguaje de negocio, sin jerga estadística en la UI.
- Sin autenticación multiusuario (no hay datos personales ni financieros).

## 7. Fuera de alcance [Informe] — no implementar

Segmentación por canal · actualización en tiempo real · conversión de unidades a insumos · cálculo de cantidades de compra · cobertura de inventario sugerida.

## 8. Prohibiciones

- **[Informe]** Nunca versionar datos crudos de la empresa (confidencialidad). Nunca pegarlos en issues, PRs, commits ni prompts compartidos.
- **[Informe]** Nunca introducir servicios o licencias de pago.
- **[Informe]** Nunca romper `main`: Streamlit Cloud redespliega automáticamente desde el repositorio.
- **[Convención]** Nunca versionar secretos (`.env`, `.streamlit/secrets.toml`); usar `st.secrets` / variables de entorno.
- **[Convención]** Nunca hacer commit de notebooks con salidas que muestren registros crudos; limpiar salidas antes del commit.
- **[Convención]** No ampliar el alcance ni cambiar el stack sin confirmación explícita del equipo.

## 9. Convenciones de código [Convención]

- Python 3.12. Formato y lint con **ruff**; pruebas con **pytest**.
- `snake_case` para funciones/variables/módulos, `PascalCase` para clases, `UPPER_SNAKE_CASE` para constantes.
- Identificadores en inglés; docstrings, comentarios, documentación y UI en **español**. Columnas de BD en español y sin acentos (`producto`, `cantidad`, `fecha`).
- Type hints en funciones públicas. Funciones puras y pequeñas para todo cálculo (métricas, features, top K, variación) → cada una con prueba en `tests/`.
- Configuración (umbrales, horizonte, K, temporadas) en un solo módulo de configuración, no hardcodeada en varios lugares.
- Semillas fijas para reproducibilidad.
- SQL parametrizado; nunca concatenar strings con entradas.

## 10. Flujo de Git [Convención]

- `main` siempre desplegable; nunca commit directo. Todo cambio entra por **Pull Request** con revisión de al menos otro integrante.
- Ramas: `feat/…`, `fix/…`, `docs/…`, `refactor/…`, `test/…`, `chore/…`, en kebab-case (ej. `feat/etl-limpieza-fechas`).
- Commits: **Conventional Commits**, descripción en español e imperativo (ej. `feat(etl): normaliza formatos de fecha`).
- PRs pequeños, una responsabilidad; pruebas en verde antes de fusionar.

## 11. Informe técnico (si se pide ayuda redactándolo) [Informe]

- Resultados: **6** (uno por objetivo específico); se muestran resultados, no opiniones.
- Referencias en **APA 7**, orden alfabético.
- Anexos: Anexo A, B, C…, cada uno con título y breve explicación, y **referenciado explícitamente** en el cuerpo. Conclusiones no repiten resultados.

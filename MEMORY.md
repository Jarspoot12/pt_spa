# MEMORY.md — reglas extra y decisiones vivas

Complemento de `AGENTS.md`. Aquí van reglas que surgen **durante** el desarrollo: decisiones tomadas, correcciones al agente, lecciones aprendidas y preferencias del equipo. `AGENTS.md` describe el proyecto (estable); este archivo registra lo que vamos aprendiendo (cambia seguido).

**Formato de cada regla:** una línea con la regla en imperativo, fecha, y el *porqué* (sin porqué, la regla no se puede aplicar bien en casos límite). Si una regla deja de ser válida, bórrala; si contradice `AGENTS.md`, actualiza `AGENTS.md` primero.

---

## Decisiones técnicas

<!-- EJEMPLOS — reemplazar por decisiones reales
- [2026-10-20] Agregar las ventas a granularidad mensual (`date_trunc('month')`) antes de modelar. Porqué: el horizonte es 1–3 meses y la serie diaria es muy ruidosa.
- [2026-10-22] "Ventas suficientes" = ≥ 24 meses con ventas > 0. Porqué: SARIMA estacional necesita al menos 2 ciclos completos.
- [2026-10-25] Usar `holidays` (paquete, país MX) para festivos; Semana Santa se calcula aparte. Porqué: no viene en el calendario oficial de festivos.
-->

- [2026-10-22] `ventas` guarda solo los 363 con historial completo; `productos` conserva los 691. Porqué: solo esos se conservan para análisis, solo el top 10 se proyecta, y con `productos` completo un producto conocido no se confunde con uno nuevo.
- [2026-10-22] Atípicos y variables de calendario se calculan al modelar, no se guardan. Porqué: mantener los datos originales y evitar que meses de evaluación influyan en el umbral.
- [2026-10-22] Cargas mensuales: solo meses posteriores al último cargado, nunca se reescriben los anteriores. Porqué: decisión del equipo para no alterar datos ya validados.
- [2026-10-22] Cada control de calidad que falla detiene la carga entera. Porqué: no dejar datos parciales en Supabase.
- [2026-10-22] Constantes del ETL viven en su módulo; cuando haya umbrales globales (horizonte, K) se crea `src/config.py` y se migran. Porqué: no crear archivos sin uso.

## Correcciones al agente

<!-- EJEMPLOS
- [2026-10-21] No uses `inplace=True` en pandas; reasigna. Porqué: dificulta depurar y está desaconsejado.
- [2026-10-23] No generes notebooks nuevos sin pedirlo; extiende los existentes. Porqué: evitamos duplicar EDA.
- [2026-10-24] Antes de proponer una nueva dependencia, verifica que funcione en Streamlit Community Cloud. Porqué: Prophet falló al compilar con una versión de Python.
-->

- [2026-10-22] No agregues variables, columnas ni archivos que no sean necesarios. Porqué: el equipo prefiere pocos archivos y una base sin ruido.
- [2026-10-22] En el informe no cambies el conjunto de productos sin justificarlo (363 vs 352): rompe el hilo del lector. Porqué: pasó con la sección de tendencia.

## Lecciones aprendidas / trampas conocidas

<!-- EJEMPLOS
- [2026-10-28] El archivo de 2022 trae fechas en formato dd/mm/aaaa y el resto en aaaa-mm-dd. Porqué: cambió el sistema interno ese año.
- [2026-11-02] Supabase free tier pausa el proyecto tras 7 días sin actividad; reactivarlo antes de la demo. Porqué: el tablero falla sin mensaje claro.
-->

- [2026-10-22] El Excel trae en cada hoja: fila 1 "AÑO: 20XX", fila 2 encabezado, filas de producto y fila final "TOTAL: N". La clave mezcla números y texto: leerla siempre como texto. Porqué: evita cruces fallidos entre hojas.
- [2026-10-22] Ejecuta las pruebas con `python -m pytest tests`, no con `pytest`. Porqué: así Python encuentra la carpeta `src`.
- [2026-10-22] `cantidad` mezcla piezas y kg (11 productos a granel). Porqué: sumarlas distorsiona los totales.

## Preferencias del equipo

<!-- EJEMPLOS
- [2026-10-20] Paleta de colores del tablero: azul para histórico, naranja para proyección. Porqué: consistencia en todas las gráficas.
- [2026-10-20] Responsables por módulo: ETL → Armando, Modelado → Kevin, Tablero → Jared. Porqué: el agente debe pedir revisión al responsable del módulo tocado.
-->

## Pendientes por confirmar con la empresa

<!-- EJEMPLOS
- Validar definición de temporada alta/baja con el encargado de compras (preliminar: dic–abr, jul–ago).
- Confirmar aceptación de los umbrales de éxito (MAPE ≤ 20 %, −15 % vs. base).
-->

- Aceptación de los umbrales de éxito (MAPE ≤ 20 %, −15 % vs. base): propuestos por el equipo.

## Cómo trabajar el uso de branches en la creación de features para el repositorio del proyecto
El ciclo completo, para cada cosa nueva

1. parte siempre del main actualizado
git switch main && git pull   
2. rama nueva
git switch -c feat/etl-limpieza-fechas  
3. commits
...trabajas, git add, git commit...       
4. subes la rama
git push -u origin feat/etl-limpieza-fechas
5. abres el PR → revisión → merge en GitHub
6. borras la rama (remota y local) y vuelves al paso 1
    0. borrar en remoto (github) después de aprobar el PR
    1. git switch main
    2. git pull
    3. git branch -d chore/contexto-ia ------- borra la rama local
    4. git fetch --prune ----- limpia referencias a ramas remotas borradas 
Las ramas deben vivir poco: días, no semanas. Mientras más tiempo dure una rama, más se aleja de main y más conflictos tendrás al fusionarla.
- [2026-10-22] El modelado y el tablero cubren solo el top 10 de piezas (sin KG); se quitó el top K del tablero. Porqué: decisión del equipo con el asesor; la base conserva el ETL completo.
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

## Correcciones al agente

<!-- EJEMPLOS
- [2026-10-21] No uses `inplace=True` en pandas; reasigna. Porqué: dificulta depurar y está desaconsejado.
- [2026-10-23] No generes notebooks nuevos sin pedirlo; extiende los existentes. Porqué: evitamos duplicar EDA.
- [2026-10-24] Antes de proponer una nueva dependencia, verifica que funcione en Streamlit Community Cloud. Porqué: Prophet falló al compilar con una versión de Python.
-->

## Lecciones aprendidas / trampas conocidas

<!-- EJEMPLOS
- [2026-10-28] El archivo de 2022 trae fechas en formato dd/mm/aaaa y el resto en aaaa-mm-dd. Porqué: cambió el sistema interno ese año.
- [2026-11-02] Supabase free tier pausa el proyecto tras 7 días sin actividad; reactivarlo antes de la demo. Porqué: el tablero falla sin mensaje claro.
-->

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

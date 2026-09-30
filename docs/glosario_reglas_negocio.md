# Glosario de reglas de negocio aplicadas — Moneta

> Consolida en un solo documento las reglas de negocio y transformaciones ya implementadas y validadas en Bronze/Silver/Gold, hasta la Sesión 28. Pensado para insertarse en el Documento de Arquitectura (entregable 1, sección de calidad/gobierno) y como referencia de gobierno funcional (ver Contexto Maestro §12).

---

## 1. Variable `age` sintética (Personal Finance Tracker)

Personal Finance Tracker no trae edad nativa. Se deriva a partir de un **score de madurez financiera** (`maturity_score`, 0–1), calculado con 5 variables ponderadas:

```
maturity_score = 0.30·norm(credit_score) + 0.25·norm(investment_amount)
               + 0.20·norm(rent_or_mortgage) + 0.15·norm(emergency_fund)
               + 0.10·norm(debt_to_income_ratio)
```

- `rent_or_mortgage` se trata como **monto continuo normalizado**, no categórico: no existe columna que distinga renta de hipoteca en el dataset real.
- A partir del score se deriva `age` dentro de un rango plausible según el segmento (`early_career` 20–29, `established` 30–60), con ruido determinístico sembrado por **índice de fila** (no `user_id`, ver regla 4).
- Cada fila derivada así queda marcada con `age_synthetic_flag = True`.
- **Limitación conocida, no bloqueante:** el `maturity_score` real no llega a 1.0 (máximo observado ~0.73), por lo que la edad `established` generada topa en ~46 años. No se reescala porque el propósito es distinguir segmento, no reproducir la pirámide etaria completa.
- Validada con el mentor BBVA el 2026-08-11.

## 2. Segmentación `<30 años`

- `p = 0.7216`: proporción real de usuarios `<30` en Credit Risk (única fuente con edad exacta y limpia de outliers).
- `threshold = quantile(maturity_score, p)`: umbral calibrado con datos reales (no un corte fijo 50/50), recalculado dinámicamente por corrida con `approxQuantile`.
- Regla de exclusión: Loan Default no participa en el cálculo del umbral por venir en bins de 10 años, no edad exacta.

## 3. Corte transversal vs. panel

Personal Finance Tracker es un **corte transversal**, no una serie longitudinal: `user_id` se repite pero por colisión estadística (pool de 1,000 IDs sobre 3,000 filas), no porque identifique a la misma persona en el tiempo. Regla derivada: **ninguna métrica de PFT se calcula como serie por persona**; toda métrica "temporal" (ej. gasto promedio 3 meses) se reinterpreta como proxy transversal o varianza inter-segmento (ver regla 7). Por esto mismo, `FACT_KPI_PERFIL` (Gold) se escribe en modo `overwrite`, no histórico.

## 4. `record_id` sintético

Prefijado por fuente (`LD_0000001`, `CR_0000001`, `PFT_0000001`, 7 dígitos). No existe llave real entre las 3 fuentes: la unión es por segmento (`UNION`), no por identidad (`JOIN`). Generado una sola vez por fuente con `RDD.zipWithIndex()` (nunca `monotonically_increasing_id()` como llave de orden — ver nota técnica abajo).

## 5. Deduplicación

Duplicado = fila idéntica en **todas** las columnas de negocio, excluyendo las 4 columnas de trazabilidad de ingesta (`ingestion_date`, `ingestion_timestamp`, `source_file`, `dag_run_id`). Necesario porque el DAG reingesta el mismo CSV fuente cada día.

## 6. Resolución de nulos y outliers

- **Nulos:** imputación por mediana de grupo (ej. `dtir1` por `loan_type`), con fallback a mediana global si el grupo queda vacío. Cada fila tocada se marca con `{columna}_imputed_flag = True`. Regla de negocio: **nunca se eliminan filas** por nulos — el volumen (hasta 24% en algunos casos) sesgaría el dataset, y Credit Risk (fuente ponderada para el segmento `<30`) es especialmente sensible a perder filas.
- **Hallazgo — `income` (Loan Default) nunca se había imputado (Sesión 29):** detectado por la cuarentena de calidad, no por `verify_silver.py` (que no chequeaba esta columna). 9,150 filas (6.16%) tenían `income` nulo — ni (solo cubrió `dtir1`) ni (`rate_of_interest`/`loan_int_rate`/`person_emp_length`) la habían tocado; `cap_income_outliers()` solo winsoriza el tope, nunca trató nulos. Se imputó con `impute_numeric_by_group()` agrupando por `loan_type` (mismo criterio ya validado para `dtir1`), **antes** de winsorizar y antes de la cuarentena — consistente con la regla de "nunca eliminar filas por nulos" de arriba: dejarlo en cuarentena habría sido, en la práctica, borrar esas 9,150 filas por la puerta de atrás. Verificado: tras imputar, 0 filas en cuarentena por esta causa.
- **Outliers:** winsorización a percentil 99 (recorte, no eliminación de fila) + flag `{columna}_outlier_flag`, aplicado a columnas de ingreso con outliers extremos (`person_income`, `income`).

## 7. Métricas derivadas de comportamiento (`FACT_COMPORTAMIENTO`)

- **Gasto promedio / varianza de ingreso:** por ser corte transversal (regla 3), "3 meses" y "varianza en el tiempo" se reinterpretan sin fabricar series sintéticas: `gasto_promedio_3m` es el snapshot de `monthly_expense_total` (documentado como aproximación); `varianza_ingreso_segmento` es la varianza poblacional de `monthly_income` **dentro** de cada `income_type`, es decir volatilidad entre personas similares, no en el tiempo.
- **Intensidad de suscripciones:** `subscription_services` es un **conteo** (1–9 suscripciones activas), no un monto en USD — confirmado con los datos reales antes de calcular nada. Se define `suscripciones_por_1000_ingreso = subscription_services / (monthly_income / 1000)` en vez de inventar un costo promedio sin respaldo.
- **Fondo de emergencia:** `fondo_emergencia_meses = emergency_fund / monthly_expense_total`, contra benchmark estándar de industria (3–6 meses).

## 8. Fórmulas de KPI y su extensión a las 3 fuentes

```
IRFI = 0.25·loan_percent_income + 0.15·(1−emp_stability) + 0.20·loan_int_rate_norm
     + 0.15·neg_amortization_flag + 0.10·(1−grade_score) + 0.15·(1−credit_hist_norm)

ICA = 1 − [0.5·loan_percent_income + 0.3·(1−emp_stability) + 0.2·housing_penalty]
```

- **Exclusión deliberada:** IRFI nunca usa `Credit_Score` directamente — es una regla de diseño, no un descuido (evita apoyarse en un score externo ya calculado).
- **`housing_penalty`** va directo, no invertido (ya es una penalización: RENT=1.0/MORTGAGE=0.5/OWN=0.0).
- **Extensión vía proxies (Loan Default, PFT):** las fórmulas se diseñaron sobre columnas nativas de Credit Risk. Al extenderlas, `grade_score` va **neutro (0.5)** en las otras 2 fuentes — usar `credit_score_norm` como proxy ahí reintroduciría `Credit_Score` por la puerta de atrás, violando la exclusión anterior. `housing_penalty` en PFT usa `1 − norm(rent_or_mortgage)` (invertido respecto al monto crudo, porque pago alto = más madurez = menos riesgo, coherente con la regla 1).
- Aprobadas por el mentor BBVA el 2026-08-11.

## 9. Nota técnica — antipatrón evitado en `record_id`

`Window.orderBy(monotonically_increasing_id())` **no** es determinista como llave de orden en Spark/Catalyst y puede evaluarse más de una vez para la misma fila dentro de un mismo plan (causó colisiones reproducibles: 48,671 de 184,086 filas, idénticas en 3 corridas). Regla de negocio operativa: `record_id` siempre se genera con `RDD.zipWithIndex()`, una sola vez por fuente, y ambas salidas (dataset maestro y sub-dimensiones) se derivan del mismo DataFrame ya indexado para evitar desincronización.

---
*Fuente: Bitácora de progreso (sección "Decisiones técnicas de referencia rápida") y Contexto Maestro §5, §6.2, §6.2.1. Última actualización: Sesión 29 (2026-09-18).*
# Diccionario de features — Moneta (`t058`)

> Documenta columna por columna las 2 tablas de Gold que alimentan el feature store del proyecto: `gold.fact_kpi_perfil` (`t050`-`t053`) y `gold.fact_comportamiento` (`t054`-`t057`). Complementa el glosario de reglas de negocio (`t044`), que documenta el *porqué* de las decisiones; este documento documenta el *qué* de cada columna, lista para consumo del dashboard (`t059`/`t060`) y del futuro Text-to-SQL (Fase 5).

---

## `gold.fact_kpi_perfil`

Grano: 1 fila por `record_id` (las 3 fuentes unidas por `UNION`, no `JOIN` — ver glosario `t044`, regla 3). 184,086 filas.

| Columna | Tipo | Descripción | Notas |
|---|---|---|---|
| `record_id` | `string` | Llave sintética, prefijada por fuente (`LD_`/`CR_`/`PFT_` + 7 dígitos). | No es llave real entre fuentes — glosario, regla 4. |
| `fuente` | `string` | `loan_default` / `credit_risk` / `personal_finance_tracker`. | |
| `segmento` | `string`, nullable | `early_career` (<30 años) / `established` (≥30). | **`NULL` en `loan_default`** — esa fuente solo trae bins de edad de 10 años, no edad exacta; no se rellena con un supuesto de distribución (hallazgo Sesión 30, mismo criterio que `t056`). `credit_risk`: 23,364 `early_career` / 9,052 `established`. `personal_finance_tracker`: 2,161 / 839. |
| `irfi` | `double` | Índice de Riesgo Financiero Individual. Fórmula completa en glosario `t044`, regla 8. | Más alto = más riesgo. |
| `ica` | `double` | Índice de Capacidad de Ahorro. Fórmula en glosario `t044`, regla 8. | Más alto = más capacidad. |
| `default_flag_unificada` | `double`, nullable | 1.0 = incumplió, 0.0 = al corriente. | `NULL` únicamente en `personal_finance_tracker` (no tiene equivalente real de default — §5.2). |
| `irfi_proxy_flag` | `boolean` | `True` si al menos un componente de IRFI usó un proxy o valor neutro en vez del dato nativo de Credit Risk. | `False` solo en `credit_risk` (única fuente sin proxies). 151,670 filas (82.4%) en `True`. |
| `ica_proxy_flag` | `boolean` | Igual que `irfi_proxy_flag`, para ICA. | Mismos componentes base que IRFI — siempre coincide con `irfi_proxy_flag`. |

---

## `gold.fact_comportamiento`

Grano: 1 fila por `record_id` de `personal_finance_tracker` **únicamente** — las otras 2 fuentes no tienen los datos de gasto/ahorro/suscripciones que esta tabla necesita. 3,000 filas.

| Columna | Tipo | Descripción | Notas |
|---|---|---|---|
| `record_id` | `string` | Mismo `record_id` que en `fact_kpi_perfil` — join válido entre ambas tablas para esta fuente. | |
| `fuente` | `string` | Siempre `personal_finance_tracker` (constante, por diseño de esta tabla). | |
| `segmento` | `string`, nullable | Igual definición que en `fact_kpi_perfil`. | 2,161 `early_career` / 839 `established`. En la práctica nunca `NULL` aquí (PFT siempre tiene edad exacta), pero la columna queda nullable por consistencia de esquema con `fact_kpi_perfil`. |
| `income_type` | `string` | `Salary` / `Mixed` / `Freelance` — tipo de ingreso nativo de PFT. | 2,154 / 317 / 529 filas respectivamente. Es el segmento usado para `varianza_ingreso_segmento` (no confundir con `segmento`, que es por edad). |
| `ingreso_mensual` | `decimal(18,2)` | `monthly_income` nativo de PFT, en USD. | Agregado en Sesión 30 (`t059`) — se usaba internamente para otras columnas pero nunca se había guardado como feature propia. |
| `gasto_promedio_3m` | `decimal(18,2)` | Snapshot de `monthly_expense_total`. | **Aproximación documentada, no un promedio real de 3 meses** — PFT es corte transversal (`t107`), no hay serie temporal real. Ver glosario `t044`, regla 7. |
| `varianza_ingreso_segmento` | `double` | Varianza poblacional de `monthly_income` dentro del mismo `income_type` (no es varianza temporal por persona). | `Freelance`: 1,144,058 · `Salary`: 973,513 · `Mixed`: 932,722 — nota real de los datos: `Mixed` queda por debajo de `Salary`, no en punto medio entre `Salary` y `Freelance` como sugeriría la intuición (muestra de 317 filas, no es un bug). |
| `ratio_endeudamiento` | `decimal(10,4)` | `debt_to_income_ratio` nativo de PFT, sin proxy. | |
| `alerta_fraude` | `boolean` | `fraud_flag` nativo de PFT, casteado explícito a boolean. | 71 `True` / 2,929 `False`. |
| `suscripciones_por_1000_ingreso` | `decimal(38,21)` | `subscription_services / (monthly_income / 1000)` — cuántas suscripciones activas por cada $1,000 USD de ingreso mensual. | **No es un "%" de gasto** — `subscription_services` es un CONTEO (1-9), no un monto; no existe en el dataset un monto real de gasto en suscripciones. Ver glosario `t044`, regla 7. Media: 1.34, stddev: 0.87. |
| `fondo_emergencia_meses` | `decimal(38,20)` | `emergency_fund / monthly_expense_total` — meses de gasto que cubre el fondo actual (benchmark industria: 3-6 meses). | Media observada: 0.37 meses — muy por debajo del benchmark, dato real, no error. Puede dar `infinito` si `monthly_expense_total = 0` (chequeado explícitamente en `build_fact_comportamiento.py`, sin ocurrencias en la corrida de Sesión 30). |

---

## Relación entre ambas tablas

`fact_kpi_perfil.record_id` para `fuente = 'personal_finance_tracker'` es exactamente el mismo `record_id` de `fact_comportamiento` — join directo, sin necesidad de mapeo. Para `loan_default`/`credit_risk`, `fact_comportamiento` no tiene fila correspondiente (esas 2 fuentes no tienen datos de gasto/ahorro).

## Cargas a Postgres

Ambas tablas viven en `postgres-dw`, esquema `gold`:
- `gold.fact_kpi_perfil` — cargada por `src/spark/loaders/load_gold_postgres.py` (modo `truncate`, requiere que la tabla ya exista con la estructura correcta).
- `gold.fact_comportamiento` — cargada por `src/spark/loaders/load_fact_comportamiento_postgres.py` (modo `overwrite` sin `truncate` — tabla se recrea cada corrida, agregado en Sesión 30, nunca existió antes).

---
*Fuente: `calculate_kpis.py`, `build_fact_comportamiento.py`, logs de ejecución de Sesión 30 (2026-09-20). Última actualización: Sesión 30.*
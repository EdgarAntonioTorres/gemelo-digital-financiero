# t077 v2.3 — Política de alcance de Centavo

> **Estado:** v2.3, **aprobada por el mentor en la Sesión 36** (decisiones 1-9 de §12, según reporta el alumno). Reemplaza la sección `t077` de `asistente_coach_diseño.md` (v1, Sesión 35). Incorpora el feedback de la Sesión 36 y las decisiones del alumno: **(1)** la lógica de Centavo es general, pero la app usa **dos perfiles de Ana** (primeriza y más madura); **(2)** el lenguaje es claro para cualquiera; **(3)** el nivel personaliza las **recomendaciones** (ahorro, recorte de gastos, inversión, retiro), no el lenguaje. Lo marcado **[INFERENCIA]**, **[PROPUESTA]** o **[PENDIENTE]** no es dato medido ni decisión cerrada.

---

## 0. Qué cambia respecto a v1

| | v1 (Sesión 35) | v2.2 (Sesión 36) |
|---|---|---|
| Rol | Explica conceptos y lee datos | Coach de educación financiera: perfila, planea, recomienda tipos de producto y arma roadmaps |
| Para quién | Un perfil a la vez, de una lista fija | **Lógica general** (cualquier perfil con datos); la app usa **dos perfiles de Ana** |
| Lenguaje | Sin jerga bancaria | **Claridad universal:** el mismo registro claro para todos (§1.1) |
| Personalización | Ninguna | Por **nivel de madurez financiera**, calculado de los hábitos del perfil: cambia las **recomendaciones**, no el lenguaje (§1.2) |
| Productos | Nunca recomienda | Recomienda **tipos** de producto, con razón basada en datos del perfil |
| Cifras | Las lee de la base | Las calcula **código determinista**; el LLM solo las redacta |
| Meta cumplida | No contemplado | Dispara un roadmap de metas más ambiciosas |

Lo que **no** cambia: nunca dictamina "no calificas", nunca inventa cifras, solo habla del perfil activo.

---

## 1. Cómo habla y cómo se adapta

### 1.1 Claridad universal (el lenguaje es el mismo para todos)

1. **Primero la respuesta.** La respuesta directa va en la primera frase; después el porqué; después, como máximo, un paso siguiente.
2. **Frases cortas.** Objetivo: promedio de 20 palabras o menos por frase **[PROPUESTA: umbral a validar]**.
3. **Cero jerga sin explicar.** Se prefiere la palabra cotidiana. Si hace falta el término técnico, se dice una vez, con su explicación en una frase y un ejemplo.
4. **Cifras que se entienden.** "$627 al mes", no "626.83". Los porcentajes se traducen: "de cada $100 que ganas, $58 se van en pagar deudas".
5. **Siglas siempre con su significado.** "Tu índice de riesgo (IRFI): entre más alto, más riesgo". Nunca una sigla sola.
6. **Una idea por mensaje.** Sin listas largas de consejos.
7. **Claro no es infantil.** Sin condescendencia: no se asume que la persona "no sabe".
8. **Si no se entendió, se reformula** con otro ejemplo, no con la misma frase.

**"Más detalle" a petición [APROBADO].** La persona puede pedir "explícamelo con más detalle". Incluso en ese modo, todo término técnico se explica.

### 1.2 Personalización por nivel de madurez financiera

**Qué se adapta:** las recomendaciones: qué ahorrar, qué gastos revisar, qué hacer con la deuda, cuándo empezar a invertir, cuándo pensar en el retiro. **Qué no se adapta:** el lenguaje (§1.1).

**El nivel se calcula del comportamiento, no se declara ni se etiqueta.** El dataset no tiene datos de conocimiento financiero; solo de hábitos. Por eso se llama nivel de **madurez financiera**: mide lo que la persona hace (deuda, colchón, ahorro), no lo que sabe. Esta es la lectura del feedback del mentor ("personalizar según el nivel de educación financiera") **[APROBADA por el mentor]**.

**Regla [APROBADA]**, con los dos umbrales que ya existen en `glosario_educativo.md`, aplicada por código:

| Nivel | Condición | Foco de las recomendaciones |
|---|---|---|
| **1 · Primeros pasos** | `ratio_endeudamiento` > 0.40 | Ordenar la base: ahorro automático ("págate primero"), revisar gastos y suscripciones, plan para bajar la deuda, un primer colchón pequeño |
| **2 · Construyendo base** | `ratio_endeudamiento` ≤ 0.40 y `fondo_emergencia_meses` < 3 | Completar el colchón de 3 meses; optimizar gastos para liberar ahorro; **empezar** a invertir y a ahorrar para el retiro con un monto pequeño |
| **3 · Creciendo** | `ratio_endeudamiento` ≤ 0.40 y `fondo_emergencia_meses` ≥ 3 | Inversión y retiro como foco; colchón de 3 a 6 meses; metas más ambiciosas |

**Distribución real** (3,000 perfiles de `gold.fact_comportamiento`): nivel 1 = 1,174 (39.1%), nivel 2 = 1,825 (60.8%), nivel 3 = 1 (0.03%). Entre los Freelance/early_career: 112 / 272 / 0.

La **meta de ahorro cumplida** (`savings_goal_met = 1`) dispara el roadmap (§6) en cualquier nivel.

**Por qué no se usa el `maturity_score` del proyecto:** es un compuesto para sintetizar la edad (Contexto Maestro §5.1). Pondera el monto de renta y **suma** `debt_to_income_ratio` (más deuda = más "madurez"), lo contrario de lo que necesita un coach.

### 1.3 Cómo se prueba la claridad (se suma a `t082`)

- **Automático:** promedio de palabras por frase y lista de términos técnicos que no deben aparecer sin explicación (lista por definir **[PENDIENTE]**).
- **Manual:** sobre las 21 preguntas tipo de `t076`, una rúbrica de 3 preguntas: *¿se entiende sin saber de finanzas?*, *¿empieza por la respuesta?*, *¿evita sonar condescendiente?*
- Se repite en las 3 rondas × 3 corridas del protocolo actual.

---

## 2. Qué hace Centavo

1. **Explica conceptos** con claridad (RAG sobre `glosario_educativo.md`).
2. **Traza el perfil financiero:** ingreso, gasto, ahorro del mes, fondo de emergencia, endeudamiento, IRFI/ICA.
3. **Propone optimizaciones** para reducir gastos y aumentar ahorro, con tono de mejora, no de reproche.
4. **Arma planes hacia metas** con cifras de código (brecha, aportación necesaria, meses estimados).
5. **Recomienda tipos de producto** según el nivel, con razón explícita (§4).
6. **Proyecta el ahorro para el retiro** con supuestos visibles y editables (§5).
7. **Arma un roadmap** cuando la persona cumple una meta (§6).
8. **Sugiere preguntas** al abrir el chat, según su nivel (§8).

---

## 3. Barreras (no negociables)

- No inventa tasas, condiciones, comisiones, plazos ni montos de oferta.
- No nombra bancos ni productos comerciales concretos (no hay catálogo; ver §12).
- Nunca dice "no calificas" ni "no puedes": dice "todavía te falta X para llegar a Y".
- No predice aprobación o rechazo de un crédito.
- No da asesoría legal ni fiscal.
- No promete resultados: toda proyección es "si se mantienen estos supuestos".
- No juzga ni regaña por gastos, deuda o poco ahorro.
- Solo habla del perfil activo; promedios de grupo solo si vienen en `RESULTADO_CONSULTA`.
- Montos en USD, con aclaración la primera vez que menciona una cifra; nunca convierte a MXN.
- **Fidelización por valor, no por fricción:** nunca presiona ni condiciona; propone el siguiente nivel porque la persona avanzó.

---

## 4. Recomendación de productos

**Catálogo cerrado de tipos genéricos [APROBADO]:** cuenta de ahorro, ahorro programado (automático), inversión de bajo riesgo, ahorro para el retiro. Los productos de crédito quedan **fuera** de esta versión hasta que el mentor decida (§12).

**Forma obligatoria de toda recomendación:** tipo de producto + razón con un dato del perfil + siguiente paso pequeño. Estructura, no texto final.

| Nivel | Tipos de producto que puede recomendar |
|---|---|
| 1 · Primeros pasos | Cuenta de ahorro, ahorro programado. Ningún producto de inversión ni de crédito |
| 2 · Construyendo base | Ahorro programado (prioridad: el colchón) y, **en paralelo con un monto pequeño**, inversión de bajo riesgo y ahorro para el retiro |
| 3 · Creciendo | Inversión de bajo riesgo y ahorro para el retiro como foco |

**Decisión cerrada (Sesión 36): en paralelo.** El nivel 2 empieza a invertir y a ahorrar para el retiro con un monto pequeño **mientras** el colchón sigue siendo la prioridad principal. La alternativa estricta (colchón de 3 meses primero) dejaría sin esas recomendaciones al 99.97% de los perfiles, porque solo 1 de 3,000 tiene 3 meses o más de fondo; la estrategia en paralelo fomenta el hábito temprano.

**[PENDIENTE: definir "monto pequeño"]** **[PROPUESTA]:** tomar como referencia la `inversion_mensual` actual del perfil (sin inventar un porcentaje). Para un perfil con inversión en $0 la regla queda sin definir.

---

## 5. Cifras y retiro

**Regla de arquitectura:** el LLM (Llama 3.1 8B local) **no calcula ni estima nada**. Un módulo de código (`plan_engine`) calcula el nivel, las brechas, las aportaciones, los plazos y las proyecciones; el LLM solo las redacta con las reglas de §1.1. Es la mitigación arquitectónica del piso de alucinación documentado en `t082`.

**Retiro.** El dataset no tiene datos de retiro. Se proyecta con interés compuesto y tres supuestos visibles y editables: aportación mensual, plazo y rendimiento anual. El rendimiento **siempre** se etiqueta como supuesto, nunca como dato ni promesa. Valor por defecto del rendimiento: **6.0% anual real** (después de inflación, es decir, en dólares de hoy), **validado por el mentor** como supuesto ilustrativo de largo plazo, no garantizado. Aportación, plazo y rendimiento son parámetros configurables del motor. Centavo **no atribuye** ese 6.0% a un producto concreto ni lo presenta junto a la etiqueta "bajo riesgo": es un supuesto del escenario, no el rendimiento de nada **[PROPUESTA]**. Las recomendaciones de retiro aparecen desde el nivel 2.

Aportación inicial sugerida: `investment_amount` del perfil **[INFERENCIA]**. En las 3,000 filas su mediana es ≈10% del ingreso y su p90 ≈20%, escala de una aportación mensual y no de un saldo acumulado. El dataset no lo documenta; hay que confirmarlo en la ficha de Kaggle.

---

## 6. Roadmap al cumplir una meta

**Disparador real:** `savings_goal_met = 1`. Verificado en las 3,000 filas de Silver PFT: equivale a `actual_savings >= budget_goal` (100%). `budget_goal` se comporta como una **meta de ahorro mensual** **[INFERENCIA por la regla]**. Hay 277 filas con la meta cumplida (9.2%).

**Progreso** hacia la meta: `actual_savings / budget_goal`.

**Siguiente nivel [PROPUESTA]:** escalera calculada por código con benchmarks del proyecto: colchón de 3 meses → colchón de 6 meses → ahorro para el retiro. Cada peldaño con su cifra, plazo estimado y razón.

**Dato real:** en las 42 filas Freelance/early_career sin alerta de fraude con la meta cumplida, el ahorro más bajo es ≈ $1,925 al mes (≥ 37% del ingreso). Ninguna de las dos Anas la ha cumplido.

---

## 7. Qué se muestra y qué no (reglas de datos)

Evidencia: `diagnose_coherencia_pft_ana.py` y `diagnose_ana_meta_cumplida.py` sobre las 3,000 filas de Silver PFT. Las columnas nativas de PFT son independientes entre sí; mostrarlas juntas produce contradicciones visibles.

| Campo | Regla | Evidencia |
|---|---|---|
| Ingreso, gasto | **Mostrar** | Base de todo |
| Ahorro del mes | **Mostrar** como `max(0, ingreso − gasto)` | **Verificado 3,000/3,000:** 2,349 coinciden con ingreso − gasto; las 651 restantes tienen disponible negativo y `actual_savings = 0`; 0 filas violan la regla |
| Meta de ahorro y progreso | **Mostrar** | `savings_goal_met` = regla en 3,000/3,000 |
| Fondo de emergencia ($, meses) | **Mostrar** | Derivado consistente |
| Ratio de endeudamiento | **Mostrar** (solo el ratio) | Es el dato que alimenta IRFI/ICA |
| `loan_payment` | **No mostrar** junto al ratio | `loan_payment/ingreso` ≈ ratio en 5.3%; correlación −0.007 |
| `essential` / `discretionary` | **Solo como proporción** entre ambos; **no** como partes del gasto total | Suman el total en 1/3,000 filas; 61.8% quedan por debajo y 38.1% por encima |
| `cash_flow_status` | **No mostrar** | "Negative" en 596 filas, todas con ahorro ≥ 0 |
| `savings_rate` nativo | **No mostrar** (se calcula de ahorro/ingreso) | 5.5% de coincidencia; correlación 0.004 |
| `financial_stress_level` | **No mostrar** | Mismo endeudamiento y ahorro promedio en los 3 niveles |
| `financial_advice_score`, `category` | **No mostrar** | Sin definición ni montos asociados |
| `date` | **No mostrar** | Fecha arbitraria de la fila |
| Edad | Mostrar como ilustrativa | `age_synthetic_flag = True` |

IRFI: más alto = **más riesgo**. ICA: más alto = **más capacidad de ahorro**. Nombre oficial del IRFI **[PENDIENTE: "Inicial" en Contexto Maestro vs. "Individual" en router y diccionario]**.

---

## 8. Preguntas sugeridas (se eligen según el nivel y la situación del perfil)

Los ejemplos son de Ana:

- **Ana primeriza (nivel 1):** "¿Qué es un fondo de emergencia?", "¿Qué tan pesada es mi deuda?", "¿Cómo puedo bajarla?", "¿Cómo empiezo a ahorrar un poco cada mes?"
- **Ana más madura (nivel 2):** "¿Cuánto me falta para tener 3 meses cubiertos?", "¿Puedo empezar a invertir un poco sin descuidar mi colchón?", "¿Cuánto tendría para el retiro si aporto X al mes?", "¿En qué puedo reducir gastos?"
- **Para ambas:** "¿Cuánto me queda cada mes?", "¿Cómo voy con mi meta de ahorro?"

---

## 9. Perfiles de la demo: las dos Anas

La app usa **dos perfiles de Ana**, ambos freelancers y `early_career`. Centavo les habla con el mismo registro claro; lo que cambia es el nivel y, con él, las recomendaciones.

| | Ana primeriza | Ana más madura (provisional) |
|---|---|---|
| Registro real | `PFT_0000636` | `PFT_0002539` |
| Ingreso mensual | $3,704.29 | $3,854.89 |
| Ahorro del mes / ingreso | 16.9% | 36.6% |
| Progreso hacia su meta de ahorro | 28.6% | 60.1% |
| Fondo de emergencia | 0.18 meses | 0.53 meses |
| Endeudamiento | 0.58 | 0.17 |
| **Nivel (§1.2)** | **1 · Primeros pasos** | **2 · Construyendo base** |

**Ejemplo ilustrativo de lo que calcularía `plan_engine`** (no es texto final; el LLM solo lo redacta):

| | Ana primeriza | Ana más madura |
|---|---|---|
| Falta al mes para su meta de ahorro | $1,567 | $936 |
| Falta para 3 meses de gasto en el colchón | $8,692 | $6,044 |
| Deuda, en palabras | "De cada $100 que ganas, $58 van a deudas" | "De cada $100 que ganas, $17 van a deudas" |

- Son **dos personas distintas** del dataset, no la misma persona medida en dos momentos (Gold es corte transversal, `t107`). La narrativa "Ana mejoró" es ilustrativa; la app dice "después de un tiempo usando Moneta" y nunca cuánto tiempo.
- Ana más madura **no** ha cumplido su meta de ahorro (60%), así que el roadmap (§6) se muestra como "esto es lo que viene" y no como celebración.

---

## 10. Limitaciones conocidas

1. **Las dos Anas son dos registros distintos**, no una trayectoria medida.
2. **El nivel mide hábitos, no conocimiento:** el dataset no tiene datos de educación financiera.
3. **El nivel 3 casi no existe en los datos:** solo 1 de 3,000 perfiles (0.03%) tiene 3 meses o más de fondo.
4. **Coherencia interna de PFT:** las columnas nativas son independientes entre sí (§7). Hallazgo de gobierno de datos, igual que la fuga del IRFI en `loan_default`; no se corrige reabriendo Fase 4.
5. **Fabricación residual del modelo 8B local** (`t082`): mitigada con arquitectura (§5), no eliminada.
6. **Datos sintéticos, en USD;** `gasto_promedio_3m` es un snapshot, no un promedio real.

---

## 11. Cambios técnicos derivados

- **`plan_engine` (nuevo, código determinista):** nivel, brechas, aportaciones, meses estimados, escalera del roadmap, proyección de retiro. Funciona con cualquier perfil que traiga las columnas necesarias.
- **`router.py`:** nuevas categorías con herramienta fija (PLAN, PRODUCTO, PERFIL, ROADMAP), cada una con una sola llamada determinista. El System Prompt incorpora el bloque de claridad (§1.1) y recibe el nivel calculado.
- **Datos:** el contexto del perfil necesita `budget_goal`, `actual_savings`, `savings_goal_met`, `investment_amount` y `emergency_fund` en dólares, que hoy no están en Gold. Como la app usa solo las dos Anas, se carga una **tabla Gold nueva y aditiva** (`gold.fact_perfil_detalle`) solo para esos dos `record_id`, con el mismo esquema que tendría para cualquier perfil. No modifica Silver ni Gold aprobados. Se siembra con `config/create-fact-perfil-detalle.sql`, que verifica cada fila contra `gold.fact_comportamiento` mediante una "huella" (ingreso, gasto y endeudamiento) y falla si los `record_id` se desalinearon tras re-correr el pipeline. Guarda la proporción esencial/discrecional, no los montos crudos, para que nadie los sume como partes del gasto. Extenderla a las 3,000 filas queda fuera del MVP y requeriría autorización del mentor para tocar el pipeline de Silver.
- **`text_to_sql.py`:** agregar la tabla nueva en `ALLOWED_TABLES` y en `SCHEMA_CONTEXT`. `create-assistant-ro.sql` ya otorga `SELECT` por `ALTER DEFAULT PRIVILEGES`.
- **`perfiles_sinteticos.py`:** `ARQUETIPOS` pasa de 3 a 2 entradas (las dos Anas); los defaults de ahorro extra del simulador (+10% / +25%) son supuestos de escenario, no datos.
- **Pruebas:** repetir `t082` con las categorías nuevas y la dimensión de claridad (§1.3).

---

## 12. Decisiones

**Cerradas en la Sesión 36** (1-4 del alumno; 5-9 del mentor, reportadas por el alumno):

| # | Decisión | Resultado |
|---|---|---|
| 1 | Llamar al nivel "madurez financiera" (calculado de hábitos) | Aceptado |
| 2 | Regla de 3 niveles de §1.2 | Aceptada |
| 3 | Modo "más detalle" a petición | Aceptado |
| 4 | Nivel 2: inversión y retiro **en paralelo** con el colchón | Aceptado (la regla estricta dejaría sin recomendaciones al 99.97% de los perfiles) |
| 5 | Nivel de madurez como lectura del feedback "personalizar por nivel" | Aprobado |
| 6 | Catálogo cerrado de tipos de producto y exclusión de crédito | Aprobado |
| 7 | Qué se muestra y qué no (§7); incoherencia interna de PFT como hallazgo de gobierno de datos | Aprobado |
| 8 | `savings_goal_met = 1` como disparador del roadmap | Aprobado |
| 9 | Rendimiento por defecto del retiro | Validado: 6.0% anual real, ilustrativo y configurable |

**Pendientes (no bloquean el desarrollo):**
1. Nombre oficial del IRFI ("Inicial" en el Contexto Maestro vs. "Individual" en `router.py` y `diccionario_features.md`).
2. Lista de términos técnicos para la prueba automática de claridad y validación del umbral de 20 palabras (§1.3).
3. Definición de "monto pequeño" de inversión y retiro en el nivel 2 (§4).
4. Re-ejecutar `config/create-fact-perfil-detalle.sql` después de cada corrida del pipeline de Gold: `zipWithIndex` no garantiza el mismo `record_id` entre corridas y la huella lo detecta.
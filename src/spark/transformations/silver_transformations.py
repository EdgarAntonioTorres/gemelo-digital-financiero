"""
Transformaciones Silver — módulo compartido.

Cada tarea de Fase 3 agrega sus propias funciones puras a este
módulo: reciben un DataFrame de Bronze y devuelven un DataFrame transformado,
SIN escribir nada a MinIO. La escritura real a `s3a://silver/` ocurre una
sola vez, al final de la cadena completa, en un script aparte
(build_silver_<fuente>.py) que encadena todas las funciones — así Silver
no queda "a medio cocinar" mientras se van resolviendo.

Tipado correcto (timestamps, decimales):
  1. `ingestion_timestamp` (las 3 fuentes): venía como `string` pese a ser
     una fecha-hora real, sin que nada le dijera a Spark que la
     tratara como tal. Se convierte a `timestamp` nativo.
  2. Columnas de dinero: Spark las infirió como `double` (binario, con
     imprecisión de redondeo — ej. 0.1 + 0.2 != 0.3 exacto). Se convierten
     a `DecimalType(18, 2)` (base 10 exacta, estándar en sistemas
     financieros/contables), decisión deliberada para un proyecto
     financiero, no solo un ejercicio de tipado.
  3. Columnas de tasa/ratio (porcentajes, proporciones): mismo problema de
     precisión que el dinero, pero con más decimales relevantes y montos
     más pequeños — se usa `DecimalType(10, 4)` en vez de `DecimalType(18, 2)`.

No se tocan en `apply_typing()` (resuelto por las funciones de más abajo,
agregadas en esta misma sesión):
  - Deduplicación exacta de filas → `deduplicate()`.
  - Nulos de `dtir1` (16% en Loan Default) → `impute_dtir1_by_group()`.
  - Outliers de `person_income`/`income` (~90x la media) →
    `cap_income_outliers()`.
  - Segmentación <30 años y `age` sintética (Personal Finance Tracker) →
    `derive_synthetic_age()`.
  - Unificación de esquema al dataset maestro → `unify_*_schema()`.

Sigue sin tocarse (fuera de alcance de este módulo):
  - Bins de `age` en Loan Default (categórico por diseño del dataset,
    no es un tipo "incorrecto", ver 5.2 del Contexto Maestro).
  - Columnas hipotecarias/administrativas que se descartan del núcleo
    maestro (5.2.2 del Contexto Maestro). Aquí se tipan igual
    porque siguen existiendo en Bronze/Silver por fuente.

Convención de columnas de flag agregadas en este módulo:
todas son booleanas, indican "este valor fue tocado/derivado por el
pipeline" (`True`) vs. "es el valor original" (`False`) — nunca se
imputa/recorta en silencio (mismo principio que `age_synthetic_flag`
ya usado en `t110`).
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import (
    coalesce,
    col,
    concat,
    expr,
    lit,
    lpad,
    monotonically_increasing_id,
    sin,
    to_timestamp,
    when,
    min,
    max,
)
from pyspark.sql.types import DecimalType, LongType, StructField, StructType

# Precisión/escala para columnas de dinero (montos) vs. tasas/ratios.
# 18 dígitos totales / 2 decimales: suficiente para cualquier monto real
# de este proyecto (ingresos, préstamos) sin desperdiciar espacio.
MONETARY_DECIMAL = DecimalType(18, 2)
# 10 dígitos totales / 4 decimales: tasas de interés y ratios necesitan
# más precisión decimal relativa (ej. 0.0399 = 3.99%) aunque el monto
# absoluto sea pequeño.
RATIO_DECIMAL = DecimalType(10, 4)

# Dos formatos porque datetime.isoformat() en Python omite los
# microsegundos cuando son exactamente 0 (caso raro pero posible) —
# coalesce() prueba el primero y si no matchea (devuelve NULL) intenta
# el segundo, sin arriesgar convertir filas válidas en NULL por accidente.
_TS_FORMAT_CON_MICROS = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX"
_TS_FORMAT_SIN_MICROS = "yyyy-MM-dd'T'HH:mm:ssXXX"

# Mapeo por fuente: qué columnas son dinero vs. tasa/ratio.
# Basado en el schema real de Bronze (confirmado con dump_schema_bronze.py,
# 2026-08-26) y en la semántica de cada columna documentada en el
# Contexto Maestro (§5, §5.2, §8 variables candidatas).
TYPING_RULES = {
    "loan_default": {
        "monetary": ["loan_amount", "Upfront_charges", "property_value", "income"],
        "ratio": ["rate_of_interest", "Interest_rate_spread", "LTV", "dtir1"],
    },
    "credit_risk": {
        "monetary": ["person_income", "loan_amnt"],
        "ratio": ["loan_int_rate", "loan_percent_income"],
    },
    "personal_finance_tracker": {
        "monetary": [
            "monthly_income",
            "monthly_expense_total",
            "budget_goal",
            "loan_payment",
            "investment_amount",
            "emergency_fund",
            "discretionary_spending",
            "essential_spending",
            "rent_or_mortgage",
            "actual_savings",
        ],
        "ratio": ["savings_rate", "debt_to_income_ratio"],
    },
}


def _cast_ingestion_timestamp(df: DataFrame) -> DataFrame:
    """Convierte `ingestion_timestamp` de string ISO 8601 a timestamp real."""
    return df.withColumn(
        "ingestion_timestamp",
        coalesce(
            to_timestamp(col("ingestion_timestamp"), _TS_FORMAT_CON_MICROS),
            to_timestamp(col("ingestion_timestamp"), _TS_FORMAT_SIN_MICROS),
        ),
    )


def _cast_decimal_columns(
    df: DataFrame, columns: list[str], target_type: DecimalType
) -> DataFrame:
    """Convierte una lista de columnas numéricas (double/int) a DecimalType."""
    for column_name in columns:
        df = df.withColumn(column_name, col(column_name).cast(target_type))
    return df


def apply_typing(df: DataFrame, source_name: str) -> DataFrame:
    """Aplica el tipado correcto a un DataFrame de Bronze de una fuente.

    Args:
        df: DataFrame leído directamente de Bronze (schema crudo, inferido
            por Spark en la ingesta).
        source_name: una de "loan_default", "credit_risk",
            "personal_finance_tracker" — determina qué columnas de dinero
            y de ratio se convierten a DecimalType.

    Returns:
        El mismo DataFrame con `ingestion_timestamp` como timestamp real
        y las columnas de dinero/ratio como DecimalType. El resto de las
        columnas queda sin tocar (su tipo inferido por Spark ya era
        correcto — ver docstring del módulo).
    """
    if source_name not in TYPING_RULES:
        raise ValueError(
            f"Fuente desconocida: '{source_name}'. Debe ser una de: "
            f"{list(TYPING_RULES.keys())}"
        )

    rules = TYPING_RULES[source_name]
    df = _cast_ingestion_timestamp(df)
    df = _cast_decimal_columns(df, rules["monetary"], MONETARY_DECIMAL)
    df = _cast_decimal_columns(df, rules["ratio"], RATIO_DECIMAL)
    return df


# ==============================================================================
# Deduplicación
# ==============================================================================

# Columnas de trazabilidad: se excluyen al comparar filas porque
# la MISMA fila de negocio, ingerida en corridas distintas del DAG
# (`ingest_bronze_pipeline`, @daily), trae un `ingestion_timestamp` y
# `dag_run_id` distintos aunque el dato real no haya cambiado. Sin
# excluirlas, dropDuplicates() nunca encontraría duplicados reales.
TRACE_COLUMNS = {"ingestion_date", "ingestion_timestamp", "source_file", "dag_run_id"}


def deduplicate(df: DataFrame) -> DataFrame:
    """Elimina filas 100% idénticas, ignorando las columnas de trazabilidad.

    Decisión: duplicado = fila idéntica en TODAS
    las columnas de negocio. Cubre el caso esperado del DAG `@daily`
    reingiriendo el mismo dataset fuente día tras día — misma
    información, corrida distinta.
    """
    business_columns = [c for c in df.columns if c not in TRACE_COLUMNS]
    return df.dropDuplicates(business_columns)


# ==============================================================================
# Nulos de `dtir1` (Loan Default, 16% del dataset)
# ==============================================================================
def impute_numeric_by_group(
    df: DataFrame, group_col: str, target_col: str
) -> DataFrame:
    """Imputa los nulos de `target_col` con la mediana del grupo
    (`group_col`), marcando cada fila tocada con `{target_col}_imputed_flag`.

    Genérica desde el inicio (antes se llamaba `impute_dtir1_by_group`,
    renombrada en `t054`/Sesión 26 al reutilizarla para `rate_of_interest`
    y `loan_int_rate` — el cuerpo no cambió).

    Por qué mediana y no promedio: las columnas que alimenta (`dtir1`,
    tasas de interés) son ratios con cola larga esperable — la mediana
    es más robusta a esa asimetría.
    Por qué por grupo y no global: asume que el valor típico varía por
    categoría (tipo de préstamo, grado de riesgo), en vez de imponer un
    único valor "típico" a todo el dataset.
    Fallback: si un grupo entero queda sin ningún valor no-nulo, se usa
    la mediana global como respaldo para no dejar nulos residuales.
    """
    flag_col = f"{target_col}_imputed_flag"
    df = df.withColumn(flag_col, col(target_col).isNull())

    group_medians = df.groupBy(group_col).agg(
        expr(f"percentile_approx({target_col}, 0.5)").alias("_group_median")
    )
    global_median = df.agg(
        expr(f"percentile_approx({target_col}, 0.5)").alias("_global_median")
    ).collect()[0]["_global_median"]

    df = df.join(group_medians, on=group_col, how="left")
    df = df.withColumn(
        target_col,
        when(col(target_col).isNotNull(), col(target_col))
        .when(col("_group_median").isNotNull(), col("_group_median"))
        .otherwise(lit(global_median)),
    ).drop("_group_median")
    return df


def impute_numeric_global(df: DataFrame, target_col: str) -> DataFrame:
    """Imputa los nulos de `target_col` con la mediana global (sin
    agrupador), marcando cada fila tocada con `{target_col}_imputed_flag`.

    Uso: cuando no hay una columna categórica claramente correlacionada
    con `target_col` en esa fuente (`t054`/Sesión 26: `person_emp_length`
    en Credit Risk — ninguna columna disponible se relaciona con
    antigüedad laboral lo bastante como para justificar un agrupador,
    a diferencia de `loan_type`→`rate_of_interest` o
    `loan_grade`→`loan_int_rate`, donde sí hay una relación clara).
    """
    flag_col = f"{target_col}_imputed_flag"
    df = df.withColumn(flag_col, col(target_col).isNull())

    global_median = df.agg(
        expr(f"percentile_approx({target_col}, 0.5)").alias("_global_median")
    ).collect()[0]["_global_median"]

    return df.withColumn(
        target_col,
        when(col(target_col).isNotNull(), col(target_col)).otherwise(
            lit(global_median)
        ),
    )


# ==============================================================================
# Outliers de ingreso (`person_income` en Credit Risk,
#         `income` en Loan Default)
# ==============================================================================
def cap_income_outliers(
    df: DataFrame, income_col: str, percentile: float = 0.99
) -> DataFrame:
    """Recorta (winsoriza) los valores de `income_col` por encima del
    percentil dado (p99 por defecto) al valor de ese percentil, y marca
    cada fila tocada con `{income_col}_outlier_flag`.

    Se elige recortar en vez de eliminar la fila: el resto de las
    columnas de esa fila sigue siendo información válida, y eliminar
    filas de Credit Risk pesa más porque es la fuente que el proyecto
    pondera especialmente para usuarios <30 años. El valor SÍ se
    modifica (no solo se marca) porque `income_col` alimenta
    `income_monthly_norm` y, si se usa directo como feature en
    el modelo, un valor 90x la media distorsiona
    cualquier escala/normalización que dependa de él.
    """
    flag_col = f"{income_col}_outlier_flag"
    cap_value = df.approxQuantile(income_col, [percentile], 0.001)[0]

    df = df.withColumn(flag_col, col(income_col) > lit(cap_value))
    df = df.withColumn(
        income_col,
        when(col(income_col) > lit(cap_value), lit(cap_value)).otherwise(
            col(income_col)
        ),
    )
    return df


# ==============================================================================
# Segmentación <30 años y `age` sintética
#             (Personal Finance Tracker — único dataset sin `age` nativa)
# ==============================================================================

# Proporción real de usuarios <30 años observada en Credit Risk (t113),
# usada para calibrar el umbral de segmentación — ver Contexto Maestro
# §5.1. Se mantiene como constante documentada (no recalculada en cada
# corrida) porque es un parámetro validado con el mentor BBVA, no un
# dato que deba re-derivarse de los datos de PFT.
SEGMENTATION_P = 0.7216

# Pesos del maturity_score (§5.1) — no modificar sin repetir la
# validación con el mentor (t111).
_MATURITY_WEIGHTS = {
    "credit_score": 0.30,
    "investment_amount": 0.25,
    "rent_or_mortgage": 0.20,
    "emergency_fund": 0.15,
    "debt_to_income_ratio": 0.10,
}


def _min_max_normalize(df: DataFrame, column: str, alias: str) -> DataFrame:
    """Normaliza una columna a escala 0-1 usando el min/max observado
    en el propio DataFrame (no un min/max externo o supuesto)."""
    stats = df.agg(min(column), max(column)).collect()[0]
    col_min, col_max = stats[f"min({column})"], stats[f"max({column})"]
    span = col_max - col_min
    if span == 0:
        # Caso borde: columna constante — evita división por cero,
        # todas las filas quedan en 0.5 (ni alta ni baja madurez).
        return df.withColumn(alias, lit(0.5))
    return df.withColumn(alias, (col(column) - lit(col_min)) / lit(span))


def derive_synthetic_age(df: DataFrame) -> DataFrame:
    """Deriva `maturity_score`, segmenta en early_career/established, y
    genera `age` sintética — SOLO para Personal Finance Tracker.

    Metodología completa en Contexto Maestro §5.1 (t110/t113/t111,
    validada con el mentor BBVA el 2026-08-11). Agrega las columnas:
      - `maturity_score`: score compuesto 0-1 (ver _MATURITY_WEIGHTS).
      - `segmento`: 'early_career' o 'established'.
      - `age`: entero sintético, coherente con el segmento.
      - `age_synthetic_flag`: True para todas las filas de esta fuente
        (age NUNCA es un valor observado en PFT).

    Nota sobre el "ruido": el Contexto Maestro especifica el uso de
    ruido en la fórmula de edad, sin fijar una implementación numérica
    exacta. Aquí se genera un ruido determinístico y reproducible
    (mismo seed → mismo resultado siempre, requisito de Spark
    distribuido) a partir del ÍNDICE DE FILA (t107: nunca `user_id`,
    que no identifica de forma única una observación en este dataset).
    Si el mentor definió una implementación numérica distinta para el
    ruido, avisar para ajustar esta función — el resto de la
    metodología (pesos, umbral, rangos de edad) no cambia.
    """
    for raw_col, alias in [
        ("credit_score", "_norm_credit_score"),
        ("investment_amount", "_norm_investment_amount"),
        ("rent_or_mortgage", "_norm_rent_or_mortgage"),
        ("emergency_fund", "_norm_emergency_fund"),
        ("debt_to_income_ratio", "_norm_debt_to_income_ratio"),
    ]:
        df = _min_max_normalize(df, raw_col, alias)

    df = df.withColumn(
        "maturity_score",
        lit(_MATURITY_WEIGHTS["credit_score"]) * col("_norm_credit_score")
        + lit(_MATURITY_WEIGHTS["investment_amount"]) * col("_norm_investment_amount")
        + lit(_MATURITY_WEIGHTS["rent_or_mortgage"]) * col("_norm_rent_or_mortgage")
        + lit(_MATURITY_WEIGHTS["emergency_fund"]) * col("_norm_emergency_fund")
        + lit(_MATURITY_WEIGHTS["debt_to_income_ratio"])
        * col("_norm_debt_to_income_ratio"),
    ).drop(
        "_norm_credit_score",
        "_norm_investment_amount",
        "_norm_rent_or_mortgage",
        "_norm_emergency_fund",
        "_norm_debt_to_income_ratio",
    )

    # Umbral calibrado dinámicamente contra los datos reales de esta
    # corrida (documentado como 0.4624 en el Contexto Maestro con el
    # dataset de referencia — approxQuantile puede diferir en la
    # milésima si el dataset fuente cambia levemente entre versiones
    # de Kaggle).
    threshold = df.approxQuantile("maturity_score", [SEGMENTATION_P], 0.001)[0]

    df = df.withColumn(
        "segmento",
        when(col("maturity_score") < lit(threshold), lit("early_career")).otherwise(
            lit("established")
        ),
    )

    # Índice de fila estable dentro de esta corrida (t107: seed por
    # índice, no por user_id). monotonically_increasing_id() no es
    # denso ni reiniciable entre corridas — no importa aquí, solo se
    # usa como semilla determinística de ruido dentro de ESTA corrida.
    df = df.withColumn("_row_idx", monotonically_increasing_id())
    # Ruido determinístico en un rango pequeño (~[-1.5, 1.5]) vía
    # función seno sobre el índice — mismo índice siempre produce el
    # mismo ruido (reproducible), sin depender de F.rand() (no
    # reproducible de forma determinística fila a fila en Spark).
    df = df.withColumn("_noise", sin(col("_row_idx").cast("double")) * lit(1.5))

    age_early_career = (
        lit(20) + (col("maturity_score") / lit(threshold)) * lit(9) + col("_noise")
    )
    age_established = (
        lit(30)
        + ((col("maturity_score") - lit(threshold)) / lit(1 - threshold)) * lit(30)
        + col("_noise")
    )

    df = df.withColumn("age_early_career_raw", age_early_career)
    df = df.withColumn("age_established_raw", age_established)
    df = df.withColumn(
        "age",
        when(
            col("segmento") == lit("early_career"),
            expr("greatest(20, least(29, round(age_early_career_raw)))"),
        ).otherwise(expr("greatest(30, least(60, round(age_established_raw)))")),
    )
    df = df.withColumn("age_synthetic_flag", lit(True))
    df = df.drop("_row_idx", "_noise", "age_early_career_raw", "age_established_raw")
    return df


# ==============================================================================
# Unificación de esquema al dataset maestro
# ==============================================================================

# Tabla ordinal de loan_grade (Credit Risk): A=mejor -> G=peor.
# Se invierte a 7..1 para que, tras normalizar 0-1, un valor más alto
# de credit_score_norm siga significando "mejor crédito" en las 3
# fuentes (igual dirección que Credit_Score/credit_score numéricos).
_LOAN_GRADE_ORDINAL = {"A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1}


def _add_record_id(df: DataFrame, prefix: str) -> DataFrame:
    """Genera `record_id` sintético prefijado por fuente (PFT_00001,
    CR_00001, LD_00001) — no existe llave real entre las 3 fuentes
    (Contexto Maestro §5.2/§t043), el `record_id` solo da trazabilidad
    al origen, no identidad real entre fuentes.

    CORRECCIÓN (hallazgo de la sesión de verificación,
    segunda vuelta): la primera versión usaba
    `row_number().over(Window.orderBy(monotonically_increasing_id()))`.
    Se veía razonable y hasta pasaba una revisión superficial, pero es
    un antipatrón documentado de Spark: `monotonically_increasing_id()`
    es una expresión NO determinística, y usarla como llave de orden
    de un Window puede hacer que Catalyst la evalúe más de una vez
    para la misma fila dentro de la ejecución de un mismo plan,
    rompiendo la garantía de secuencia única que `row_number()`
    necesita. El síntoma fue consistente en 3 corridas distintas
    (siempre 48,671 colisiones exactas) — no era un problema de
    materialización/caché (ya se había agregado `cache()`+`count()`
    sin resultado), sino de la función en sí como llave de orden.

    La corrección usa `RDD.zipWithIndex()`, la técnica estándar y
    garantizada en Spark para numerar filas de forma única — no
    depende de ordenar ninguna expresión no determinística.
    """
    df = df.cache()
    df.count()  # materializar antes del zipWithIndex, para estabilidad

    indexed_rdd = df.rdd.zipWithIndex().map(lambda pair: (*pair[0], pair[1]))
    schema_with_seq = StructType(
        df.schema.fields + [StructField("_seq", LongType(), nullable=False)]
    )
    df = df.sparkSession.createDataFrame(indexed_rdd, schema_with_seq)

    df = df.withColumn(
        "record_id",
        concat(lit(f"{prefix}_"), lpad((col("_seq") + 1).cast("string"), 7, "0")),
    ).drop("_seq")
    return df


def unify_loan_default_schema(df_indexed: DataFrame) -> DataFrame:
    """Mapea Loan Default (ya limpio) a las 5 columnas del dataset
    maestro, según la tabla de Contexto Maestro §5.2.

    IMPORTANTE (Sesión 26, Contexto Maestro §6.2.1): `df_indexed` debe
    llegar YA con `record_id` (vía `_add_record_id`, llamado una sola
    vez por el caller). No se genera aquí adentro para evitar que
    `select_kpi_components_loan_default()` reciba un `record_id`
    distinto para la misma fila física — `zipWithIndex()` no garantiza
    el mismo orden entre dos llamadas/lecturas separadas.
    """
    df = df_indexed
    df = _min_max_normalize(df, "Credit_Score", "credit_score_norm")
    return df.select(
        "record_id",
        lit("loan_default").alias("fuente"),
        col("credit_score_norm"),
        (col("dtir1") / lit(100)).alias("debt_to_income_norm"),
        (col("income") / lit(12)).alias("income_monthly_norm"),
        # Loan Default solo trae bins de edad (<25...>74) — se
        # mantiene como string, no se fuerza a numérico (§5.2: evita
        # apilar un supuesto de distribución uniforme sobre otro).
        col("age").cast("string").alias("age_unificada"),
        lit(False).alias("age_synthetic_flag"),
        col("Status").cast("double").alias("default_flag_unificada"),
    )


def unify_credit_risk_schema(df_indexed: DataFrame) -> DataFrame:
    """Mapea Credit Risk (ya limpio) a las 5 columnas del dataset
    maestro, según la tabla de Contexto Maestro §5.2.

    IMPORTANTE (Sesión 26, §6.2.1): `df_indexed` debe llegar ya con
    `record_id` — ver nota idéntica en `unify_loan_default_schema`.
    """
    df = df_indexed

    grade_map = expr(
        "CASE loan_grade "
        + " ".join(f"WHEN '{g}' THEN {v}" for g, v in _LOAN_GRADE_ORDINAL.items())
        + " ELSE NULL END"
    )
    df = df.withColumn("_grade_ordinal", grade_map)
    df = _min_max_normalize(df, "_grade_ordinal", "credit_score_norm")

    return df.select(
        "record_id",
        lit("credit_risk").alias("fuente"),
        col("credit_score_norm"),
        col("loan_percent_income").alias("debt_to_income_norm"),
        (col("person_income") / lit(12)).alias("income_monthly_norm"),
        col("person_age").cast("string").alias("age_unificada"),
        lit(False).alias("age_synthetic_flag"),
        col("loan_status").cast("double").alias("default_flag_unificada"),
    )


def unify_pft_schema(df_indexed: DataFrame) -> DataFrame:
    """Mapea Personal Finance Tracker (ya limpio y con `age` sintética
    de `derive_synthetic_age()`) a las 5 columnas del dataset maestro.

    IMPORTANTE (Sesión 26, §6.2.1): `df_indexed` debe llegar ya con
    `record_id` — ver nota idéntica en `unify_loan_default_schema`.
    """
    df = df_indexed
    df = _min_max_normalize(df, "credit_score", "credit_score_norm")
    return df.select(
        "record_id",
        lit("personal_finance_tracker").alias("fuente"),
        col("credit_score_norm"),
        col("debt_to_income_ratio").alias("debt_to_income_norm"),
        col("monthly_income").alias("income_monthly_norm"),
        col("age").cast("string").alias("age_unificada"),
        col("age_synthetic_flag"),
        # PFT no tiene equivalente real de default de crédito —
        # queda NULL a propósito (§5.2: cash_flow_status='Negative' es
        # cualitativo, fusionarlo inventaría una equivalencia que los
        # datos no sostienen).
        lit(None).cast("double").alias("default_flag_unificada"),
    )


# ==============================================================================
# Componentes crudos para IRFI/ICA por fuente — Contexto Maestro §6.2.1
# (Sesión 26)
#
# Las fórmulas de IRFI/ICA se diseñaron sobre columnas
# nativas de Credit Risk. Al extender el dataset maestro a 3 fuentes,
# se decidió NO modificar las fórmulas (ya aprobadas por el
# mentor BBVA el 2026-08-11) sino extender su aplicación vía proxies
# documentados — mismo criterio ya usado en `credit_score_norm` (§5.2).
#
# Estas funciones reciben el MISMO DataFrame ya indexado con
# `record_id` que produce la fila del maestro (nunca una segunda
# lectura/llamada independiente — ver nota de riesgo en
# `unify_loan_default_schema` sobre por qué `zipWithIndex()` no
# garantiza el mismo orden entre dos corridas separadas). Solo exponen
# las columnas fuente con nombres neutros; la derivación completa
# (normalización, mapeo a peso neutro cuando no hay proxy razonable)
# vive en `calculate_kpis.py`, no aquí — este módulo es de limpieza
# Silver, no de cálculo de KPI de Gold.
# ==============================================================================

# Mapeo ordinal income_type -> estabilidad laboral (0-1), Personal
# Finance Tracker. Confirmado con value_counts() real (Sesión 26):
# Salary=2154, Freelance=529, Mixed=317. Salario fijo = más estable;
# freelance = menos estable; mixto = punto medio.
INCOME_TYPE_STABILITY = {"Salary": 1.0, "Mixed": 0.5, "Freelance": 0.0}

# Mapeo Neg_ammortization -> flag (Loan Default). Confirmado con
# value_counts() real (Sesión 26): 89.74% not_neg, 10.18% neg_amm,
# 0.08% NaN (121 filas) — variabilidad real (10%), NO se descarta como
# ruido/casi-constante (hipótesis inicial descartada con datos reales).
# La columna sigue fuera del núcleo del dataset maestro (§5.2.2,
# consistente) pero se reincorpora, ya tipada, solo para
# este cálculo de KPI — mismo patrón que las columnas de §5.2.1.
NEG_AMORTIZATION_FLAG_MAP = {"neg_amm": 1.0, "not_neg": 0.0}


def select_kpi_components_credit_risk(df_indexed: DataFrame) -> DataFrame:
    """Columnas crudas de Credit Risk necesarias para IRFI/ICA.

    No incluye un proxy de `grade_score`: para Credit Risk, ese
    componente se toma directo de `credit_score_norm` del maestro (ya
    es la normalización de `loan_grade`, calcularlo de nuevo aquí
    sería redundante) — ver `calculate_kpis.py`.
    """
    return df_indexed.select(
        "record_id",
        col("person_emp_length").alias("_emp_raw"),
        col("cb_person_cred_hist_length").alias("_credit_hist_raw"),
        col("loan_int_rate").alias("_interest_rate_raw"),
        col("person_home_ownership").alias("_housing_raw"),
    )


def select_kpi_components_loan_default(df_indexed: DataFrame) -> DataFrame:
    """Columnas crudas de Loan Default necesarias para IRFI/ICA.

    Sin proxy razonable para `emp_stability`/`grade_score`/
    `credit_hist_norm`/`housing_penalty` (§6.2.1) — se ponderan neutro
    en `calculate_kpis.py`, no se exponen aquí.
    """
    return df_indexed.select(
        "record_id",
        col("rate_of_interest").alias("_interest_rate_raw"),
        col("Neg_ammortization").alias("_neg_amortization_raw"),
    )


def select_kpi_components_pft(df_indexed: DataFrame) -> DataFrame:
    """Columnas crudas de Personal Finance Tracker necesarias para
    IRFI/ICA.

    Sin proxy razonable para `credit_hist_norm`/`loan_int_rate_norm`
    (PFT no es un dataset de préstamos) ni para `grade_score`
    (usar `credit_score_norm` violaría la exclusión deliberada de
    `Credit_Score`/`credit_score` en IRFI, §6.2 — corregido en
    Sesión 26, no se expone aquí).
    """
    return df_indexed.select(
        "record_id",
        col("income_type").alias("_income_type_raw"),
        col("rent_or_mortgage").alias("_rent_or_mortgage_raw"),
    )


# ==============================================================================
# Verificación manual (NO escribe a Silver — solo confirma que el tipado
# se aplicó correctamente, leyendo la partición de hoy de cada fuente).
# ==============================================================================
if __name__ == "__main__":
    import os

    from pyspark.sql import SparkSession

    def build_spark_session() -> SparkSession:
        spark = (
            SparkSession.builder.appName("verify_t038_typing")
            .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
            .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
            .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
            .config(
                "spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem"
            )
            .config("spark.sql.parquet.mergeSchema", "true")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        return spark

    BRONZE_PATHS = {
        "loan_default": "s3a://bronze/loan_default/",
        "credit_risk": "s3a://bronze/credit_risk/",
        "personal_finance_tracker": "s3a://bronze/personal_finance_tracker/",
    }

    spark = build_spark_session()
    try:
        for source, path in BRONZE_PATHS.items():
            print(
                f"\n=== {source}: valores crudos de ingestion_timestamp por partición ==="
            )
            df_raw = spark.read.parquet(path)
            df_raw.select("ingestion_date", "ingestion_timestamp").distinct().orderBy(
                "ingestion_date"
            ).show(truncate=False)

            df_typed = apply_typing(df_raw, source)

            # Verificación de que no se perdieron filas al castear
            # ingestion_timestamp (si el coalesce no matcheara ningún
            # formato, la fila quedaría con NULL en vez de fallar).
            nulos_ts = df_typed.filter(col("ingestion_timestamp").isNull()).count()
            print(f"Filas con ingestion_timestamp NULL tras el cast: {nulos_ts}")
    finally:
        spark.stop()

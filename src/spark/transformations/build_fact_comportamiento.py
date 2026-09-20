"""
Gold — FACT_COMPORTAMIENTO: gasto/ingreso, endeudamiento, fraude,
intensidad de suscripciones y fondo de emergencia (`t054`-`t057`)

Contexto Maestro §6.3 ya anotaba `FACT_COMPORTAMIENTO` como tabla
pendiente (grano 1 fila por `record_id` de Personal Finance Tracker).
Este script cierra Fase 4 columna por columna en la MISMA tabla
(`t054`-`t057`, todas cerradas) — evita fragmentar el feature store en
una tabla de 1 columna por feature. Solo queda `t058` (documentar el
diccionario de features) para cerrar el bloque de feature engineering
de Fase 4.

`t057` — capacidad de ahorro para primer fondo de emergencia: a
diferencia de `t054`/`t056`, no hubo vacío de tipo de dato —
`emergency_fund` ya es un monto en USD nativo (`DecimalType(18,2)`,
ver `TYPING_RULES` en `silver_transformations.py`).
`fondo_emergencia_meses` = `emergency_fund` / `monthly_expense_total`
— meses de gasto que cubre el fondo actual, benchmark estándar de la
industria financiera (3-6 meses), usando 2 columnas reales sin
inventar nada.

`t056` — otro vacío real descubierto con datos, no asumido (Sesión
27): la tarea original pide "% de ingreso destinado a suscripciones
mensuales", pero `subscription_services` **no es un monto en USD** —
es un ENTERO de 1 a 9 (confirmado con `describe()` real: media 4.98,
stddev 2.56), es decir, "número de suscripciones activas". No existe
en el dataset ningún monto en dólares específico de gasto en
suscripciones (`essential_spending`/`discretionary_spending` son
categorías de gasto distintas, no desglosan suscripciones). Calcular
un "%" real habría requerido inventar un costo promedio por
suscripción (ej. "$15 USD/mes") — un supuesto externo sin respaldo en
los datos, descartado por el mismo criterio que ya se usó en `t054`
(`t110`: no fabricar lo que los datos no sostienen).

En su lugar, `suscripciones_por_1000_ingreso` = `subscription_services
/ (monthly_income / 1000)` — intensidad relativa (cuántas
suscripciones activas tiene la persona por cada $1,000 de ingreso
mensual), usando solo datos reales del dataset, sin ningún precio
inventado. No es literalmente el "%" que pedía el nombre original de
`t056`, igual que `gasto_promedio_3m` no es literalmente un promedio
de 3 meses — mismo criterio de honestidad metodológica en ambos casos,
documentado aquí y a documentar en el Contexto Maestro.

`t055` — ratio de endeudamiento y alerta de fraude: ambas columnas ya
vienen NATIVAS en Personal Finance Tracker (`debt_to_income_ratio`,
`fraud_flag`), sin necesidad de proxy ni derivación — a diferencia de
`t054`/`t056`, aquí no hubo ningún vacío metodológico que resolver. Se
renombran a español para consistencia con el resto de
`FACT_COMPORTAMIENTO` (`ratio_endeudamiento`, `alerta_fraude`) y se
castea `fraud_flag` a `boolean` explícitamente (llega como 0/1 sin
tipar desde Bronze/Silver) — mismo criterio de tipos explícitos que
`irfi_proxy_flag`/`ica_proxy_flag` en `calculate_kpis.py`.

Decisión de metodología para `t054` (Sesión 27, cierra `t114` con
texto real): Personal Finance Tracker es corte transversal (`t107`,
confirmado) — no existen múltiples fechas por `user_id`, así que un
"promedio de 3 meses" o una "varianza de ingresos" real (a través del
tiempo, por persona) NO se pueden calcular con los datos tal cual
vienen. Se decidió NO fabricar una serie de tiempo sintética (habría
requerido inventar un parámetro de ruido sin dato real que lo
sostenga). En su lugar:

  - `gasto_promedio_3m` = `monthly_expense_total` tal cual (snapshot
    transversal). Es una APROXIMACIÓN documentada, no un promedio real
    de 3 meses.
  - `varianza_ingreso_segmento` = varianza poblacional de
    `monthly_income` DENTRO del segmento `income_type` del usuario
    (Salary/Mixed/Freelance), no una varianza temporal por persona.
    **Nota real de los datos (Sesión 27):** con la muestra actual,
    `Mixed` (932,722) queda por DEBAJO de `Salary` (973,513) en vez de
    en punto medio entre `Salary` y `Freelance` (1,144,057) como
    sugeriría la intuición — no es un bug, es la varianza real
    observada en una muestra de 317 filas. No presentar en el
    dashboard como si `Mixed` fuera automáticamente "más estable que
    Salary" sin esta salvedad.

Todas las aproximaciones (`t054`, `t056`) quedan documentadas aquí y
en el Contexto Maestro como lo que son: razonadas, no lo que el
nombre original de cada tarea sugiere literalmente. Mismo espíritu de
trazabilidad que `irfi_proxy_flag`/`age_synthetic_flag` — la
diferencia es que estas aproximaciones aplican a TODAS las filas por
igual (son decisiones estructurales, no excepciones fila por fila),
así que no se agrega un flag booleano que sería `True` en el 100% de
los casos; queda documentado aquí en texto en su lugar.

Lee:
    s3a://silver/dim_comportamiento_pft/  (record_id, monthly_income,
    monthly_expense_total, income_type, debt_to_income_ratio,
    fraud_flag, subscription_services, emergency_fund, actual_savings
    — actual_savings queda sin usar por ahora, disponible para futuras
    features del dashboard)

Escribe:
    s3a://gold/fact_comportamiento/  (Parquet)

Modo de escritura: overwrite, no histórico — mismo criterio que
FACT_KPI_PERFIL (Contexto Maestro §6.4): Personal Finance Tracker es
corte transversal, no tiene sentido acumular historial de un dato que
tampoco tiene historia real detrás.

Uso (dentro del contenedor de Airflow, después de build_silver_master.py):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/transformations/build_fact_comportamiento.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import SparkSession, Window
from pyspark.sql.functions import col, expr, lit, var_pop, when

SILVER_DIM_COMPORTAMIENTO_PFT_PATH = "s3a://silver/dim_comportamiento_pft/"
SILVER_MASTER_PATH = "s3a://silver/master/"
GOLD_FACT_COMPORTAMIENTO_PATH = "s3a://gold/fact_comportamiento/"

# Mismo umbral y mismo criterio que calculate_kpis.py (hallazgo Sesión
# 30): segmento nunca se propagó a Gold. Aquí siempre es
# 'personal_finance_tracker' (grano de esta tabla), que SÍ trae edad
# exacta en age_unificada — a diferencia de calculate_kpis.py, no se
# espera NULL en la práctica, pero se usa el mismo try_cast por
# consistencia y por si algún registro llega con age_unificada
# corrupta (defensivo, no un caso esperado).
SEGMENTO_AGE_THRESHOLD = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_fact_comportamiento")


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("build_fact_comportamiento")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def main() -> None:
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info(
            "Leyendo componentes de comportamiento: %s",
            SILVER_DIM_COMPORTAMIENTO_PFT_PATH,
        )
        df = spark.read.parquet(SILVER_DIM_COMPORTAMIENTO_PFT_PATH)

        # segmento (hallazgo Sesión 30): no vive en dim_comportamiento_pft
        # (nunca se seleccionó ahí, ver silver_transformations.py), pero
        # SÍ vive como age_unificada en el maestro — se une por
        # record_id en vez de tocar Silver de nuevo. Solo se trae
        # age_unificada, no el resto de columnas del maestro (no se
        # necesitan aquí).
        logger.info("Leyendo age_unificada del maestro: %s", SILVER_MASTER_PATH)
        df_age = spark.read.parquet(SILVER_MASTER_PATH).select(
            "record_id", "age_unificada"
        )
        df = df.join(df_age, on="record_id", how="left")
        # Bug corregido (Sesión 30, ver mismo fix en calculate_kpis.py):
        # try_cast directo a INT falla con age_unificada = "34.0"
        # (age es double antes del cast a string en unify_pft_schema) —
        # daba NULL en las 3,000 filas. Cast a DOUBLE primero.
        df = df.withColumn(
            "_age_parsed", expr("try_cast(age_unificada AS DOUBLE)").cast("int")
        )
        df = df.withColumn(
            "segmento",
            when(col("_age_parsed").isNull(), lit(None))
            .when(
                col("_age_parsed") < lit(SEGMENTO_AGE_THRESHOLD),
                lit("early_career"),
            )
            .otherwise(lit("established")),
        ).drop("_age_parsed", "age_unificada")

        # gasto_promedio_3m: proxy directo (ver docstring del módulo).
        df = df.withColumn("gasto_promedio_3m", col("monthly_expense_total"))

        # varianza_ingreso_segmento: varianza poblacional de
        # monthly_income dentro de cada income_type (ver docstring).
        # var_pop, no var_samp: se trata el segmento observado como la
        # población completa de interés, no una muestra de algo mayor
        # (mismo dataset se usa para todo el proyecto, no hay
        # intención de inferir sobre una población externa).
        window_by_segment = Window.partitionBy("income_type")
        df = df.withColumn(
            "varianza_ingreso_segmento",
            var_pop("monthly_income").over(window_by_segment),
        )

        # t055: ambas columnas nativas de PFT, sin proxy necesario (ver
        # docstring del módulo). Se castea fraud_flag a boolean
        # explícito (llega como 0/1 sin tipar desde Bronze/Silver).
        df = df.withColumn("ratio_endeudamiento", col("debt_to_income_ratio"))
        df = df.withColumn("alerta_fraude", col("fraud_flag").cast("boolean"))

        # t056: subscription_services es un CONTEO (1-9), no un monto —
        # confirmado con datos reales (ver docstring). Intensidad
        # relativa por cada $1,000 de ingreso mensual, sin inventar
        # ningún costo promedio por suscripción.
        df = df.withColumn(
            "suscripciones_por_1000_ingreso",
            col("subscription_services") / (col("monthly_income") / lit(1000)),
        )

        # t057: meses de gasto que cubre el fondo de emergencia actual
        # (benchmark estándar de la industria: 3-6 meses).
        df = df.withColumn(
            "fondo_emergencia_meses",
            col("emergency_fund") / col("monthly_expense_total"),
        )

        df_fact = df.select(
            "record_id",
            lit("personal_finance_tracker").alias("fuente"),
            "segmento",
            "income_type",
            # Hallazgo Sesión 30 (t059): monthly_income se usaba para
            # calcular varianza_ingreso_segmento y
            # suscripciones_por_1000_ingreso, pero nunca se guardaba
            # como columna propia — t059 pide "ingresos vs. gastos" y
            # sin esto solo había gastos.
            col("monthly_income").alias("ingreso_mensual"),
            "gasto_promedio_3m",
            "varianza_ingreso_segmento",
            "ratio_endeudamiento",
            "alerta_fraude",
            "suscripciones_por_1000_ingreso",
            "fondo_emergencia_meses",
        )

        total_rows = df_fact.count()
        logger.info("FACT_COMPORTAMIENTO: %s filas totales", total_rows)

        segment_counts = df_fact.groupBy("income_type").count().collect()
        logger.info(
            "Filas por segmento (income_type): %s",
            {row["income_type"]: row["count"] for row in segment_counts},
        )

        segmento_counts = df_fact.groupBy("segmento").count().collect()
        logger.info(
            "Filas por segmento (edad, hallazgo Sesión 30): %s",
            {row["segmento"]: row["count"] for row in segmento_counts},
        )

        varianza_por_segmento = (
            df_fact.select("income_type", "varianza_ingreso_segmento")
            .distinct()
            .collect()
        )
        logger.info(
            "varianza_ingreso_segmento por segmento: %s",
            {
                row["income_type"]: row["varianza_ingreso_segmento"]
                for row in varianza_por_segmento
            },
        )

        fraud_counts = df_fact.groupBy("alerta_fraude").count().collect()
        logger.info(
            "alerta_fraude: %s",
            {row["alerta_fraude"]: row["count"] for row in fraud_counts},
        )

        logger.info("--- suscripciones_por_1000_ingreso: estadísticas descriptivas ---")
        df_fact.select("suscripciones_por_1000_ingreso").describe().show()

        logger.info("--- fondo_emergencia_meses: estadísticas descriptivas ---")
        df_fact.select("fondo_emergencia_meses").describe().show()
        # monthly_expense_total = 0 daría división entre cero (infinito,
        # no nulo, en Spark) — se chequea explícitamente en vez de
        # confiar en que describe() lo hubiera mostrado con claridad.
        infinitos = df_fact.filter(
            col("fondo_emergencia_meses") == float("inf")
        ).count()
        if infinitos > 0:
            logger.warning(
                "%s filas con fondo_emergencia_meses infinito "
                "(monthly_expense_total = 0) — revisar antes de usar en el dashboard.",
                infinitos,
            )

        logger.info(
            "Escribiendo FACT_COMPORTAMIENTO en: %s", GOLD_FACT_COMPORTAMIENTO_PATH
        )
        df_fact.write.mode("overwrite").option("compression", "snappy").parquet(
            GOLD_FACT_COMPORTAMIENTO_PATH
        )
        logger.info("FACT_COMPORTAMIENTO completado: %s filas escritas.", total_rows)
    except Exception:
        logger.exception("Falló la construcción de FACT_COMPORTAMIENTO.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

"""
Diagnóstico — `t073b`: ¿es `financial_scenario` útil para validar el simulador?

Contexto (decisión pendiente con el mentor BBVA, Opción C de 3
propuestas): antes de decidir si vale la pena reabrir Silver/Gold para
llevar `financial_scenario` hasta `gold.fact_comportamiento` (Opción
A) o descartar `t073b` del alcance del MVP (Opción B), hace falta ver
qué es realmente esta columna con datos reales — el Contexto Maestro
la documenta como "nativa" de Personal Finance Tracker (§5) pero
nunca se inspeccionó su contenido.

Deliberadamente NO toca ningún entregable ya aprobado:

  - Lee directo de `s3a://silver/personal_finance_tracker/` — la
    tabla Silver YA completa de esta fuente (la que
    `build_silver_master.py` lee después). Esta tabla SÍ trae
    `financial_scenario`, `segmento` e `income_type`: nadie las quitó
    ahí, `apply_typing()`/`deduplicate()`/`derive_synthetic_age()`
    (`silver_transformations.py`) no filtran columnas. Lo que nunca
    las lleva más lejos es `build_silver_master.py`
    (`unify_pft_schema()` / `select_comportamiento_components_pft()`
    no las seleccionan hacia el maestro ni hacia
    `dim_comportamiento_pft`) — por eso no llegan a Gold, no porque
    se hayan perdido en Silver.
  - NO genera `record_id` ni cruza contra `gold.fact_comportamiento`
    en Postgres. `build_silver_master.py` ya documenta el riesgo
    explícito: `RDD.zipWithIndex()` no garantiza el mismo orden entre
    corridas separadas — recalcular `record_id` aquí para cruzar con
    Gold podría desalinear filas en silencio. Todo el análisis de
    este script es AGREGADO (conteos, cruces de categorías), nunca
    fila por fila — mismo criterio ya usado en todo el proyecto para
    evitar suposiciones sin respaldo.
  - No escribe nada a ningún lado, solo imprime a consola/logs — mismo
    espíritu que `diagnose_null_kpis.py` / `verify_silver.py`.

Qué mirar en la salida para decidir con el mentor:
  1. ¿Cuántas categorías tiene `financial_scenario` y qué tan pobladas
     están? Si hay una categoría dominante o categorías con muy pocas
     filas, eso ya condiciona qué tan útil sería para validar 3
     escenarios distintos.
  2. ¿Los nombres de las categorías se relacionan conceptualmente con
     los 3 escenarios ya implementados (renta/auto/empleo, `t068`-
     `t070`)? Si no hay relación semántica clara, la Opción A pierde
     fuerza sin importar el volumen de datos.
  3. ¿`financial_scenario` varía de forma coherente por `segmento`/
     `income_type`, o parece independiente de todo lo demás? Si no
     covaría con nada que el simulador ya usa, es una señal débil para
     validar contra ella.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/diagnose_financial_scenario_t073b.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count
from pyspark.sql.functions import round as spark_round

SILVER_PFT_PATH = "s3a://silver/personal_finance_tracker/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("diagnose_financial_scenario_t073b")


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
        SparkSession.builder.appName("diagnose_financial_scenario_t073b")
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
    spark = build_spark_session()
    try:
        logger.info("Leyendo Silver de personal_finance_tracker: %s", SILVER_PFT_PATH)
        df = spark.read.parquet(SILVER_PFT_PATH)

        columnas_esperadas = {"financial_scenario", "segmento", "income_type"}
        faltantes = columnas_esperadas - set(df.columns)
        if faltantes:
            logger.error(
                "Faltan columnas esperadas en Silver PFT: %s — revisar si "
                "cambió el esquema de Bronze/Silver antes de continuar. "
                "Deteniendo el diagnóstico aquí (no se asume nada).",
                faltantes,
            )
            return

        total = df.count()
        logger.info("Filas totales en Silver PFT: %s", total)

        logger.info("--- 1. Valores distintos de financial_scenario (global) ---")
        (
            df.groupBy("financial_scenario")
            .agg(count("*").alias("n"))
            .withColumn("pct", spark_round(col("n") / total * 100, 2))
            .orderBy(col("n").desc())
            .show(50, truncate=False)
        )

        logger.info(
            "--- 2. financial_scenario x segmento (early_career/established) ---"
        )
        (
            df.groupBy("financial_scenario", "segmento")
            .agg(count("*").alias("n"))
            .orderBy("financial_scenario", "segmento")
            .show(100, truncate=False)
        )

        logger.info(
            "--- 3. financial_scenario x income_type (Salary/Mixed/Freelance) ---"
        )
        (
            df.groupBy("financial_scenario", "income_type")
            .agg(count("*").alias("n"))
            .orderBy("financial_scenario", "income_type")
            .show(100, truncate=False)
        )

        logger.info(
            "Diagnóstico completado — no se escribió nada a ningún lado. "
            "Revisar la salida de arriba contra las 3 preguntas del docstring "
            "de este script antes de la conversación con el mentor."
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

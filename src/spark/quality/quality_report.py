"""
Reporte de % de registros que pasan validación — Fase 3 (`t047`).

Corre DESPUÉS de los 3 `build_silver_<fuente>.py` (que ya separaron
válidas/cuarentena vía `quarantine_and_write()`, t046). Este script no
vuelve a decidir nada de calidad — solo LEE lo que ya quedó escrito en
Silver y en cuarentena, calcula el % de registros que pasaron por
fuente, y lo persiste en Postgres para que `t048`/`t049` (Streamlit)
lo consuman sin tener que recalcular nada ni hablar con MinIO.

Qué mide "% que pasa validación" aquí (importante, no confundir con
t045): es un número POR FILA — cuántos registros terminaron en Silver
vs. en cuarentena — no el % de expectativas de Great Expectations que
pasaron (eso es agregado a nivel de regla, ver `great_expectations_runner.py`).
Se incluye también el detalle de GE sobre el Silver YA filtrado
(post-cuarentena), como diagnóstico adicional — debería acercarse a
100% de expectativas si `t046` está haciendo bien su trabajo, y si no
es una señal de que faltó cubrir alguna regla en `expectations_config.py`.

Tabla destino: `operational.quality_metrics` en `postgres-dw` (mismo
motor que Gold, esquema `operational` ya existe en
`init-dw-schemas.sql` desde `t051`). Igual que el primer `write()` de
`load_gold_postgres.py` (Sesión 27): se escribe en modo `append` sin
DDL explícito primero — Spark JDBC crea la tabla si no existe,
infiriendo tipos. Si luego quieres una PK/índice sobre
(`source`, `run_timestamp`), agrégala a mano en `init-dw-schemas.sql`
una vez que el esquema real esté confirmado, mismo criterio ya usado
para `gold.fact_kpi_perfil`.

Uso (dentro del contenedor de Airflow, después de los 3 build_silver):
    spark-submit \\
        --packages org.apache.hadoop:hadoop-aws:3.3.4,org.postgresql:postgresql:42.7.3 \\
        /opt/airflow/src/spark/quality/quality_report.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY, DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER,
DW_POSTGRES_PASSWORD (ya presentes en docker-compose.yml desde t051).
"""

import logging
import os
import sys
import time

from pyspark.sql import Row, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from great_expectations_runner import run_expectations
from quarantine import QUARANTINE_PATHS
from pipeline_timing import log_execution

SILVER_PATHS = {
    "loan_default": "s3a://silver/loan_default/",
    "credit_risk": "s3a://silver/credit_risk/",
    "personal_finance_tracker": "s3a://silver/personal_finance_tracker/",
}

QUALITY_METRICS_TABLE = "operational.quality_metrics"

REPORT_SCHEMA = StructType(
    [
        StructField("run_timestamp", TimestampType(), False),
        StructField("source", StringType(), False),
        StructField("valid_rows", IntegerType(), False),
        StructField("quarantined_rows", IntegerType(), False),
        StructField("total_rows", IntegerType(), False),
        StructField("pass_rate_records", DoubleType(), False),
        StructField("ge_expectations_total", IntegerType(), False),
        StructField("ge_expectations_passed", IntegerType(), False),
        StructField("ge_pass_rate_rules", DoubleType(), False),
    ]
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("quality_report")


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
        SparkSession.builder.appName("quality_report")
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


def build_jdbc_url() -> tuple[str, dict[str, str]]:
    host = get_required_env("DW_POSTGRES_HOST")
    db = get_required_env("DW_POSTGRES_DB")
    user = get_required_env("DW_POSTGRES_USER")
    password = get_required_env("DW_POSTGRES_PASSWORD")
    url = f"jdbc:postgresql://{host}:5432/{db}"
    properties = {"user": user, "password": password, "driver": "org.postgresql.Driver"}
    return url, properties


def report_for_source(spark: SparkSession, source_name: str) -> Row:
    logger.info("Calculando métricas de calidad para: %s", source_name)

    silver_df = spark.read.parquet(SILVER_PATHS[source_name])
    valid_rows = silver_df.count()

    # La cuarentena puede no existir todavía si nunca hubo una fila
    # inválida en esa fuente (quarantine_and_write igual la escribe
    # vacía, así que en la práctica siempre existe — pero se cubre el
    # caso por robustez, ej. primera corrida en un entorno nuevo).
    try:
        quarantine_df = spark.read.parquet(QUARANTINE_PATHS[source_name])
        quarantined_rows = quarantine_df.count()
    except Exception:
        logger.warning(
            "No se encontró cuarentena para %s (asumiendo 0 filas).", source_name
        )
        quarantined_rows = 0

    total_rows = valid_rows + quarantined_rows
    pass_rate_records = (valid_rows / total_rows) if total_rows else 1.0

    # Detalle adicional: expectativas de GE sobre el Silver YA filtrado
    # (post-cuarentena) — debería acercarse a 100% de reglas OK.
    ge_summary = run_expectations(silver_df, source_name)

    logger.info(
        "%s: %s/%s registros válidos (%.1f%%), GE %s/%s expectativas OK",
        source_name,
        valid_rows,
        total_rows,
        pass_rate_records * 100,
        ge_summary["passed"],
        ge_summary["total"],
    )

    return Row(
        source=source_name,
        valid_rows=valid_rows,
        quarantined_rows=quarantined_rows,
        total_rows=total_rows,
        pass_rate_records=pass_rate_records,
        ge_expectations_total=ge_summary["total"],
        ge_expectations_passed=ge_summary["passed"],
        ge_pass_rate_rules=ge_summary["pass_rate"],
    )


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        rows = [report_for_source(spark, source) for source in SILVER_PATHS]

        run_ts = F.current_timestamp()
        report_df = spark.createDataFrame(rows).withColumn("run_timestamp", run_ts)
        # Reordenar columnas para que coincidan con REPORT_SCHEMA (createDataFrame
        # a partir de Row no garantiza el orden de declaración de campos).
        report_df = report_df.select(*[f.name for f in REPORT_SCHEMA.fields])

        jdbc_url, jdbc_properties = build_jdbc_url()
        logger.info("Escribiendo reporte de calidad en: %s", QUALITY_METRICS_TABLE)
        report_df.write.mode("append").jdbc(
            url=jdbc_url, table=QUALITY_METRICS_TABLE, properties=jdbc_properties
        )
        logger.info(
            "Reporte de calidad (t047) escrito: %s filas (una por fuente).",
            report_df.count(),
        )
    except Exception:
        status = "failed"
        logger.exception("Falló la generación del reporte de calidad (t047).")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("quality_report", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

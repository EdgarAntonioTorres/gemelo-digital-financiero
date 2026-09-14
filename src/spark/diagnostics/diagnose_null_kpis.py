"""
Diagnóstico — nulos en FACT_KPI_PERFIL y en las columnas crudas que lo
alimentan (Sesión 26, seguimiento a verify_gold.py, chequeo 3).

Autocontenido (mismo patrón que verify_silver.py/verify_gold.py):
rutas escritas directamente aquí, SIN importar de
src/spark/transformations/ — evita el ModuleNotFoundError de
silver_transformations al importar build_silver_master.py desde otra
carpeta (Bitácora, Sesión 26).

No modifica nada, solo cuenta. Uso:
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/diagnose_null_kpis.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.

Ubicación: src/spark/diagnostics/diagnose_null_kpis.py
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, when

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SILVER_MASTER = "s3a://silver/master/"
GOLD_FACT_KPI_PERFIL = "s3a://gold/fact_kpi_perfil/"
DIM_PATHS = {
    "credit_risk": "s3a://silver/dim_perfil_credit_risk/",
    "loan_default": "s3a://silver/dim_perfil_loan_default/",
    "personal_finance_tracker": "s3a://silver/dim_perfil_pft/",
}


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
        SparkSession.builder.appName("diagnose_null_kpis")
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


def null_counts(df, label: str) -> None:
    logger.info("--- Nulos por columna: %s ---", label)
    exprs = [count(when(col(c).isNull(), c)).alias(c) for c in df.columns]
    df.select(exprs).show(truncate=False)


def main() -> None:
    spark = None
    try:
        spark = build_spark_session()

        df_fact = spark.read.parquet(GOLD_FACT_KPI_PERFIL)
        logger.info("--- Filas con irfi nulo, por fuente ---")
        df_fact.filter("irfi IS NULL").groupBy("fuente").count().show()

        df_master = spark.read.parquet(SILVER_MASTER)
        logger.info("--- Nulos en debt_to_income_norm del maestro, por fuente ---")
        df_master.groupBy("fuente").agg(
            count(when(col("debt_to_income_norm").isNull(), True)).alias(
                "debt_to_income_norm_nulls"
            )
        ).show()

        null_counts(
            spark.read.parquet(DIM_PATHS["credit_risk"]), "dim_perfil_credit_risk"
        )
        null_counts(
            spark.read.parquet(DIM_PATHS["loan_default"]), "dim_perfil_loan_default"
        )
        null_counts(
            spark.read.parquet(DIM_PATHS["personal_finance_tracker"]), "dim_perfil_pft"
        )
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

"""
Silver — Loan Default Dataset

Encadena las transformaciones puras de `silver_transformations.py`
(tipado, deduplicación, nulos de `dtir1`, outliers de `income`)
sobre la partición completa de Bronze, y escribe el
resultado a Silver. Este es el ÚNICO lugar donde Silver se escribe de
verdad a MinIO para esta fuente — las funciones en
`silver_transformations.py` son puras y no tocan disco (ver docstring
de ese módulo).

Orden de las transformaciones (deliberado):
  1. apply_typing()            — ya cerrado.
  2. deduplicate()              —. Antes que nulos/outliers: si no,
     una fila duplicada con `dtir1` nulo se imputaría dos veces con
     valores potencialmente distintos según el orden de ejecución.
  3. impute_dtir1_by_group()    —.
  4. cap_income_outliers()      — , sobre `income`.

No incluye (unificación de esquema) — eso ocurre después, en
`build_silver_master.py`, una vez que las 3 fuentes ya están limpias
por separado.

Uso (dentro del contenedor de Airflow, mismo patrón que los scripts
de ingesta — ver docstring de `ingest_loan_default.py`):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/transformations/build_silver_loan_default.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY (mismas que los scripts de ingesta Bronze).
"""

import logging
import os
import sys
import time

from pyspark.sql import SparkSession

from silver_transformations import (
    apply_typing,
    cap_income_outliers,
    deduplicate,
    impute_dtir1_by_group,
)

BRONZE_PATH = "s3a://bronze/loan_default/"
SILVER_PATH = "s3a://silver/loan_default/"
SOURCE_NAME = "loan_default"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_silver_loan_default")


def get_required_env(name: str) -> str:
    """Mismo patrón que en los scripts de ingesta Bronze — falla
    explícita y temprana si falta una variable de MinIO."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Misma configuración S3A que los scripts de ingesta, más
    mergeSchema=true para leer el histórico completo de Bronze (ver
    smoke_test_bronze.py — conviven particiones con y sin las 3
    columnas de trazabilidad agregadas después)."""
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("build_silver_loan_default")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.sql.parquet.mergeSchema", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def main() -> None:
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo Bronze completo desde: %s", BRONZE_PATH)
        df = spark.read.parquet(BRONZE_PATH)
        row_count_bronze = df.count()
        logger.info("Filas leídas de Bronze: %s", row_count_bronze)

        df = apply_typing(df, SOURCE_NAME)
        df = deduplicate(df)
        row_count_deduped = df.count()
        logger.info(
            "Tras deduplicar: %s filas (%s duplicados removidos)",
            row_count_deduped,
            row_count_bronze - row_count_deduped,
        )

        df = impute_dtir1_by_group(df, group_col="loan_type", target_col="dtir1")
        imputed_count = df.filter(df.dtir1_imputed_flag).count()
        logger.info("dtir1 imputados: %s filas", imputed_count)

        df = cap_income_outliers(df, income_col="income", percentile=0.99)
        capped_count = df.filter(df.income_outlier_flag).count()
        logger.info("Outliers de income recortados: %s filas", capped_count)

        logger.info("Escribiendo Silver en: %s", SILVER_PATH)
        df.write.mode("overwrite").option("compression", "snappy").parquet(SILVER_PATH)
        logger.info(
            "Silver de loan_default completado: %s filas escritas.", row_count_deduped
        )
    except Exception:
        logger.exception("Falló la construcción de Silver para loan_default.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

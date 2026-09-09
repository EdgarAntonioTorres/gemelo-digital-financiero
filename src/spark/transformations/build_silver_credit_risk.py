"""
Silver — Credit Risk Dataset

Mismo patrón que `build_silver_loan_default.py`: encadena
(tipado) + (deduplicación) + (outliers de `person_income`)
y escribe a Silver.

No incluye (Credit Risk no tiene nulos en `dtir1` — esa columna
no existe en esta fuente) ni (unificación — ver
`build_silver_master.py`).

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/transformations/build_silver_credit_risk.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import SparkSession

from silver_transformations import apply_typing, cap_income_outliers, deduplicate

BRONZE_PATH = "s3a://bronze/credit_risk/"
SILVER_PATH = "s3a://silver/credit_risk/"
SOURCE_NAME = "credit_risk"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_silver_credit_risk")


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
        SparkSession.builder.appName("build_silver_credit_risk")
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

        df = cap_income_outliers(df, income_col="person_income", percentile=0.99)
        capped_count = df.filter(df.person_income_outlier_flag).count()
        logger.info("Outliers de person_income recortados: %s filas", capped_count)

        logger.info("Escribiendo Silver en: %s", SILVER_PATH)
        df.write.mode("overwrite").option("compression", "snappy").parquet(SILVER_PATH)
        logger.info(
            "Silver de credit_risk completado: %s filas escritas.", row_count_deduped
        )
    except Exception:
        logger.exception("Falló la construcción de Silver para credit_risk.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

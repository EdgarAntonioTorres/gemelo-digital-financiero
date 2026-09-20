"""
Silver — Personal Finance Tracker Dataset

Mismo patrón que las otras 2 fuentes, más un paso adicional exclusivo
de esta fuente: (segmentación <30 años + `age` sintética),
ya que esta es la única de las 3 sin edad nativa.

Orden de las transformaciones:
  1. apply_typing()            — .
  2. deduplicate()              — .
  3. derive_synthetic_age()     — . Después de deduplicar (no
     antes): si se derivara la edad sintética sobre filas duplicadas,
     el índice de fila usado como semilla de ruido (t107) cambiaría
     según cuáles duplicados sobrevivan, dando resultados no
     reproducibles entre corridas.

No incluye (esta fuente no tiene `dtir1`) ni1 (Contexto
Maestro §5.2 no documenta un outlier de `monthly_income` en esta
fuente — solo en `person_income`/`income` de las otras 2).

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/transformations/build_silver_personal_finance_tracker.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import SparkSession

from silver_transformations import apply_typing, deduplicate, derive_synthetic_age
from quarantine import quarantine_and_write
from pipeline_timing import log_execution

BRONZE_PATH = "s3a://bronze/personal_finance_tracker/"
SILVER_PATH = "s3a://silver/personal_finance_tracker/"
SOURCE_NAME = "personal_finance_tracker"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_silver_personal_finance_tracker")


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
        SparkSession.builder.appName("build_silver_personal_finance_tracker")
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
    status = "success"
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

        df = derive_synthetic_age(df)
        segment_counts = df.groupBy("segmento").count().collect()
        logger.info(
            "Segmentación: %s",
            {row["segmento"]: row["count"] for row in segment_counts},
        )

        # t046 (Fase 3): gate de calidad — separa filas inválidas según
        # expectations_config.py, las escribe a cuarentena y devuelve
        # solo las válidas. No detiene la corrida si hay cuarentena.
        df = quarantine_and_write(df, SOURCE_NAME)

        row_count_final = df.count()
        logger.info("Escribiendo Silver en: %s", SILVER_PATH)
        df.write.mode("overwrite").option("compression", "snappy").parquet(SILVER_PATH)
        logger.info(
            "Silver de personal_finance_tracker completado: %s filas escritas "
            "(%s pasaron deduplicación, %s en cuarentena por t046).",
            row_count_final,
            row_count_deduped,
            row_count_deduped - row_count_final,
        )
    except Exception:
        status = "failed"
        logger.exception(
            "Falló la construcción de Silver para personal_finance_tracker."
        )
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("build_silver_personal_finance_tracker", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

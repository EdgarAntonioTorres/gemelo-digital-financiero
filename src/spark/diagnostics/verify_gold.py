"""
Verificación rápida de FACT_KPI_PERFIL (Gold) — Sesión 26.

Mismo espíritu y mismo patrón que verify_silver.py: NO importa nada de
src/spark/transformations/ (ver Bitácora, Sesión 26, sobre el
ModuleNotFoundError que causó importar calculate_kpis.py/
build_silver_master.py desde otra carpeta) — rutas escritas
directamente aquí, autocontenido.

No transforma nada, solo LEE lo que ya escribió calculate_kpis.py y
confirma con evidencia real (no solo "corrió sin error") que:
  1. IRFI/ICA caen en [0, 1].
  2. irfi_proxy_flag es False SOLO para credit_risk, True para el resto.
  3. Cero nulos en irfi/ica.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/verify_gold.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.

Ubicación: src/spark/diagnostics/verify_gold.py
"""

import logging
import os

from pyspark.sql import SparkSession

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

GOLD_FACT_KPI_PERFIL = "s3a://gold/fact_kpi_perfil/"


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
        SparkSession.builder.appName("verify_gold")
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
    try:
        spark = build_spark_session()
        df_fact = spark.read.parquet(GOLD_FACT_KPI_PERFIL)

        logger.info("--- 1. Rango de IRFI/ICA (esperado: [0, 1]) ---")
        df_fact.selectExpr(
            "min(irfi) as irfi_min",
            "max(irfi) as irfi_max",
            "min(ica) as ica_min",
            "max(ica) as ica_max",
        ).show()

        logger.info(
            "--- 2. irfi_proxy_flag por fuente (esperado: credit_risk=False, resto=True) ---"
        )
        df_fact.groupBy("fuente", "irfi_proxy_flag").count().show()

        logger.info("--- 3. Filas con irfi/ica nulo (esperado: 0) ---")
        null_count = df_fact.filter("irfi IS NULL OR ica IS NULL").count()
        logger.info("Filas con nulos: %s", null_count)
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

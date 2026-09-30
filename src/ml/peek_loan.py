"""
Script DESECHABLE de diagnóstico — investiga si
`rate_of_interest_imputed_flag` es fuga de datos real (el patrón de
nulos se generó usando información posterior al desenlace) o un proxy
indirecto de `loan_type` (variable omitida, no fuga literal).

Hallazgo que motiva esto (Sesión 32): al exponer el flag como feature
explícita, AUC subió a ~0.97-0.996 (más alto que con el valor crudo
imputado) y el flag concentra 92.8% de la importancia en XGBoost — un
solo booleano "resolviendo" el riesgo de crédito es una señal de alerta
seria, no un resultado a celebrar.

Lee TODO de la MISMA tabla (s3a://silver/loan_default/), sin ningún
join — evita el riesgo de record_id desincronizado (regla 4/9 del
glosario) porque `Status` (target crudo), `loan_type` y
`rate_of_interest_imputed_flag` ya conviven en esa tabla, previo a
cualquier unificación.

Qué mira:
  1. Tasa de default (`Status`) por `rate_of_interest_imputed_flag`
     (confirma el hallazgo previo, sin depender de gold/silver/master).
  2. Cómo se distribuye `rate_of_interest_imputed_flag` DENTRO de cada
     `loan_type` — si el flag=True se concentra casi todo en un solo
     loan_type, es la pista de que es un proxy, no fuga literal.
  3. Tasa de default por `loan_type` SOLO — si un loan_type ya explica
     la mayoría de la diferencia por sí solo, confirma la hipótesis de
     "variable omitida" en vez de fuga.
  4. Tasa de default por (`loan_type`, `rate_of_interest_imputed_flag`)
     cruzados — el test decisivo: si DENTRO del mismo loan_type el
     flag sigue marcando una diferencia enorme de default, eso apunta
     a fuga real, no a loan_type.

Uso:
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/peek_imputation_leakage.py
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import avg, col, count

SILVER_LOAN_DEFAULT_PATH = "s3a://silver/loan_default/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("peek_imputation_leakage")


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    spark = (
        SparkSession.builder.appName("peek_imputation_leakage")
        .config("spark.hadoop.fs.s3a.endpoint", get_required_env("MINIO_ENDPOINT"))
        .config("spark.hadoop.fs.s3a.access.key", get_required_env("MINIO_ACCESS_KEY"))
        .config("spark.hadoop.fs.s3a.secret.key", get_required_env("MINIO_SECRET_KEY"))
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
        df = spark.read.parquet(SILVER_LOAN_DEFAULT_PATH)
        df = df.withColumn("status_double", col("Status").cast("double"))

        logger.info("--- 1. Tasa de default por rate_of_interest_imputed_flag ---")
        df.groupBy("rate_of_interest_imputed_flag").agg(
            count("*").alias("filas"), avg("status_double").alias("tasa_default")
        ).show(truncate=False)

        logger.info(
            "--- 2. Distribución de rate_of_interest_imputed_flag DENTRO de "
            "cada loan_type ---"
        )
        df.groupBy("loan_type", "rate_of_interest_imputed_flag").agg(
            count("*").alias("filas")
        ).orderBy("loan_type", "rate_of_interest_imputed_flag").show(50, truncate=False)

        logger.info("--- 3. Tasa de default por loan_type (solo) ---")
        df.groupBy("loan_type").agg(
            count("*").alias("filas"), avg("status_double").alias("tasa_default")
        ).orderBy("loan_type").show(truncate=False)

        logger.info(
            "--- 4. Tasa de default por (loan_type, "
            "rate_of_interest_imputed_flag) cruzados — TEST DECISIVO ---"
        )
        df.groupBy("loan_type", "rate_of_interest_imputed_flag").agg(
            count("*").alias("filas"), avg("status_double").alias("tasa_default")
        ).orderBy("loan_type", "rate_of_interest_imputed_flag").show(50, truncate=False)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

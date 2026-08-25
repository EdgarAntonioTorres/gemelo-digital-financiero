"""
Verificación puntual de UNA partición de Bronze (diagnóstico).

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/verificar_particion_hoy.py

Lee directamente la partición de HOY (sin pasar por el resto del
histórico de Bronze) para confirmar si el DAG realmente escribió las
columnas de trazabilidad ahí, aislado del problema de mergeSchema al
leer todo el histórico junto.
"""

import os

from pyspark.sql import SparkSession

# Mismas rutas de Bronze que usan los scripts de ingesta.
PARTICIONES_DE_HOY = {
    "loan_default": "s3a://bronze/loan_default/ingestion_date=2026-08-25/",
    "credit_risk": "s3a://bronze/credit_risk/ingestion_date=2026-08-25/",
    "personal_finance_tracker": (
        "s3a://bronze/personal_finance_tracker/ingestion_date=2026-08-25/"
    ),
}


def build_spark_session() -> SparkSession:
    spark = (
        SparkSession.builder.appName("verificar_particion_hoy")
        .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
        .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
        .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def main() -> None:
    spark = build_spark_session()
    for nombre, ruta in PARTICIONES_DE_HOY.items():
        print(f"\n=== {nombre} ({ruta}) ===")
        df = spark.read.parquet(ruta)
        df.select("ingestion_timestamp", "source_file", "dag_run_id").distinct().show(
            truncate=False
        )
    spark.stop()


if __name__ == "__main__":
    main()

"""
Utilidad de diagnóstico (insumo para diseñar t038, no es t038 en sí):
imprime el schema real (columna -> tipo inferido por Spark) de cada
fuente en Bronze, leyendo solo la partición de HOY para no pagar el
costo de leer 5 días de historial.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \
        /opt/airflow/src/spark/dump_schema_bronze.py
"""

import os

from pyspark.sql import SparkSession

BRONZE_SOURCES = {
    "loan_default": "s3a://bronze/loan_default/",
    "credit_risk": "s3a://bronze/credit_risk/",
    "personal_finance_tracker": "s3a://bronze/personal_finance_tracker/",
}


def build_spark_session() -> SparkSession:
    spark = (
        SparkSession.builder.appName("dump_schema_bronze")
        .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
        .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
        .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.sql.parquet.mergeSchema", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def main() -> None:
    spark = build_spark_session()
    try:
        for nombre, path in BRONZE_SOURCES.items():
            print(f"\n=== {nombre} ({path}) ===")
            df = spark.read.parquet(path)
            for campo in df.schema.fields:
                print(f"  {campo.name}: {campo.dataType.simpleString()}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

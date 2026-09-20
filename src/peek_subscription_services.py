"""
Diagnóstico puntual y desechable: ¿subscription_services es un monto
en USD o ya un ratio/porcentaje? Necesario para decidir la fórmula de
t056 con datos reales, no con una suposición.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/peek_subscription_services.py
"""

import os

from pyspark.sql import SparkSession

PATH = "s3a://silver/dim_comportamiento_pft/"


def build_spark_session() -> SparkSession:
    spark = (
        SparkSession.builder.appName("peek_subscription_services")
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
    try:
        df = spark.read.parquet(PATH)

        print("\n=== Tipo de dato ===")
        for field in df.schema.fields:
            if field.name == "subscription_services":
                print(f"  {field.name}: {field.dataType.simpleString()}")

        print("\n=== 15 filas de muestra: subscription_services vs. monthly_income ===")
        df.select("subscription_services", "monthly_income").show(15, truncate=False)

        print("\n=== Estadísticas descriptivas ===")
        df.select("subscription_services").describe().show()
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

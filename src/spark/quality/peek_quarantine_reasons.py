"""
Script desechable — inspecciona `_failure_reasons` de la cuarentena
escrita por `quarantine_and_write()`, para saber CUÁL regla de
`expectations_config.py` está fallando antes de asumir nada. Mismo
espíritu que `peek_subscription_services.py` (Sesión 28): confirmar
con datos reales antes de escribir una conclusión en la Bitácora.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/quality/peek_quarantine_reasons.py <fuente>

    <fuente> = loan_default | credit_risk | personal_finance_tracker
"""

import os
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from quarantine import QUARANTINE_PATHS


def build_spark_session() -> SparkSession:
    spark = (
        SparkSession.builder.appName("peek_quarantine_reasons")
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
    if len(sys.argv) != 2 or sys.argv[1] not in QUARANTINE_PATHS:
        print(f"Uso: peek_quarantine_reasons.py <{'|'.join(QUARANTINE_PATHS)}>")
        sys.exit(1)

    source_name = sys.argv[1]
    path = QUARANTINE_PATHS[source_name]

    spark = build_spark_session()
    try:
        df = spark.read.parquet(path)
        total = df.count()
        print(f"\n=== {source_name}: {total} filas en cuarentena ===\n")

        # Una fila puede fallar por más de una regla a la vez — explode
        # cuenta cada razón por separado, así que la suma puede superar
        # `total` (eso es esperado, no un bug).
        (
            df.select(F.explode("_failure_reasons").alias("razon"))
            .groupBy("razon")
            .count()
            .orderBy(F.col("count").desc())
            .show(truncate=False)
        )

        print("Muestra de 10 filas en cuarentena (para inspección manual):")
        df.select(
            "record_id" if "record_id" in df.columns else df.columns[0],
            "_failure_reasons",
        ).show(10, truncate=False)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

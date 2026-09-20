"""
Gold → PostgreSQL — Carga de FACT_COMPORTAMIENTO a postgres-dw

Hallazgo de Sesión 30 (al construir `t059`): `build_fact_comportamiento.py`
(`t054`-`t057`) escribe a `s3a://gold/fact_comportamiento/` en Parquet,
pero a diferencia de `FACT_KPI_PERFIL` (`t051`, `load_gold_postgres.py`),
nunca tuvo su loader — nadie lo cargó a Postgres. El dashboard
(`t059`) lo necesita en SQL, igual que `t060` necesita `FACT_KPI_PERFIL`.

Mismo patrón exacto que `load_gold_postgres.py`: JDBC nativo de Spark,
coalesce antes de escribir, mismo directorio `loaders/` (no
`transformations/` ni `diagnostics/` — ver docstring de ese módulo
para el porqué de la convención).

Modo de escritura — Fase 1 (esta es la PRIMERA carga de esta tabla,
a diferencia de `FACT_KPI_PERFIL` que ya iba en Fase 2 cuando se
escribió su loader): `mode="overwrite"` SIN `truncate` — Spark crea
la tabla con tipos inferidos porque `gold.fact_comportamiento` no
existe todavía en `init-dw-schemas.sql`. Si más adelante se le agrega
una PK explícita (`record_id`) a `init-dw-schemas.sql`, este script
puede pasar a `truncate=true` como hizo `load_gold_postgres.py` en su
Fase 2 — no es necesario para que el dashboard funcione hoy.

Lee:
    s3a://gold/fact_comportamiento/   (Parquet, build_fact_comportamiento.py)

Escribe:
    postgres-dw / gemelo_digital / gold.fact_comportamiento

Uso (dentro del contenedor de Airflow, después de build_fact_comportamiento.py):
    spark-submit \\
        --packages org.apache.hadoop:hadoop-aws:3.3.4,org.postgresql:postgresql:42.7.3 \\
        /opt/airflow/src/spark/loaders/load_fact_comportamiento_postgres.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY, DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER,
DW_POSTGRES_PASSWORD (mismas 4 ya declaradas en docker-compose.yml).
"""

import logging
import os
import sys
import time

from pyspark.sql import DataFrame, SparkSession

FACT_COMPORTAMIENTO_PATH = "s3a://gold/fact_comportamiento/"
TARGET_TABLE = "gold.fact_comportamiento"
JDBC_DRIVER = "org.postgresql.Driver"

# Mismos valores que load_gold_postgres.py, por consistencia — esta
# tabla es mucho más chica (3,000 filas, solo PFT), así que no hay
# presión real de performance, pero no hay razón para inventar otros
# números sin motivo.
N_PARTITIONS_JDBC = 4
JDBC_BATCH_SIZE = 5000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("load_fact_comportamiento_postgres")


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
        SparkSession.builder.appName("load_fact_comportamiento_postgres")
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


def build_jdbc_url() -> str:
    host = get_required_env("DW_POSTGRES_HOST")
    db = get_required_env("DW_POSTGRES_DB")
    return f"jdbc:postgresql://{host}:5432/{db}"


def write_to_postgres(df: DataFrame) -> None:
    jdbc_url = build_jdbc_url()
    jdbc_user = get_required_env("DW_POSTGRES_USER")
    jdbc_password = get_required_env("DW_POSTGRES_PASSWORD")

    original_partitions = df.rdd.getNumPartitions()
    df_compact = df.coalesce(N_PARTITIONS_JDBC)
    logger.info(
        "Compactando particiones antes de escribir: %s -> %s",
        original_partitions,
        df_compact.rdd.getNumPartitions(),
    )

    # Fase 1 (ver docstring): sin truncate, tabla nueva — Spark hace
    # DROP + CREATE con tipos inferidos.
    (
        df_compact.write.format("jdbc")
        .option("url", jdbc_url)
        .option("dbtable", TARGET_TABLE)
        .option("user", jdbc_user)
        .option("password", jdbc_password)
        .option("driver", JDBC_DRIVER)
        .option("batchsize", JDBC_BATCH_SIZE)
        .mode("overwrite")
        .save()
    )


def main() -> None:
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo FACT_COMPORTAMIENTO desde: %s", FACT_COMPORTAMIENTO_PATH)
        df_fact = spark.read.parquet(FACT_COMPORTAMIENTO_PATH)

        total_rows = df_fact.count()
        logger.info("Filas leídas de Gold (Parquet): %s", total_rows)
        logger.info("Esquema inferido:")
        df_fact.printSchema()

        logger.info("Escribiendo %s en postgres-dw...", TARGET_TABLE)
        write_to_postgres(df_fact)
        logger.info(
            "Carga completada: %s filas escritas en %s.", total_rows, TARGET_TABLE
        )
    except Exception:
        logger.exception("Falló la carga de FACT_COMPORTAMIENTO a PostgreSQL.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

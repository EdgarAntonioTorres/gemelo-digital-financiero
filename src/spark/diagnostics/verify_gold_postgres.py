"""
Verificación de gold.fact_kpi_perfil en PostgreSQL — Sesión 27,
seguimiento (src/spark/loaders/load_gold_postgres.py).

Mismo espíritu que verify_gold.py (que valida el Parquet en
s3a://gold/fact_kpi_perfil/): NO importa nada de
src/spark/transformations/ ni de src/spark/loaders/ (convención §7.3
del Contexto Maestro) — rutas/config escritas directamente aquí,
autocontenido.

Diferencia con verify_gold.py: ese script valida que los VALORES del
KPI sean correctos (fórmula bien aplicada sobre el Parquet). Este
valida que la CARGA a Postgres no haya introducido ningún problema en
el camino — compara contra el propio Parquet de origen en vez de
asumir un número fijo de filas, así el chequeo sigue siendo válido
aunque cambie el volumen de datos en corridas futuras. Cubre:
  1. El conteo de filas en Postgres coincide con el Parquet de origen
     (ninguna fila se perdió/duplicó en el TRUNCATE + INSERT del loader).
  2. record_id es único en Postgres (evidencia de que la PK realmente
     está activa, no solo declarada en el DDL).
  3. IRFI/ICA caen en [0, 1] (mismo chequeo que verify_gold.py,
     confirma que el tipo double sobrevivió el viaje por JDBC sin
     truncar/redondear).
  4. irfi_proxy_flag es False SOLO para credit_risk, True para el
     resto (mismo chequeo que verify_gold.py, confirma que el tipo
     boolean sobrevivió el viaje por JDBC).
  5. Cero nulos en irfi/ica (mismo chequeo que verify_gold.py).

Uso (dentro del contenedor de Airflow, después de correr
load_gold_postgres.py):
    spark-submit \\
        --packages org.apache.hadoop:hadoop-aws:3.3.4,org.postgresql:postgresql:42.7.3 \\
        /opt/airflow/src/spark/diagnostics/verify_gold_postgres.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY (lectura del Parquet de origen, para el chequeo 1) +
DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER, DW_POSTGRES_PASSWORD
(lectura de Postgres) — mismas 4 ya declaradas en x-airflow-common-env
del docker-compose.yml, ver load_gold_postgres.py.

Ubicación: src/spark/diagnostics/verify_gold_postgres.py
"""

import logging
import os

from pyspark.sql import DataFrame, SparkSession

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

GOLD_FACT_KPI_PARQUET = "s3a://gold/fact_kpi_perfil/"
TARGET_TABLE = "gold.fact_kpi_perfil"
JDBC_DRIVER = "org.postgresql.Driver"


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Config S3A (para leer el Parquet de origen, chequeo 1) — mismo
    patrón que el resto de src/spark/diagnostics/. La lectura de
    Postgres no necesita config adicional en la sesión, el driver JDBC
    se resuelve vía --packages (ver docstring del módulo)."""
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("verify_gold_postgres")
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
    # Puerto interno de postgres-dw en la red de Docker Compose (no el
    # 5433 publicado al host) — mismo criterio que load_gold_postgres.py.
    return f"jdbc:postgresql://{host}:5432/{db}"


def read_postgres_fact_kpi(spark: SparkSession) -> DataFrame:
    jdbc_url = build_jdbc_url()
    jdbc_user = get_required_env("DW_POSTGRES_USER")
    jdbc_password = get_required_env("DW_POSTGRES_PASSWORD")

    return (
        spark.read.format("jdbc")
        .option("url", jdbc_url)
        .option("dbtable", TARGET_TABLE)
        .option("user", jdbc_user)
        .option("password", jdbc_password)
        .option("driver", JDBC_DRIVER)
        .load()
    )


def check_row_count_parity(
    spark: SparkSession, df_postgres: DataFrame, fallos: list[str]
) -> None:
    """1. El conteo en Postgres debe coincidir EXACTO con el Parquet de
    origen — cualquier diferencia significa filas perdidas o
    duplicadas durante la carga."""
    df_parquet = spark.read.parquet(GOLD_FACT_KPI_PARQUET)
    filas_parquet = df_parquet.count()
    filas_postgres = df_postgres.count()

    if filas_parquet != filas_postgres:
        fallos.append(
            f"Conteo no coincide: Parquet tiene {filas_parquet} filas, "
            f"Postgres tiene {filas_postgres}."
        )
    logger.info(
        "Chequeo conteo de filas: Parquet=%s, Postgres=%s",
        filas_parquet,
        filas_postgres,
    )


def check_record_id_unique(df_postgres: DataFrame, fallos: list[str]) -> None:
    """2. record_id único en Postgres — evidencia de que la PK
    (pk_fact_kpi_perfil, ver config/init-dw-schemas.sql) está
    realmente activa, no solo declarada."""
    total = df_postgres.count()
    distintos = df_postgres.select("record_id").distinct().count()
    if total != distintos:
        fallos.append(
            f"record_id NO es único en Postgres: {total} filas vs. "
            f"{distintos} valores distintos ({total - distintos} colisiones) "
            "— revisar si la PK sigue activa en gold.fact_kpi_perfil."
        )
    logger.info(
        "Chequeo record_id único (Postgres): %s filas, %s distintos",
        total,
        distintos,
    )


def check_irfi_ica_range(df_postgres: DataFrame, fallos: list[str]) -> None:
    """3. IRFI/ICA deben seguir en [0, 1] tras el viaje por JDBC."""
    row = df_postgres.selectExpr(
        "min(irfi) as irfi_min",
        "max(irfi) as irfi_max",
        "min(ica) as ica_min",
        "max(ica) as ica_max",
    ).collect()[0]

    if row["irfi_min"] < 0 or row["irfi_max"] > 1:
        fallos.append(
            f"irfi fuera de [0, 1] en Postgres: min={row['irfi_min']}, "
            f"max={row['irfi_max']}."
        )
    if row["ica_min"] < 0 or row["ica_max"] > 1:
        fallos.append(
            f"ica fuera de [0, 1] en Postgres: min={row['ica_min']}, "
            f"max={row['ica_max']}."
        )
    logger.info(
        "Chequeo rango IRFI/ICA (Postgres): irfi=[%.4f, %.4f], ica=[%.4f, %.4f]",
        row["irfi_min"],
        row["irfi_max"],
        row["ica_min"],
        row["ica_max"],
    )


def check_proxy_flag_by_source(df_postgres: DataFrame, fallos: list[str]) -> None:
    """4. irfi_proxy_flag debe ser False SOLO para credit_risk, True
    para loan_default/personal_finance_tracker (Contexto Maestro
    §6.2.1) — confirma que el tipo boolean sobrevivió el viaje JDBC."""
    conteos = df_postgres.groupBy("fuente", "irfi_proxy_flag").count().collect()
    for r in conteos:
        logger.info(
            "  fuente=%s, irfi_proxy_flag=%s -> %s filas",
            r["fuente"],
            r["irfi_proxy_flag"],
            r["count"],
        )
        es_credit_risk = r["fuente"] == "credit_risk"
        flag_inesperado = (es_credit_risk and r["irfi_proxy_flag"] is not False) or (
            not es_credit_risk and r["irfi_proxy_flag"] is not True
        )
        if flag_inesperado:
            fallos.append(
                f"irfi_proxy_flag inesperado para fuente={r['fuente']}: "
                f"{r['irfi_proxy_flag']} ({r['count']} filas)."
            )


def check_no_nulls_irfi_ica(df_postgres: DataFrame, fallos: list[str]) -> None:
    """5. Cero nulos en irfi/ica en Postgres."""
    null_count = df_postgres.filter("irfi IS NULL OR ica IS NULL").count()
    if null_count > 0:
        fallos.append(f"{null_count} filas con irfi/ica nulo en Postgres.")
    logger.info("Chequeo nulos irfi/ica (Postgres): %s", null_count)


def main() -> None:
    spark = None
    try:
        spark = build_spark_session()
        fallos: list[str] = []

        logger.info("Leyendo %s desde postgres-dw...", TARGET_TABLE)
        df_postgres = read_postgres_fact_kpi(spark)
        df_postgres.cache()

        check_row_count_parity(spark, df_postgres, fallos)
        check_record_id_unique(df_postgres, fallos)
        check_irfi_ica_range(df_postgres, fallos)
        check_proxy_flag_by_source(df_postgres, fallos)
        check_no_nulls_irfi_ica(df_postgres, fallos)

        logger.info("=== Resumen verify_gold_postgres ===")
        if fallos:
            for f in fallos:
                logger.warning("FALLO: %s", f)
            raise AssertionError(
                f"verify_gold_postgres encontró {len(fallos)} problema(s):\n"
                + "\n".join(fallos)
            )

        logger.info(
            "verify_gold_postgres OK — conteo coincide con el Parquet de "
            "origen, record_id único (PK activa), IRFI/ICA en [0,1], "
            "irfi_proxy_flag consistente por fuente, cero nulos."
        )
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

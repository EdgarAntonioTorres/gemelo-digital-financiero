"""
Smoke test de Silver — diagnóstico posterior a correr los
4 scripts de build_silver_*.py.

Mismo espíritu que smoke_test_bronze.py: no transforma nada, solo LEE
lo que ya se escribió a Silver y confirma que la estructura es la
esperada. No repite los conteos que build_silver_*.py ya loguea
(filas leídas, duplicados removidos, etc.) — se enfoca en lo que esos
logs NO cubren: calidad estructural del resultado final.

Chequeos:
  1. `record_id` es único en el dataset maestro (sin colisión de
     llave sintética entre o dentro de fuentes).
  2. `record_id` respeta el formato esperado por fuente (prefijo +
     5 dígitos) — LD_00001, CR_00001, PFT_00001.
  3. Cero nulos residuales en `dtir1` de Silver/loan_default tras la
     imputación (si queda alguno, algo falló en el fallback
     de impute_dtir1_by_group()).
  4. `age` en Silver/personal_finance_tracker cae dentro del rango
     esperado por segmento (20-29 early_career, 30-60 established) —
     confirma que el clip de derive_synthetic_age() funcionó.
  5. `default_flag_unificada` es NULL únicamente para
     fuente='personal_finance_tracker' en el maestro (
     §5.2: PFT no tiene equivalente real de default).

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/verify_silver.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.

Ubicación: src/spark/diagnostics/verify_silver.py
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

SILVER_LOAN_DEFAULT = "s3a://silver/loan_default/"
SILVER_CREDIT_RISK = "s3a://silver/credit_risk/"
SILVER_PFT = "s3a://silver/personal_finance_tracker/"
SILVER_MASTER = "s3a://silver/master/"

# prefijo esperado -> fuente (para el chequeo de formato de record_id)
RECORD_ID_PREFIX_BY_SOURCE = {
    "loan_default": "LD",
    "credit_risk": "CR",
    "personal_finance_tracker": "PFT",
}


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
        SparkSession.builder.appName("verify_silver")
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


def check_record_id_unique(df_master, fallos: list[str]) -> None:
    """1. record_id no debe repetirse en todo el maestro."""
    total = df_master.count()
    distintos = df_master.select("record_id").distinct().count()
    if total != distintos:
        fallos.append(
            f"record_id NO es único: {total} filas vs. {distintos} valores "
            f"distintos ({total - distintos} colisiones)."
        )
    logger.info("Chequeo record_id único: %s filas, %s distintos", total, distintos)


def check_record_id_format(df_master, fallos: list[str]) -> None:
    """2. record_id debe respetar '<PREFIJO>_<5 dígitos>' según fuente."""
    for fuente, prefijo in RECORD_ID_PREFIX_BY_SOURCE.items():
        subset = df_master.filter(col("fuente") == fuente)
        patron = rf"^{prefijo}_\d{{7}}$"
        mal_formados = subset.filter(~col("record_id").rlike(patron)).count()
        if mal_formados > 0:
            fallos.append(
                f"{fuente}: {mal_formados} filas con record_id que no matchea "
                f"el patrón '{prefijo}_0000000'."
            )
        logger.info(
            "Chequeo formato record_id (%s): %s filas mal formadas",
            fuente,
            mal_formados,
        )


def check_dtir1_no_nulls(spark, fallos: list[str]) -> None:
    """3. Silver/loan_default no debe tener nulos residuales en dtir1."""
    df = spark.read.parquet(SILVER_LOAN_DEFAULT)
    nulos = df.filter(col("dtir1").isNull()).count()
    if nulos > 0:
        fallos.append(
            f"loan_default: quedan {nulos} nulos en dtir1 tras la imputación."
        )
    logger.info("Chequeo nulos residuales en dtir1: %s", nulos)


def check_kpi_raw_columns_no_nulls(spark, fallos: list[str]) -> None:
    """6. Sin nulos residuales en las columnas crudas que alimentan los
    proxies de IRFI/ICA (Sesión 26) — rate_of_interest
    (loan_default), loan_int_rate y person_emp_length (credit_risk)."""
    checks = [
        (SILVER_LOAN_DEFAULT, "loan_default", "rate_of_interest"),
        (SILVER_CREDIT_RISK, "credit_risk", "loan_int_rate"),
        (SILVER_CREDIT_RISK, "credit_risk", "person_emp_length"),
    ]
    for path, fuente, columna in checks:
        df = spark.read.parquet(path)
        nulos = df.filter(col(columna).isNull()).count()
        if nulos > 0:
            fallos.append(
                f"{fuente}: quedan {nulos} nulos en {columna} tras la " "imputación."
            )
        logger.info("Chequeo nulos residuales en %s (%s): %s", columna, fuente, nulos)


def check_age_ranges(spark, fallos: list[str]) -> None:
    """4. age sintética (PFT) debe caer en 20-29 (early_career) o
    30-60 (established), sin excepción."""
    df = spark.read.parquet(SILVER_PFT)

    fuera_early = df.filter(
        (col("segmento") == "early_career") & ((col("age") < 20) | (col("age") > 29))
    ).count()
    fuera_established = df.filter(
        (col("segmento") == "established") & ((col("age") < 30) | (col("age") > 60))
    ).count()

    if fuera_early > 0:
        fallos.append(
            f"personal_finance_tracker: {fuera_early} filas early_career con "
            f"age fuera de [20, 29]."
        )
    if fuera_established > 0:
        fallos.append(
            f"personal_finance_tracker: {fuera_established} filas established "
            f"con age fuera de [30, 60]."
        )
    logger.info(
        "Chequeo rangos de age: %s fuera de rango (early_career), "
        "%s fuera de rango (established)",
        fuera_early,
        fuera_established,
    )


def check_default_flag_null_only_pft(df_master, fallos: list[str]) -> None:
    """5. default_flag_unificada debe ser NULL únicamente en PFT."""
    nulos_no_pft = df_master.filter(
        (col("fuente") != "personal_finance_tracker")
        & col("default_flag_unificada").isNull()
    ).count()
    no_nulos_pft = df_master.filter(
        (col("fuente") == "personal_finance_tracker")
        & col("default_flag_unificada").isNotNull()
    ).count()

    if nulos_no_pft > 0:
        fallos.append(
            f"{nulos_no_pft} filas de loan_default/credit_risk con "
            "default_flag_unificada NULL (no debería pasar)."
        )
    if no_nulos_pft > 0:
        fallos.append(
            f"{no_nulos_pft} filas de personal_finance_tracker con "
            "default_flag_unificada NO nulo (debería ser siempre NULL, §5.2)."
        )
    logger.info(
        "Chequeo default_flag_unificada: %s nulos inesperados fuera de PFT, "
        "%s no-nulos inesperados en PFT",
        nulos_no_pft,
        no_nulos_pft,
    )


def main() -> None:
    spark = None
    try:
        spark = build_spark_session()
        fallos: list[str] = []

        logger.info("Leyendo dataset maestro: %s", SILVER_MASTER)
        df_master = spark.read.parquet(SILVER_MASTER)

        check_record_id_unique(df_master, fallos)
        check_record_id_format(df_master, fallos)
        check_dtir1_no_nulls(spark, fallos)
        check_kpi_raw_columns_no_nulls(spark, fallos)
        check_age_ranges(spark, fallos)
        check_default_flag_null_only_pft(df_master, fallos)

        logger.info("=== Resumen verify_silver ===")
        if fallos:
            for f in fallos:
                logger.warning("FALLO: %s", f)
            raise AssertionError(
                f"verify_silver encontró {len(fallos)} problema(s):\n"
                + "\n".join(fallos)
            )

        logger.info(
            "verify_silver OK — record_id único y bien formado, sin nulos "
            "residuales en dtir1, age en rango, default_flag_unificada "
            "consistente con §5.2."
        )
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

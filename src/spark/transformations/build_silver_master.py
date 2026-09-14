"""
Silver — Dataset maestro unificado

Lee las 3 tablas Silver YA LIMPIAS (build_silver_loan_default.py,
build_silver_credit_risk.py, build_silver_personal_finance_tracker.py
deben haber corrido antes que este script — ver dependencia en el DAG,
sección "Orquestación" abajo), aplica el mapeo de columnas de
Contexto Maestro §5.2 a cada una por separado (unify_*_schema()), y
las une (UNION, apiladas por fila) en un único dataset maestro con
`record_id` sintético prefijado por fuente.

Por qué UNION y no JOIN: no existe una llave real entre las 3 fuentes
(§5.2/§t043) — la "unión" del proyecto es conceptual (por segmento de
comportamiento), no por identidad de persona. Cada fila del maestro
sigue perteneciendo a una sola fuente original; `record_id` da
trazabilidad al origen, no una identidad cruzada.

Columnas del dataset maestro (según §5.2):
    record_id, fuente, credit_score_norm, debt_to_income_norm,
    income_monthly_norm, age_unificada, age_synthetic_flag,
    default_flag_unificada

Además: escribe 3 sub-dimensiones
"copo de nieve" (DIM_PERFIL_CREDIT_RISK/LOAN_DEFAULT/PFT) con las
columnas crudas por fuente que alimentan los proxies de IRFI/ICA
(`calculate_kpis.py` las consume, unidas al maestro por `record_id`).
No se agregan al núcleo del maestro por la misma razón de §6.3: dejarían
2/3 de las columnas en NULL según el origen del registro.

Orquestación (Airflow, referencia para cuando se integre al DAG):
    build_silver_loan_default.py
    build_silver_credit_risk.py                    >> build_silver_master.py
    build_silver_personal_finance_tracker.py
    (las 3 primeras no dependen entre sí — pueden ir en paralelo o
    encadenadas según el mismo criterio de Ivy cache; este script
    SÍ depende de que las 3 hayan terminado.)

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/transformations/build_silver_master.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import SparkSession

from silver_transformations import (
    _add_record_id,
    select_kpi_components_credit_risk,
    select_kpi_components_loan_default,
    select_kpi_components_pft,
    unify_credit_risk_schema,
    unify_loan_default_schema,
    unify_pft_schema,
)

SILVER_PATHS = {
    "loan_default": "s3a://silver/loan_default/",
    "credit_risk": "s3a://silver/credit_risk/",
    "personal_finance_tracker": "s3a://silver/personal_finance_tracker/",
}
MASTER_PATH = "s3a://silver/master/"

# Sub-dimensiones "copo de nieve" (Contexto Maestro §6.3):
# columnas crudas por fuente que alimentan los proxies de IRFI/ICA
# (§6.2.1) y que no tiene sentido forzar en el núcleo del maestro
# (dejarían 2/3 de las columnas en NULL, ver §6.3).
DIM_PATHS = {
    "credit_risk": "s3a://silver/dim_perfil_credit_risk/",
    "loan_default": "s3a://silver/dim_perfil_loan_default/",
    "personal_finance_tracker": "s3a://silver/dim_perfil_pft/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("build_silver_master")


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
        SparkSession.builder.appName("build_silver_master")
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
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        # IMPORTANTE (Sesión 26, §6.2.1): `_add_record_id()` se llama
        # UNA sola vez por fuente, sobre el DataFrame ya leído y antes
        # de derivar nada más. El maestro (unify_*_schema) y la
        # sub-dimensión de KPI (select_kpi_components_*) parten del
        # MISMO df indexado — nunca de lecturas o llamadas separadas —
        # para garantizar que ambas salidas asignen el mismo
        # `record_id` a la misma fila física. `zipWithIndex()` no
        # garantiza el mismo orden entre dos corridas independientes.

        logger.info("Leyendo Silver de loan_default: %s", SILVER_PATHS["loan_default"])
        df_ld_indexed = _add_record_id(
            spark.read.parquet(SILVER_PATHS["loan_default"]), "LD"
        )
        df_ld_unified = unify_loan_default_schema(df_ld_indexed)
        df_ld_kpi = select_kpi_components_loan_default(df_ld_indexed)

        logger.info("Leyendo Silver de credit_risk: %s", SILVER_PATHS["credit_risk"])
        df_cr_indexed = _add_record_id(
            spark.read.parquet(SILVER_PATHS["credit_risk"]), "CR"
        )
        df_cr_unified = unify_credit_risk_schema(df_cr_indexed)
        df_cr_kpi = select_kpi_components_credit_risk(df_cr_indexed)

        logger.info(
            "Leyendo Silver de personal_finance_tracker: %s",
            SILVER_PATHS["personal_finance_tracker"],
        )
        df_pft_indexed = _add_record_id(
            spark.read.parquet(SILVER_PATHS["personal_finance_tracker"]), "PFT"
        )
        df_pft_unified = unify_pft_schema(df_pft_indexed)
        df_pft_kpi = select_kpi_components_pft(df_pft_indexed)

        # unionByName (no union() posicional): más seguro ante cualquier
        # cambio futuro en el orden de columnas de un unify_*_schema().
        df_master = df_ld_unified.unionByName(df_cr_unified).unionByName(df_pft_unified)

        total_rows = df_master.count()
        counts_by_source = df_master.groupBy("fuente").count().collect()
        logger.info("Dataset maestro: %s filas totales", total_rows)
        logger.info(
            "Filas por fuente: %s",
            {row["fuente"]: row["count"] for row in counts_by_source},
        )

        logger.info("Escribiendo dataset maestro en: %s", MASTER_PATH)
        df_master.write.mode("overwrite").option("compression", "snappy").parquet(
            MASTER_PATH
        )
        logger.info("Dataset maestro completado: %s filas escritas.", total_rows)

        logger.info("Escribiendo sub-dimensiones de KPI (DIM_PERFIL_*)...")
        df_ld_kpi.write.mode("overwrite").option("compression", "snappy").parquet(
            DIM_PATHS["loan_default"]
        )
        df_cr_kpi.write.mode("overwrite").option("compression", "snappy").parquet(
            DIM_PATHS["credit_risk"]
        )
        df_pft_kpi.write.mode("overwrite").option("compression", "snappy").parquet(
            DIM_PATHS["personal_finance_tracker"]
        )
        logger.info("Sub-dimensiones de KPI completadas.")
    except Exception:
        logger.exception("Falló la construcción del dataset maestro.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

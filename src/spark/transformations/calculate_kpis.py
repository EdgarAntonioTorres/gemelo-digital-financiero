"""
Gold — Cálculo de KPIs de riesgo/ahorro (IRFI/ICA)

Aplica las fórmulas de IRFI/ICA aprobadas por el mentor BBVA el
2026-08-11 (Contexto Maestro §6.2), extendidas a las 3
fuentes del dataset maestro vía proxies documentados (§6.2.1, Sesión
26) — las columnas originales de la fórmula (`loan_percent_income`,
`emp_stability`, `loan_int_rate_norm`, `neg_amortization_flag`,
`grade_score`, `credit_hist_norm`, `housing_penalty`) solo existen
nativamente en Credit Risk.

Proxies por componente (Sesión 26):

* emp_stability:
  - Credit Risk: person_emp_length
  - Loan Default: neutro (0.5, sin proxy)
  - Personal Finance Tracker: income_type (Salary=1.0/Mixed=0.5/Freelance=0.0)

* grade_score:
  - Credit Risk: credit_score_norm del maestro (ya es loan_grade normalizado)
  - Loan Default: neutro (0.5, sin proxy)
  - Personal Finance Tracker: neutro (0.5 — usar credit_score_norm
    violaría la exclusión deliberada de Credit_Score en IRFI, §6.2)

* credit_hist_norm:
  - Credit Risk: cb_person_cred_hist_length
  - Loan Default: neutro (0.5, sin proxy)
  - Personal Finance Tracker: neutro (0.5, sin proxy)

* loan_int_rate_norm:
  - Credit Risk: loan_int_rate
  - Loan Default: rate_of_interest
  - Personal Finance Tracker: neutro (0.5 — no es dataset de préstamos)

* housing_penalty:
  - Credit Risk: person_home_ownership (RENT=1.0/MORTGAGE=0.5/OWN=0.0)
  - Loan Default: neutro (0.5, sin proxy)
  - Personal Finance Tracker: 1 - norm(rent_or_mortgage) (invertido:
    pago alto = más madurez = MENOS riesgo, consistente con t110)

* neg_amortization_flag:
  - Credit Risk: 0 fijo (columna no existe)
  - Loan Default: Neg_ammortization (neg_amm=1.0/not_neg=0.0/NaN=0.0 —
    variabilidad real confirmada, 10.18%, NO descartada como ruido)
  - Personal Finance Tracker: 0 fijo (columna no existe)

Cada registro con al menos un componente en "neutro" se marca con
`irfi_proxy_flag`/`ica_proxy_flag = True` en `FACT_KPI_PERFIL`, mismo
criterio de trazabilidad que `age_synthetic_flag`/`*_outlier_flag`.

Lee:
    s3a://silver/master/                     (record_id, fuente, ...)
    s3a://silver/dim_perfil_credit_risk/     (componentes crudos CR)
    s3a://silver/dim_perfil_loan_default/    (componentes crudos LD)
    s3a://silver/dim_perfil_pft/             (componentes crudos PFT)
    — las 3 sub-dimensiones las escribe build_silver_master.py, en la
    misma corrida que genera el maestro (mismo record_id garantizado).

Escribe:
    s3a://gold/fact_kpi_perfil/  (Parquet — NO escribe a Postgres
    directamente; `t051` es la tarea aparte que carga Gold a
    postgres-dw, mismo patrón que el resto de src/spark/transformations/)

Modo de escritura: overwrite, no histórico (Contexto Maestro §6.4) —
Personal Finance Tracker es corte transversal (`t107`), no tiene
sentido acumular historial de un KPI cuyo dato base tampoco tiene
historia real detrás.

Uso (dentro del contenedor de Airflow, después de build_silver_master.py):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \
        /opt/airflow/src/spark/transformations/calculate_kpis.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, lit, when

from silver_transformations import INCOME_TYPE_STABILITY, _min_max_normalize

SILVER_MASTER_PATH = "s3a://silver/master/"
DIM_PATHS = {
    "credit_risk": "s3a://silver/dim_perfil_credit_risk/",
    "loan_default": "s3a://silver/dim_perfil_loan_default/",
    "personal_finance_tracker": "s3a://silver/dim_perfil_pft/",
}
FACT_KPI_PATH = "s3a://gold/fact_kpi_perfil/"

# Peso neutro para componentes sin proxy razonable en una fuente dada
# (Contexto Maestro §6.2.1) — ni penaliza ni beneficia el KPI.
NEUTRAL_WEIGHT = 0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("calculate_kpis")


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
        SparkSession.builder.appName("calculate_kpis")
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


# ==============================================================================
# Resolución de componentes por fuente (proxies de §6.2.1)
# ==============================================================================


def prepare_credit_risk_components(df: DataFrame) -> DataFrame:
    """Componentes nativos de Credit Risk (única fuente sin proxies,
    salvo `grade_score`, que se toma del maestro — ver `compute_irfi_ica`)."""
    df = _min_max_normalize(df, "_emp_raw", "emp_stability")
    df = _min_max_normalize(df, "_credit_hist_raw", "credit_hist_norm")
    df = _min_max_normalize(df, "_interest_rate_raw", "loan_int_rate_norm")
    df = df.withColumn(
        "housing_penalty",
        when(col("_housing_raw") == "RENT", lit(1.0))
        .when(col("_housing_raw") == "MORTGAGE", lit(0.5))
        .when(col("_housing_raw") == "OWN", lit(0.0))
        .otherwise(lit(NEUTRAL_WEIGHT)),  # valor inesperado/nulo -> neutro
    )
    df = df.withColumn("neg_amortization_flag", lit(0.0))  # columna no existe en CR
    df = df.withColumn("has_proxy", lit(False))  # CR no usa proxies
    return df.select(
        "record_id",
        "emp_stability",
        "credit_hist_norm",
        "loan_int_rate_norm",
        "housing_penalty",
        "neg_amortization_flag",
        "has_proxy",
    )


def prepare_loan_default_components(df: DataFrame) -> DataFrame:
    """Proxies de Loan Default: solo `loan_int_rate_norm` (rate_of_interest)
    y `neg_amortization_flag` (Neg_ammortization) tienen columna
    disponible; el resto va neutro (§6.2.1)."""
    df = _min_max_normalize(df, "_interest_rate_raw", "loan_int_rate_norm")
    df = df.withColumn(
        "neg_amortization_flag",
        when(col("_neg_amortization_raw") == "neg_amm", lit(1.0)).when(
            col("_neg_amortization_raw") == "not_neg", lit(0.0)
        )
        # NaN (0.08% de las filas, Sesión 26): sin evidencia de
        # amortización negativa, no se penaliza.
        .otherwise(lit(0.0)),
    )
    df = df.withColumn("emp_stability", lit(NEUTRAL_WEIGHT))
    df = df.withColumn("credit_hist_norm", lit(NEUTRAL_WEIGHT))
    df = df.withColumn("housing_penalty", lit(NEUTRAL_WEIGHT))
    df = df.withColumn("has_proxy", lit(True))
    return df.select(
        "record_id",
        "emp_stability",
        "credit_hist_norm",
        "loan_int_rate_norm",
        "housing_penalty",
        "neg_amortization_flag",
        "has_proxy",
    )


def prepare_pft_components(df: DataFrame) -> DataFrame:
    """Proxies de Personal Finance Tracker: `emp_stability` (income_type)
    y `housing_penalty` (rent_or_mortgage, invertido) tienen proxy; el
    resto va neutro (§6.2.1, incl. `grade_score` — corregido en Sesión
    26 para no reintroducir `credit_score` en IRFI)."""
    df = df.withColumn(
        "emp_stability",
        when(
            col("_income_type_raw") == "Salary",
            lit(INCOME_TYPE_STABILITY["Salary"]),
        )
        .when(col("_income_type_raw") == "Mixed", lit(INCOME_TYPE_STABILITY["Mixed"]))
        .when(
            col("_income_type_raw") == "Freelance",
            lit(INCOME_TYPE_STABILITY["Freelance"]),
        )
        .otherwise(lit(NEUTRAL_WEIGHT)),  # categoría inesperada -> neutro
    )
    df = _min_max_normalize(df, "_rent_or_mortgage_raw", "_rent_or_mortgage_norm")
    # Invertido respecto al monto crudo (Sesión 26): consistente con
    # `t110` (pago de vivienda alto = más madurez financiera = MENOS
    # riesgo, no más) — evita que dos KPIs lean la misma columna en
    # direcciones opuestas sin justificación.
    df = df.withColumn("housing_penalty", lit(1.0) - col("_rent_or_mortgage_norm"))
    df = df.withColumn("credit_hist_norm", lit(NEUTRAL_WEIGHT))
    df = df.withColumn("loan_int_rate_norm", lit(NEUTRAL_WEIGHT))
    df = df.withColumn("neg_amortization_flag", lit(0.0))  # columna no existe en PFT
    df = df.withColumn("has_proxy", lit(True))
    return df.select(
        "record_id",
        "emp_stability",
        "credit_hist_norm",
        "loan_int_rate_norm",
        "housing_penalty",
        "neg_amortization_flag",
        "has_proxy",
    )


def compute_irfi_ica(df_master: DataFrame, df_components: DataFrame) -> DataFrame:
    """Aplica las fórmulas de IRFI/ICA (Contexto Maestro §6.2) sobre el
    maestro unido a los componentes por fuente ya resueltos (proxies
    incluidos).

    `grade_score`: para Credit Risk se toma `credit_score_norm` del
    propio maestro (ya es `loan_grade` normalizado, calcularlo de
    nuevo sería redundante); para Loan Default/PFT va neutro — nunca
    `credit_score_norm` de esas 2 fuentes, porque ahí sí viene de
    `Credit_Score`/`credit_score`, y reusarlo violaría la exclusión
    deliberada de un score externo en IRFI (§6.2, corregido Sesión 26).
    """
    df = df_master.join(df_components, on="record_id", how="inner")

    df = df.withColumn(
        "grade_score",
        when(col("fuente") == "credit_risk", col("credit_score_norm")).otherwise(
            lit(NEUTRAL_WEIGHT)
        ),
    )

    irfi = (
        lit(0.25) * col("debt_to_income_norm")
        + lit(0.15) * (lit(1) - col("emp_stability"))
        + lit(0.20) * col("loan_int_rate_norm")
        + lit(0.15) * col("neg_amortization_flag")
        + lit(0.10) * (lit(1) - col("grade_score"))
        + lit(0.15) * (lit(1) - col("credit_hist_norm"))
    )
    ica = lit(1) - (
        lit(0.5) * col("debt_to_income_norm")
        + lit(0.3) * (lit(1) - col("emp_stability"))
        + lit(0.2) * col("housing_penalty")
    )

    df = df.withColumn("irfi", irfi)
    df = df.withColumn("ica", ica)
    # has_proxy ya viene True/False por fuente completa (CR nunca usa
    # proxy, LD/PFT siempre usan al menos uno) — se replica en ambos
    # flags porque ambos KPIs comparten los mismos componentes base.
    df = df.withColumnRenamed("has_proxy", "irfi_proxy_flag")
    df = df.withColumn("ica_proxy_flag", col("irfi_proxy_flag"))

    return df.select(
        "record_id",
        "fuente",
        "irfi",
        "ica",
        "default_flag_unificada",
        "irfi_proxy_flag",
        "ica_proxy_flag",
    )


def main() -> None:
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo dataset maestro: %s", SILVER_MASTER_PATH)
        df_master = spark.read.parquet(SILVER_MASTER_PATH)

        logger.info("Leyendo componentes crudos de Credit Risk")
        components_cr = prepare_credit_risk_components(
            spark.read.parquet(DIM_PATHS["credit_risk"])
        )

        logger.info("Leyendo componentes crudos de Loan Default")
        components_ld = prepare_loan_default_components(
            spark.read.parquet(DIM_PATHS["loan_default"])
        )

        logger.info("Leyendo componentes crudos de Personal Finance Tracker")
        components_pft = prepare_pft_components(
            spark.read.parquet(DIM_PATHS["personal_finance_tracker"])
        )

        df_components = components_cr.unionByName(components_ld).unionByName(
            components_pft
        )

        df_fact = compute_irfi_ica(df_master, df_components)

        total_rows = df_fact.count()
        proxy_rows = df_fact.filter(col("irfi_proxy_flag")).count()
        logger.info("FACT_KPI_PERFIL: %s filas totales", total_rows)
        logger.info(
            "Filas con al menos un proxy: %s (%.1f%%)",
            proxy_rows,
            100.0 * proxy_rows / total_rows if total_rows else 0.0,
        )
        counts_by_source = df_fact.groupBy("fuente").count().collect()
        logger.info(
            "Filas por fuente: %s",
            {row["fuente"]: row["count"] for row in counts_by_source},
        )

        logger.info("Escribiendo FACT_KPI_PERFIL en: %s", FACT_KPI_PATH)
        df_fact.write.mode("overwrite").option("compression", "snappy").parquet(
            FACT_KPI_PATH
        )
        logger.info("FACT_KPI_PERFIL completado: %s filas escritas.", total_rows)
    except Exception:
        logger.exception("Falló el cálculo de KPIs.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

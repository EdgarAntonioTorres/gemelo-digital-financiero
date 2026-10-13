"""
Diagnóstico desechable — "Ana después" con meta de ahorro cumplida

Contexto: `diagnose_coherencia_pft_ana.py` mostró que
`savings_goal_met == (actual_savings >= budget_goal)` se cumple en las
3,000 filas, y que hay 42 filas Freelance/early_career sin alerta de
fraude con `savings_goal_met = 1`. El mentor pidió que, al cumplir una
meta, Centavo arme un roadmap de metas más ambiciosas: una Ana después
con la meta cumplida (dato real, no inventado) sería su disparador.
El filtro estricto de la corrida anterior dejó 1 sola fila (con 77% de
ahorro sobre ingreso, poco creíble), así que aquí se listan las 42
completas, sin filtros extra, para elegir con criterio.

Qué hace (solo lectura, no escribe nada, no genera record_id):
  0. Verifica la hipótesis `actual_savings = max(0, ingreso - gasto)`:
     las 651 filas donde no coincide con ingreso - gasto deberían ser
     exactamente las de disponible negativo, con actual_savings = 0.
     Esperado: 0 filas que violen la hipótesis.
  1. Lista las filas Freelance + early_career + sin fraude +
     savings_goal_met = 1, ordenadas por cercanía de ingreso a la
     Ana inicio elegida (3704.29).

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/diagnose_ana_meta_cumplida.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

SILVER_PFT_PATH = "s3a://silver/personal_finance_tracker/"
INGRESO_REF_ANA_INICIO = 3704.29

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("diagnose_ana_meta_cumplida")


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
        SparkSession.builder.appName("diagnose_ana_meta_cumplida")
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
    spark = build_spark_session()
    try:
        df = spark.read.parquet(SILVER_PFT_PATH)
        total = df.count()

        inc = F.col("monthly_income").cast("double")
        exp = F.col("monthly_expense_total").cast("double")
        act = F.col("actual_savings").cast("double")
        disponible = inc - exp

        print("\n=== 0. HIPÓTESIS: actual_savings = max(0, ingreso - gasto) ===")
        coincide = F.abs(disponible - act) < 0.011
        piso_cero = (disponible < 0) & (act == 0)
        violan = df.filter(~(coincide | piso_cero)).count()
        print(f"Filas totales: {total}")
        print(f"Coinciden con ingreso - gasto: {df.filter(coincide).count()}")
        print(
            f"Disponible < 0 con actual_savings = 0 (piso en cero): "
            f"{df.filter(piso_cero).count()}"
        )
        print(f"Filas que violan la hipótesis (esperado 0): {violan}")

        print(
            "\n=== 1. FREELANCE + early_career + sin fraude + savings_goal_met = 1 ==="
        )
        fondo_meses = F.col("emergency_fund").cast("double") / exp
        base = df.filter(
            (F.col("income_type") == "Freelance")
            & (F.col("segmento") == "early_career")
            & (F.col("fraud_flag") == 0)
            & (F.col("savings_goal_met") == 1)
        )
        print(
            f"Filas: {base.count()} (ordenadas por cercanía de ingreso a "
            f"{INGRESO_REF_ANA_INICIO})"
        )
        (
            base.select(
                F.round(inc, 2).alias("ingreso"),
                F.round(exp, 2).alias("gasto"),
                F.round(act, 2).alias("ahorro"),
                F.round(act / inc, 3).alias("ahorro/ing"),
                F.round(F.col("budget_goal").cast("double"), 2).alias("meta_ahorro"),
                F.round(F.col("debt_to_income_ratio").cast("double"), 2).alias("dti"),
                F.round(fondo_meses, 2).alias("fondo_m"),
                F.round(F.col("emergency_fund").cast("double"), 2).alias("fondo_usd"),
                F.col("credit_score").alias("credito"),
                F.round(F.col("investment_amount").cast("double"), 2).alias(
                    "inversion"
                ),
                F.col("subscription_services").alias("subs"),
                F.round(F.col("essential_spending").cast("double"), 0).alias("esenc"),
                F.round(F.col("discretionary_spending").cast("double"), 0).alias(
                    "discrec"
                ),
            )
            .orderBy(F.abs(F.col("ingreso") - INGRESO_REF_ANA_INICIO))
            .show(60, truncate=False)
        )
        logger.info("Diagnóstico completado — no se escribió nada a ningún lado.")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

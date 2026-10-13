"""
Diagnóstico desechable — coherencia interna de PFT + detalle de las "Anas"

Contexto: la demo pasa a 2 perfiles de la MISMA protagonista (Ana al
inicio / Ana después de un tiempo con la app), ambos `Freelance` +
`early_career`. Antes de decidir qué muestra "Lo que tengo hoy" hay que
saber qué columnas de Silver PFT son coherentes entre sí. En 9
candidatos revisados a mano se vio que:
  - actual_savings = ingreso - gasto                    (9/9)
  - savings_goal_met = (actual_savings >= budget_goal)  (9/9)
  - essential + discretionary != gasto total            (0/9)
  - cash_flow_status contradice el signo del ahorro     (varios)
  - savings_rate nativo != actual_savings / ingreso     (varios)
  - loan_payment / ingreso != debt_to_income_ratio      (9/9)
Este script confirma o refuta eso sobre las 3,000 filas (agregados) y
lee el detalle de las filas candidatas.

Qué hace (solo lectura, no escribe nada, no genera record_id):
  1. Chequeos de coherencia sobre las 3,000 filas de Silver PFT.
  2. Detalle de los candidatos a Ana, localizados POR VALOR
     (income_type + monthly_income + debt_to_income_ratio, con un
     chequeo extra de gasto aproximado). Esperado: exactamente 1
     coincidencia por candidato; si no, se informa tal cual.
  3. Busca filas Freelance/early_career con savings_goal_met = 1 y
     perfil de "Ana después" — por si existe una Ana que ya cumplió
     su meta (disparador natural del roadmap que pidió el mentor).

Mismo criterio de capas que el resto de `diagnostics/`: autocontenido,
no importa nada de `transformations/`.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/diagnostics/diagnose_coherencia_pft_ana.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

SILVER_PFT_PATH = "s3a://silver/personal_finance_tracker/"

INGRESO_REF_ANA_INICIO = 3704.29

# (rol, record_id en Gold [solo referencia], ingreso_mensual,
#  ratio_endeudamiento, tasa_disponible redondeada a 3 decimales)
# Valores tomados de la salida de la query de pares sobre Gold.
CANDIDATOS = [
    ("ana_inicio", "PFT_0000636", 3704.29, 0.58, 0.169),
    ("ana_despues", "PFT_0001193", 3700.95, 0.15, 0.449),
    ("ana_despues", "PFT_0002588", 3784.62, 0.33, 0.409),
    ("ana_despues", "PFT_0001214", 3815.91, 0.15, 0.444),
    ("ana_despues", "PFT_0002539", 3854.89, 0.17, 0.366),
    ("respaldo_inicio", "PFT_0002044", 3009.56, 0.45, 0.054),
    ("respaldo_despues", "PFT_0000653", 3062.59, 0.28, 0.225),
]

COLUMNAS_DETALLE = [
    "user_id",
    "date",
    "age",
    "segmento",
    "income_type",
    "financial_scenario",
    "monthly_income",
    "monthly_expense_total",
    "actual_savings",
    "budget_goal",
    "savings_goal_met",
    "savings_rate",
    "emergency_fund",
    "debt_to_income_ratio",
    "loan_payment",
    "credit_score",
    "investment_amount",
    "subscription_services",
    "essential_spending",
    "discretionary_spending",
    "rent_or_mortgage",
    "category",
    "transaction_count",
    "fraud_flag",
    "cash_flow_status",
    "financial_stress_level",
    "financial_advice_score",
    "maturity_score",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("diagnose_coherencia_pft_ana")


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
        SparkSession.builder.appName("diagnose_coherencia_pft_ana")
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


def pct(n: int, total: int) -> str:
    return f"{n} / {total} ({n / total * 100:.2f}%)" if total else "n/a"


def seccion_coherencia(df) -> None:
    d = df.select(
        F.col("monthly_income").cast("double").alias("inc"),
        F.col("monthly_expense_total").cast("double").alias("exp"),
        F.col("actual_savings").cast("double").alias("act"),
        F.col("budget_goal").cast("double").alias("bud"),
        F.col("savings_goal_met").alias("goal"),
        F.col("essential_spending").cast("double").alias("ess"),
        F.col("discretionary_spending").cast("double").alias("disc"),
        F.col("cash_flow_status").alias("cash"),
        F.col("savings_rate").cast("double").alias("sr"),
        F.col("loan_payment").cast("double").alias("loan"),
        F.col("debt_to_income_ratio").cast("double").alias("dti"),
        F.col("rent_or_mortgage").cast("double").alias("rent"),
        F.col("investment_amount").cast("double").alias("inv"),
        F.col("emergency_fund").cast("double").alias("fund"),
        F.col("financial_stress_level").alias("stress"),
    ).cache()
    total = d.count()
    print(f"\n=== 1. COHERENCIA INTERNA DE SILVER PFT ({total} filas) ===")

    nulos = (
        d.select(*[F.sum(F.col(c).isNull().cast("int")).alias(c) for c in d.columns])
        .collect()[0]
        .asDict()
    )
    print(
        f"Nulos por columna (solo las que tienen): "
        f"{ {k: v for k, v in nulos.items() if v} or 'ninguna' }"
    )

    n = d.filter(F.abs(F.col("inc") - F.col("exp") - F.col("act")) < 0.011).count()
    print(f"\n[1a] actual_savings == ingreso - gasto: {pct(n, total)}")

    regla = F.col("act") >= F.col("bud")
    n = d.filter((F.col("goal") == 1) == regla).count()
    print(f"[1b] savings_goal_met == (actual_savings >= budget_goal): {pct(n, total)}")
    print("     Cruce goal x regla (si 1b no es ~100%, aquí se ve dónde falla):")
    d.groupBy("goal", regla.alias("regla_cumple")).count().orderBy(
        "goal", "regla_cumple"
    ).show()

    gap = F.col("exp") - (F.col("ess") + F.col("disc"))
    print("[1c] essential + discretionary vs gasto total:")
    print(
        f"     coinciden (|gap| <= 1): {pct(d.filter(F.abs(gap) <= 1).count(), total)}"
    )
    print(
        f"     componentes MENOR que total (gap > 1): {pct(d.filter(gap > 1).count(), total)}"
    )
    print(
        f"     componentes MAYOR que total (gap < -1): {pct(d.filter(gap < -1).count(), total)}"
    )
    q = d.withColumn("gap_rel", gap / F.col("exp")).select(
        F.expr("percentile_approx(gap_rel, array(0.1, 0.5, 0.9))").alias("q")
    )
    print(f"     gap / gasto total, percentiles [p10, p50, p90]: {q.collect()[0]['q']}")

    signo = (
        F.when(F.col("act") > 0, "ahorro>0")
        .when(F.col("act") < 0, "ahorro<0")
        .otherwise("ahorro=0")
    )
    print("\n[1d] cash_flow_status x signo del ahorro real:")
    d.groupBy("cash", signo.alias("signo")).count().orderBy("cash", "signo").show()

    d2 = d.withColumn("sr_real", F.col("act") / F.col("inc"))
    n = d2.filter(F.abs(F.col("sr") - F.col("sr_real")) <= 0.02).count()
    print(
        f"[1e] savings_rate nativo ~ actual_savings/ingreso (+-0.02): {pct(n, total)}"
    )
    print(
        f"     correlación savings_rate vs ahorro/ingreso: {d2.stat.corr('sr', 'sr_real'):.3f}"
    )

    d3 = d.withColumn("loan_rel", F.col("loan") / F.col("inc"))
    n = d3.filter(F.abs(F.col("loan_rel") - F.col("dti")) <= 0.02).count()
    print(
        f"\n[1f] loan_payment/ingreso ~ debt_to_income_ratio (+-0.02): {pct(n, total)}"
    )
    print(
        f"     correlación loan_payment/ingreso vs dti: {d3.stat.corr('loan_rel', 'dti'):.3f}"
    )

    print(
        f"\n[1g] rent_or_mortgage > essential_spending: "
        f"{pct(d.filter(F.col('rent') > F.col('ess')).count(), total)}"
    )

    print("\n[1h] financial_stress_level: ¿informa algo? (promedios por nivel)")
    d.groupBy("stress").agg(
        F.count("*").alias("n"),
        F.round(F.avg("dti"), 3).alias("dti_prom"),
        F.round(F.avg(F.col("act") / F.col("inc")), 3).alias("ahorro/ingreso_prom"),
    ).orderBy("stress").show()

    print("[1i] investment_amount: ¿flujo mensual o saldo acumulado? (percentiles)")
    d.select(
        F.expr("percentile_approx(inv, array(0.1, 0.5, 0.9))").alias("inv_p10_p50_p90"),
        F.expr("percentile_approx(inv / inc, array(0.1, 0.5, 0.9))").alias(
            "inv/ingreso_p10_p50_p90"
        ),
        F.sum((F.col("inv") == 0).cast("int")).alias("inv_igual_0"),
    ).show(truncate=False)
    d.unpersist()


def seccion_candidatos(df) -> None:
    print("\n=== 2. DETALLE DE CANDIDATOS A ANA (localizados por valor) ===")
    resumen = []
    for rol, rid, ingreso, dti, disp in CANDIDATOS:
        filas = df.filter(
            (F.col("income_type") == "Freelance")
            & (F.abs(F.col("monthly_income") - ingreso) < 0.005)
            & (F.abs(F.col("debt_to_income_ratio") - dti) < 0.00005)
        ).collect()
        gasto_aprox = ingreso * (1 - disp)
        print(
            f"\n--- {rol.upper()} | ref. Gold: {rid} | coincidencias: {len(filas)} ---"
        )
        gasto_ok_total = 0
        for i, fila in enumerate(filas, start=1):
            if len(filas) > 1:
                print(f"  (coincidencia {i} de {len(filas)})")
            gasto = float(fila["monthly_expense_total"])
            gasto_ok = abs(gasto - gasto_aprox) <= 4.0
            gasto_ok_total += int(gasto_ok)
            for col in COLUMNAS_DETALLE:
                print(f"  {col}: {fila[col]}")
            print(
                f"  [chequeo] gasto implicado por Gold ~ {gasto_aprox:.2f} | "
                f"gasto en Silver = {gasto:.2f} | coincide: {gasto_ok}"
            )
        resumen.append((rol, rid, len(filas), gasto_ok_total))

    print("\n--- Resumen de coincidencias (esperado: 1 coincidencia y gasto OK) ---")
    for rol, rid, n, ok in resumen:
        marca = "OK" if (n == 1 and ok == 1) else "REVISAR"
        print(f"  {rol:17s} {rid}  coincidencias={n}  gasto_ok={ok}  [{marca}]")


def seccion_ana_con_meta(df) -> None:
    print("\n=== 3. ¿EXISTE UNA 'ANA DESPUÉS' QUE YA CUMPLIÓ SU META? ===")
    base = df.filter(
        (F.col("income_type") == "Freelance")
        & (F.col("segmento") == "early_career")
        & (F.col("fraud_flag") == 0)
    )
    print(f"Freelance + early_career + sin alerta de fraude: {base.count()} filas")
    print(
        f"  de ellas con savings_goal_met = 1: "
        f"{base.filter(F.col('savings_goal_met') == 1).count()}"
    )

    fondo_meses = F.col("emergency_fund") / F.col("monthly_expense_total")
    cercanas = base.filter(
        (F.col("savings_goal_met") == 1)
        & (
            F.abs(F.col("monthly_income") - INGRESO_REF_ANA_INICIO)
            / INGRESO_REF_ANA_INICIO
            <= 0.10
        )
        & (F.col("debt_to_income_ratio") <= 0.35)
        & (fondo_meses >= 0.45)
    )
    n = cercanas.count()
    print(
        f"\nCon meta cumplida, ingreso a +-10% de {INGRESO_REF_ANA_INICIO}, "
        f"ratio de endeudamiento <= 0.35 y fondo >= 0.45 meses: {n} filas"
    )
    if n:
        (
            cercanas.select(
                "monthly_income",
                "monthly_expense_total",
                "actual_savings",
                "budget_goal",
                "debt_to_income_ratio",
                F.round(fondo_meses, 2).alias("fondo_meses"),
                "emergency_fund",
                "credit_score",
                "subscription_services",
            )
            .orderBy(F.abs(F.col("monthly_income") - INGRESO_REF_ANA_INICIO))
            .show(10, truncate=False)
        )


def main() -> None:
    spark = build_spark_session()
    try:
        logger.info("Leyendo Silver PFT: %s", SILVER_PFT_PATH)
        df = spark.read.parquet(SILVER_PFT_PATH)
        seccion_coherencia(df)
        seccion_candidatos(df)
        seccion_ana_con_meta(df)
        logger.info("Diagnóstico completado — no se escribió nada a ningún lado.")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()

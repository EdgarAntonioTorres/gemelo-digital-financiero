"""
ML — Split train/test con foco segmentado en usuarios <30 años

Lee `gold.fact_kpi_perfil` y asigna cada `record_id` a
`train`/`test`, preservando 2 cosas simultáneamente:

  1. La proporción de `default_flag_unificada` (la variable objetivo)
     dentro de cada `fuente` — split estratificado estándar, para que
     ni el modelo baseline ni el avanzado vean un
     desbalance artificial entre train y test.
  2. La proporción del segmento `<30` DENTRO de `credit_risk`
     específicamente — es el "foco segmentado" que pide, y
     habilita la comparación de (modelo segmentado vs.
     genérico) sin que el split introduzca un sesgo por sí mismo.

Hallazgo que determina el diseño (mismo criterio que
en la Bitácora — no fabricar lo que los datos no sostienen):

  `default_flag_unificada` (el target) solo es no-nulo en
  `loan_default` (148,670 filas) y `credit_risk` (32,416 filas) —
  `personal_finance_tracker` no tiene equivalente real de default
  (§5.2 Contexto Maestro), así que NO participa en el split de
  modelado. Población de modelado real: 181,086 filas.

  `segmento` en `gold.fact_kpi_perfil` NO es el `segmento` de
  `derive_synthetic_age()` (Silver-PFT, umbral de `maturity_score`,
  `p=0.7216`) — ese cálculo vive solo dentro de Silver-PFT
  para generar la edad sintética y nunca se selecciona en
  `unify_pft_schema()`, no llega al dataset maestro. El `segmento`
  real de Gold se RECALCULA en `calculate_kpis.py`
  (`compute_irfi_ica()`) con un corte simple `age_unificada < 30`
  (`SEGMENTO_AGE_THRESHOLD = 30`, vía `try_cast` porque `age_unificada`
  es string heterogéneo entre fuentes — hallazgo Sesión 30). Verificado
  en el código real (no en la documentación derivada): puebla
  `segmento` tanto en `credit_risk` como en `personal_finance_tracker`
  (ambas tienen edad exacta parseable) — `NULL` únicamente en
  `loan_default` (bins de 10 años, `try_cast` no parsea el bin y
  devuelve `NULL` a propósito, no un supuesto de distribución).

  Esto no cambia el resultado de este script: `personal_finance_tracker`
  ya queda fuera de la población de modelado por no tener
  `default_flag_unificada` (ver más abajo), así que dentro de esa
  población `es_segmento_prioritario_lt30` solo puede dar `True` en
  `credit_risk` de todas formas — pero la razón correcta es esta, no
  la que asumía la primera versión de este docstring (que atribuía
  el segmento de Gold al umbral, incorrectamente).

  Conclusión (decidida con el alumno, no asumida por default): el
  segmento "<30 con foco" de SOLO puede construirse
  desde `credit_risk` con `segmento = 'early_career'`. No se extiende
  a `personal_finance_tracker` (no tiene target) ni se inventa un
  segmento para `loan_default` (no hay dato que lo sostenga). Esto
  queda expuesto en la columna `es_segmento_prioritario_lt30` — si en
  el futuro alguna fuente nueva trae segmento + target, la misma
  columna la absorbe sin cambiar el criterio.

Metodología del split (estratificación por grupo, no `randomSplit`
global):

  `estrato` = `fuente` + `default_flag_unificada` + `segmento`
  (con `segmento` reemplazado por `'NA'` cuando es NULL, vía
  `coalesce`). Esto da 6 estratos reales:
    loan_default   | 0.0 | NA
    loan_default   | 1.0 | NA
    credit_risk    | 0.0 | early_career
    credit_risk    | 0.0 | established
    credit_risk    | 1.0 | early_career
    credit_risk    | 1.0 | established

  Se corre `randomSplit([0.8, 0.2], seed=42)` POR ESTRATO (no sobre
  el dataset completo) y se unen los resultados — así la proporción
  80/20 se cumple dentro de cada estrato, no solo en el agregado.
  Semilla fija (42) por reproducibilidad, mismo criterio de
  determinismo ya aplicado en `age` sintética y en el
  threshold de segmentación.

Alcance deliberado de este script (para no invadir):
  Solo asigna `split_set` y expone `es_segmento_prioritario_lt30`.
  NO hace feature engineering ni selecciona columnas crudas de
  modelado (`loan_percent_income`, `emp_stability`, etc.) — esas
  viven en `DIM_PERFIL_CREDIT_RISK`/`DIM_PERFIL_LOAN_DEFAULT`
  (`silver/dim_perfil_*`) y se unen por `record_id` en,
  cuando se sepa qué features usa cada modelo. Fusionar ambas cosas
  aquí habría mezclado una decisión de split (estable, no debería
  cambiar) con una decisión de features
  (específica de cada modelo).

Lee:
    s3a://gold/fact_kpi_perfil/  (record_id, fuente, segmento, irfi,
    ica, default_flag_unificada, irfi_proxy_flag, ica_proxy_flag)

Escribe:
    s3a://gold/ml_train_test_split/  (Parquet) — mismas columnas de
    entrada + `es_segmento_prioritario_lt30` (boolean) + `split_set`
    ('train'/'test'). Grano: 1 fila por `record_id` de la población
    de modelado (loan_default + credit_risk, target no nulo). NO
    incluye `personal_finance_tracker` (sin target, ver arriba).

Modo de escritura: overwrite — el split se recalcula completo en
cada corrida (mismo criterio que las demás tablas Gold del
proyecto); si se necesita reproducir un split exacto entre sesiones,
la semilla fija (42) + la lógica determinística de estratos lo
garantizan sin necesidad de modo histórico.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/split_train_test.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import coalesce, col, concat_ws, lit, when
from pipeline_timing import log_execution

GOLD_FACT_KPI_PERFIL_PATH = "s3a://gold/fact_kpi_perfil/"
GOLD_ML_TRAIN_TEST_SPLIT_PATH = "s3a://gold/ml_train_test_split/"

# Fuentes con default_flag_unificada no nulo (ver docstring del
# módulo) — personal_finance_tracker queda fuera por diseño, no por
# error: no tiene target real.
FUENTES_CON_TARGET = ("loan_default", "credit_risk")

TRAIN_RATIO = 0.8
TEST_RATIO = 0.2
SPLIT_SEED = 42  # fijo por reproducibilidad, mismo criterio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("split_train_test")


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
        SparkSession.builder.appName("split_train_test")
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


def assign_stratified_split(df: DataFrame) -> DataFrame:
    """Asigna train/test por estrato (fuente x target x segmento).

    randomSplit() estándar de Spark corrido UNA vez por cada valor
    distinto de `estrato`, no sobre el DataFrame completo — así la
    proporción 80/20 se respeta dentro de cada combinación, no solo
    en el total (ver docstring del módulo, sección "Metodología").
    """
    df = df.withColumn(
        "estrato",
        concat_ws(
            "|",
            col("fuente"),
            col("default_flag_unificada").cast("string"),
            coalesce(col("segmento"), lit("NA")),
        ),
    )

    estratos = [row["estrato"] for row in df.select("estrato").distinct().collect()]
    logger.info("Estratos detectados (%s): %s", len(estratos), sorted(estratos))

    splits = []
    for estrato in estratos:
        df_estrato = df.filter(col("estrato") == estrato)
        df_train, df_test = df_estrato.randomSplit(
            [TRAIN_RATIO, TEST_RATIO], seed=SPLIT_SEED
        )
        splits.append(df_train.withColumn("split_set", lit("train")))
        splits.append(df_test.withColumn("split_set", lit("test")))

    df_split = splits[0]
    for part in splits[1:]:
        df_split = df_split.unionByName(part)

    return df_split.drop("estrato")


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo FACT_KPI_PERFIL: %s", GOLD_FACT_KPI_PERFIL_PATH)
        df = spark.read.parquet(GOLD_FACT_KPI_PERFIL_PATH)

        total_gold = df.count()
        logger.info("FACT_KPI_PERFIL completo: %s filas (las 3 fuentes)", total_gold)

        # Población de modelado: solo fuentes con target real (ver
        # docstring). personal_finance_tracker (default_flag_unificada
        # siempre NULL) queda fuera aquí, no en una etapa posterior —
        # así ningún script downstream puede entrenar por accidente
        # sobre filas sin target.
        df_modelado = df.filter(col("fuente").isin(*FUENTES_CON_TARGET))
        total_modelado = df_modelado.count()
        logger.info(
            "Población de modelado (target no nulo): %s filas (%s excluidas de "
            "personal_finance_tracker, sin target real)",
            total_modelado,
            total_gold - total_modelado,
        )

        # es_segmento_prioritario_lt30: True únicamente cuando la
        # fuente trae segmento conocido Y es early_career. En la
        # práctica, dentro de la población de modelado, solo
        # credit_risk puede dar True (ver docstring) — loan_default
        # da False siempre porque su segmento es NULL, no porque se
        # haya evaluado y descartado.
        df_modelado = df_modelado.withColumn(
            "es_segmento_prioritario_lt30",
            when(col("segmento") == lit("early_career"), lit(True)).otherwise(
                lit(False)
            ),
        )

        df_final = assign_stratified_split(df_modelado)

        # --- Verificación (mismo espíritu que verify_gold_postgres.py:
        # validar con datos reales, no asumir que la lógica hizo lo
        # que se esperaba) ---
        train_count = df_final.filter(col("split_set") == "train").count()
        test_count = df_final.filter(col("split_set") == "test").count()
        logger.info(
            "Split global: train=%s (%.2f%%) test=%s (%.2f%%) total=%s",
            train_count,
            100 * train_count / total_modelado,
            test_count,
            100 * test_count / total_modelado,
            train_count + test_count,
        )
        if train_count + test_count != total_modelado:
            logger.warning(
                "El total post-split (%s) no coincide con la población de "
                "modelado (%s) — revisar antes de usar este split.",
                train_count + test_count,
                total_modelado,
            )

        logger.info("--- Balance del target por fuente y split_set ---")
        df_final.groupBy(
            "fuente", "split_set", "default_flag_unificada"
        ).count().orderBy("fuente", "split_set", "default_flag_unificada").show(
            truncate=False
        )

        logger.info(
            "--- Balance del segmento prioritario <30 dentro de credit_risk "
            "(el 'foco segmentado' de t061) ---"
        )
        df_final.filter(col("fuente") == "credit_risk").groupBy(
            "split_set", "es_segmento_prioritario_lt30"
        ).count().orderBy("split_set", "es_segmento_prioritario_lt30").show(
            truncate=False
        )

        logger.info(
            "Escribiendo ML_TRAIN_TEST_SPLIT en: %s", GOLD_ML_TRAIN_TEST_SPLIT_PATH
        )
        df_final.write.mode("overwrite").option("compression", "snappy").parquet(
            GOLD_ML_TRAIN_TEST_SPLIT_PATH
        )
        logger.info(
            "ML_TRAIN_TEST_SPLIT completado: %s filas escritas.",
            train_count + test_count,
        )
    except Exception:
        status = "failed"
        logger.exception("Falló el split train/test.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("split_train_test", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

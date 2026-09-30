"""
ML — Modelo baseline: Logistic Regression sobre las 5 features
confirmadas con datos reales (`t062`)

Features usadas (confirmadas con `peek_kpi_features_t062.py` antes de
escribir este script — ver Bitácora, Sesión 32):
    credit_score_norm, debt_to_income_norm, income_monthly_norm
      -> ya normalizadas/calculadas en `silver/master`, se leen
      directo, sin recalcular.
    loan_int_rate_norm, neg_amortization_flag
      -> NO están persistidas en ninguna tabla (`calculate_kpis.py`
      las calcula de forma transitoria, solo para IRFI/ICA). Se
      recalculan aquí con la MISMA fórmula (`_min_max_normalize` por
      fuente sobre `_interest_rate_raw`; mapeo `neg_amm`=1.0/
      `not_neg`=0.0/`NULL`=0.0 sobre `_neg_amortization_raw`).

Duplicación deliberada, no descuido: no se importa
`calculate_kpis.py`/`silver_transformations.py` desde `src/ml/` —
mismo espíritu que la regla de Contexto Maestro §7.3
("`diagnostics/` nunca importa de `transformations/`"), aplicada aquí
para no acoplar el pipeline de modelado a los internals de Gold. Si
`calculate_kpis.py` cambia la fórmula de estos 2 proxies, este
script debe actualizarse a mano — documentado aquí para que quede
visible en el próximo `git blame`, no escondido.

Explícitamente NO usadas como features (decisión con el alumno,
Sesión 32, ver Bitácora):
  - `irfi`/`ica`: casi circulares (combinación lineal de pesos ya
    fijados a mano sobre estos mismos componentes).
  - `emp_stability`/`credit_hist_norm`/`housing_penalty`: confirmado
    con el ESQUEMA real de `dim_perfil_loan_default` (no solo con
    lectura de código) que no tienen ninguna columna cruda detrás en
    `loan_default` — son 0.5 constante en el 100% de esas filas, un
    atajo de "de qué fuente vengo" más que señal financiera.
  - `fuente` (one-hot): mismo criterio — se deja fuera del baseline a
    propósito; si el rendimiento resulta sospechoso, se prueba
    agregarla en `t063` y se documenta el efecto con datos, no se
    asume de entrada.

Fuga de datos en loan_int_rate_norm para loan_default (hallazgo de
`t063`, Sesión 32 — ver historial completo en el docstring de
`prepare_loan_default_proxies()` abajo, con los 3 diagnósticos que lo
confirmaron). Resumen: `rate_of_interest` en `loan_default` tiene un
patrón de nulos que encierra el desenlace real (99.45% de los defaults
reales caen exactamente dentro de las filas con el dato imputado) —
fuga de datos del dataset original de Kaggle, no señal financiera.
Corrección final: `loan_int_rate_norm` queda neutro (`NEUTRAL_WEIGHT`)
para el 100% de `loan_default`, igual que
`emp_stability`/`credit_hist_norm`/`housing_penalty` — sigue siendo
real y confirmado limpio en `credit_risk`. Se mantienen 5 features (no
6 — un intento intermedio agregó `tasa_interes_imputada_flag` como
feature aparte, pero resultó ser la misma fuga con otro disfraz, se
eliminó). PENDIENTE para llevar al mentor, no resuelto aquí: el mismo
`loan_int_rate_norm` con dato crudo (sin neutralizar) se usa con peso
real en la fórmula de IRFI de `calculate_kpis.py` (Fase 4, ya
aprobada) — es probable que tenga esta misma fuga.

Desbalance de clases (decisión tomada DESPUÉS de la primera corrida sin
pesos, Sesión 32): sin ponderar, el AUC daba ~0.60 pero el recall de
`default=1` en test era ~2% (189 de 8,544 casos reales) — el
optimizador casi no penalizaba ignorar la clase minoritaria (~24%
default / ~76% no-default en train). Se agrega `class_weight`
(fórmula balanceada estándar, calculada SOLO con `train`) al
`LogisticRegression` vía `weightCol`, antes de construir `t063` — para
que baseline y modelo avanzado compartan el mismo criterio de
desbalance desde el inicio, y no haya que reentrenar ambos más
adelante para que `t065` compare de forma justa.

Alcance de `t062` (para no invadir `t063`/`t064`/`t065`/`t066`):
  Entrena la población "genérica" (`train` completo, sin filtrar por
  segmento) y reporta métricas básicas de sanity-check (AUC, F1,
  matriz de confusión). NO hace tuning de hiperparámetros (eso
  distingue este baseline del modelo avanzado de `t063`, no sería un
  "baseline" si ya viene optimizado). NO serializa el modelo (`t066`).
  NO entrena la variante segmentada `<30` de `t065` — ese script
  reutiliza `build_feature_frame()` de aquí, filtrando por
  `es_segmento_prioritario_lt30 == True` antes de ensamblar el vector
  de features, para comparar contra esta misma corrida "genérica".

Lee:
    s3a://gold/ml_train_test_split/       (t061)
    s3a://silver/master/                  (credit_score_norm, debt_to_income_norm,
                                            income_monthly_norm)
    s3a://silver/dim_perfil_credit_risk/  (_interest_rate_raw)
    s3a://silver/dim_perfil_loan_default/ (_interest_rate_raw, _neg_amortization_raw)

Escribe:
    s3a://gold/ml_features_baseline/  (Parquet, overwrite) — tabla de
    features ya ensambladas (record_id, fuente, split_set, segmento,
    es_segmento_prioritario_lt30, default_flag_unificada + las 5
    features). Reusable por t063/t065 sin recalcular el join — mismo
    criterio de "1 tabla que se llena, no fragmentar" ya usado en
    FACT_COMPORTAMIENTO (t054-t057).

    El modelo entrenado NO se escribe a disco (`t066` lo serializa
    cuando el modelo final esté decidido); esta corrida solo imprime
    métricas al log.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/train_baseline_model.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

from pyspark.ml.classification import LogisticRegression
from pyspark.ml.evaluation import (
    BinaryClassificationEvaluator,
    MulticlassClassificationEvaluator,
)
from pyspark.ml.feature import StandardScaler, VectorAssembler
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, count, lit, max, min, when
from pipeline_timing import log_execution

GOLD_ML_TRAIN_TEST_SPLIT_PATH = "s3a://gold/ml_train_test_split/"
SILVER_MASTER_PATH = "s3a://silver/master/"
DIM_PATHS = {
    "credit_risk": "s3a://silver/dim_perfil_credit_risk/",
    "loan_default": "s3a://silver/dim_perfil_loan_default/",
}
GOLD_ML_FEATURES_PATH = "s3a://gold/ml_features_baseline/"

# Mismo valor que NEUTRAL_WEIGHT en calculate_kpis.py — no se importa
# (ver docstring), se duplica el literal a propósito, documentado.
NEUTRAL_WEIGHT = 0.5

FEATURE_COLUMNS = [
    "credit_score_norm",
    "debt_to_income_norm",
    "income_monthly_norm",
    "loan_int_rate_norm",
    "neg_amortization_flag",
]
LABEL_COLUMN = "default_flag_unificada"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_baseline_model")


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
        SparkSession.builder.appName("train_baseline_model")
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


def _min_max_normalize(df: DataFrame, column: str, alias: str) -> DataFrame:
    """Duplicado deliberado de `_min_max_normalize()` en
    `silver_transformations.py` (ver docstring del módulo — no se
    importa a propósito). Mismo comportamiento exacto, incluyendo el
    caso borde de columna constante (span=0 -> 0.5 fijo)."""
    stats = df.agg(min(column), max(column)).collect()[0]
    col_min, col_max = stats[f"min({column})"], stats[f"max({column})"]
    span = col_max - col_min
    if span == 0:
        return df.withColumn(alias, lit(0.5))
    return df.withColumn(alias, (col(column) - lit(col_min)) / lit(span))


def prepare_credit_risk_proxies(df_dim_cr: DataFrame) -> DataFrame:
    """loan_int_rate_norm real (proxy con dato, CONFIRMADO limpio —
    ver docstring del módulo: relación gradual con el target, sin
    nulos, sin el patrón de fuga encontrado en loan_default);
    neg_amortization_flag fijo en 0 (la columna no existe en Credit
    Risk — mismo criterio que `prepare_credit_risk_components()` en
    `calculate_kpis.py`)."""
    df = _min_max_normalize(df_dim_cr, "_interest_rate_raw", "loan_int_rate_norm")
    df = df.withColumn("neg_amortization_flag", lit(0.0))
    return df.select("record_id", "loan_int_rate_norm", "neg_amortization_flag")


def prepare_loan_default_proxies(df_dim_ld: DataFrame) -> DataFrame:
    """neg_amortization_flag con dato real en Loan Default — mismo
    criterio que `prepare_loan_default_components()` en
    `calculate_kpis.py`.

    loan_int_rate_norm: NEUTRALIZADO (NEUTRAL_WEIGHT) para el 100% de
    loan_default — NO solo las filas imputadas. Historial completo del
    hallazgo (Sesión 32, 2 intentos antes de esta versión final):

      1ra corrida (t063 original): AUC~0.96, loan_int_rate_norm con
         58.6% de importancia — se investigó por sospechoso.
      Diagnóstico 1 (peek_loan_int_rate_signal.py): deciles NO
         monótonos, salto brusco, masa de filas con valor idéntico
         (~3.99) → sospecha de imputación.
      Diagnóstico 2 (peek_interest_rate_imputation.py): confirmado —
         31.75% de filas comparten ese valor imputado, tasa de default
         18x más alta que el resto (69.4% vs 3.8%).
      Intento de corrección #1 (INCORRECTO): exponer
         `tasa_interes_imputada_flag` como feature aparte, neutralizar
         solo las filas imputadas. Empeoró el problema — AUC subió a
         ~0.97-0.996, el flag concentró 92.8% de la importancia.
      Diagnóstico 3 (peek_imputation_leakage.py, TEST DECISIVO): dentro
         de CADA loan_type, `rate_of_interest_imputed_flag=True` da
         tasa de default EXACTAMENTE 1.0 (100%), `False` da ~0%-1.16%.
         99.45% de los defaults reales de loan_default caen dentro del
         grupo imputado. Esto es FUGA DE DATOS real (el patrón de
         nulos del CSV original de Kaggle encierra el desenlace), no
         una relación financiera ni un proxy de loan_type.
      Corrección final (esta versión): loan_int_rate_norm neutro para
         el 100% de loan_default, sin excepción — mismo tratamiento
         que ya reciben emp_stability/credit_hist_norm/housing_penalty
         (real solo en credit_risk). Se elimina
         `tasa_interes_imputada_flag` — era pura fuga, no una feature.

      PENDIENTE — no resuelto en este script: `calculate_kpis.py` usa
      este mismo loan_int_rate_norm con peso real (0.20) en la fórmula
      de IRFI para loan_default (aprobada por el mentor en Fase 4).
      Es probable que el IRFI de loan_default tenga esta misma fuga
      desde antes de Fase 5 — pendiente de llevar al mentor, no se
      corrige aquí sin su validación.
    """
    df = df_dim_ld.withColumn("loan_int_rate_norm", lit(NEUTRAL_WEIGHT))
    df = df.withColumn(
        "neg_amortization_flag",
        when(col("_neg_amortization_raw") == "neg_amm", lit(1.0))
        .when(col("_neg_amortization_raw") == "not_neg", lit(0.0))
        .otherwise(lit(0.0)),  # NULL (0.08%): sin evidencia, no se penaliza
    )
    return df.select("record_id", "loan_int_rate_norm", "neg_amortization_flag")


def build_feature_frame(spark: SparkSession) -> DataFrame:
    """Ensambla la tabla de features reusable (`ml_features_baseline`).

    Grano: 1 fila por `record_id` de la población de modelado de
    `t061` (`loan_default` + `credit_risk`, target no nulo).
    """
    df_split = spark.read.parquet(GOLD_ML_TRAIN_TEST_SPLIT_PATH)
    df_master = spark.read.parquet(SILVER_MASTER_PATH).select(
        "record_id", "credit_score_norm", "debt_to_income_norm", "income_monthly_norm"
    )

    proxies_cr = prepare_credit_risk_proxies(
        spark.read.parquet(DIM_PATHS["credit_risk"])
    )
    proxies_ld = prepare_loan_default_proxies(
        spark.read.parquet(DIM_PATHS["loan_default"])
    )
    df_proxies = proxies_cr.unionByName(proxies_ld)

    df_features = df_split.join(df_master, on="record_id", how="inner").join(
        df_proxies, on="record_id", how="inner"
    )
    return df_features.select(
        "record_id",
        "fuente",
        "segmento",
        "es_segmento_prioritario_lt30",
        "split_set",
        LABEL_COLUMN,
        *FEATURE_COLUMNS,
    )


def add_class_weights(df_train: DataFrame) -> DataFrame:
    """Agrega `class_weight` (fórmula balanceada estándar,
    `n_total / (2 * n_clase)`) calculada SOLO con `train` — nunca con
    `test`, que no debe influir en cómo se pondera el entrenamiento.

    Decisión de Sesión 32 (no en el diseño original de t062): la
    primera corrida sin pesos dio AUC~0.60 pero recall de la clase
    `default=1` de solo ~2% en test (predijo default en 189 de 8,544
    casos reales) — el desbalance real (~24% default / ~76% no-default
    en train) hacía que el optimizador casi no penalizara ignorar la
    clase minoritaria. Se corrige aquí, antes de construir `t063`, para
    que el baseline y el modelo avanzado compartan el mismo criterio de
    desbalance desde el inicio — evita reentrenar ambos más adelante
    para poder comparar `t065` de forma justa.
    """
    counts = df_train.groupBy(LABEL_COLUMN).agg(count("*").alias("n")).collect()
    counts_by_label = {row[LABEL_COLUMN]: row["n"] for row in counts}
    n_total = sum(counts_by_label.values())
    n_classes = len(counts_by_label)  # 2 (0.0/1.0) en este dataset

    logger.info(
        "Distribución de clases en train (para pesos balanceados): %s (total=%s)",
        counts_by_label,
        n_total,
    )

    weight_positivo = n_total / (n_classes * counts_by_label[1.0])
    weight_negativo = n_total / (n_classes * counts_by_label[0.0])
    logger.info(
        "  Peso balanceado -> default=1.0: %.4f | default=0.0: %.4f",
        weight_positivo,
        weight_negativo,
    )

    return df_train.withColumn(
        "class_weight",
        when(col(LABEL_COLUMN) == lit(1.0), lit(weight_positivo)).otherwise(
            lit(weight_negativo)
        ),
    )


def train_and_evaluate(df_features: DataFrame) -> None:
    """Entrena Logistic Regression sobre `train` (población genérica,
    sin filtrar por segmento) y reporta métricas de sanity-check sobre
    `train` y `test`. Escalado (StandardScaler) ajustado SOLO con
    `train`, aplicado a ambos — evita fuga de información de `test`
    hacia el ajuste del escalador. Pesos de clase (`class_weight`)
    también calculados SOLO con `train` (ver `add_class_weights()`) —
    `test` se evalúa sin ponderar, con las métricas estándar."""
    assembler = VectorAssembler(inputCols=FEATURE_COLUMNS, outputCol="features_raw")
    scaler = StandardScaler(
        inputCol="features_raw", outputCol="features", withMean=True, withStd=True
    )

    df_train = assembler.transform(df_features.filter(col("split_set") == "train"))
    df_test = assembler.transform(df_features.filter(col("split_set") == "test"))

    scaler_model = scaler.fit(df_train)  # SOLO train
    df_train_scaled = scaler_model.transform(df_train)
    df_test_scaled = scaler_model.transform(df_test)

    df_train_scaled = add_class_weights(df_train_scaled)

    lr = LogisticRegression(
        featuresCol="features", labelCol=LABEL_COLUMN, weightCol="class_weight"
    )
    model = lr.fit(df_train_scaled)

    logger.info("--- Coeficientes del modelo (feature -> peso) ---")
    for feature_name, weight in zip(FEATURE_COLUMNS, model.coefficients):
        logger.info("  %s: %.4f", feature_name, weight)
    logger.info("  intercept: %.4f", model.intercept)

    auc_evaluator = BinaryClassificationEvaluator(
        labelCol=LABEL_COLUMN, metricName="areaUnderROC"
    )
    f1_evaluator = MulticlassClassificationEvaluator(
        labelCol=LABEL_COLUMN, predictionCol="prediction", metricName="f1"
    )

    for split_name, df_split_scaled in [
        ("train", df_train_scaled),
        ("test", df_test_scaled),
    ]:
        predictions = model.transform(df_split_scaled)
        auc = auc_evaluator.evaluate(predictions)
        f1 = f1_evaluator.evaluate(predictions)
        logger.info("--- Métricas en %s ---", split_name)
        logger.info("  AUC: %.4f", auc)
        logger.info("  F1: %.4f", f1)
        logger.info("  Matriz de confusión (predicted x actual):")
        predictions.groupBy("prediction", LABEL_COLUMN).count().orderBy(
            "prediction", LABEL_COLUMN
        ).show()


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Ensamblando tabla de features (t062)...")
        df_features = build_feature_frame(spark)
        df_features.cache()

        total_rows = df_features.count()
        logger.info("ml_features_baseline: %s filas ensambladas", total_rows)

        logger.info("Escribiendo ml_features_baseline en: %s", GOLD_ML_FEATURES_PATH)
        df_features.write.mode("overwrite").option("compression", "snappy").parquet(
            GOLD_ML_FEATURES_PATH
        )

        logger.info(
            "Entrenando modelo baseline (población genérica, train completo)..."
        )
        train_and_evaluate(df_features)

        logger.info("t062 completado.")
    except Exception:
        status = "failed"
        logger.exception("Falló el entrenamiento del modelo baseline.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("train_baseline_model", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

"""
ML — Modelo avanzado: XGBoost sobre las mismas 5 features de `t062`
(`t063`)

Reutiliza `s3a://gold/ml_features_baseline/` (escrita por
`train_baseline_model.py`, `t062`) sin recalcular el join — mismas 5
features, mismo split `train`/`test`, para que la comparación contra
el baseline sea directa y justa.

Por qué XGBoost en pandas y no `xgboost4j-spark` (distribuido):
  181,081 filas x 5 columnas caben cómodas en memoria (unos pocos MB)
  — no hay volumen real que justifique el camino distribuido, que
  además es más frágil de configurar aquí (requeriría un paquete
  adicional vía `--packages`, con compatibilidad de versión
  Scala/Spark/XGBoost4J que mantener). Se usa Spark solo para LEER el
  Parquet desde MinIO (mismo patrón `s3a://` de todo el proyecto);
  el entrenamiento en sí corre en pandas + `xgboost` puro, en el
  driver. Instalado en `Dockerfile.airflow` (Sesión 32) — a diferencia
  del conector S3A, esto SÍ requirió reconstruir la imagen (`import
  xgboost` ocurre del lado de Python, no es un JAR resoluble por
  Spark).

Desbalance de clases: mismo CRITERIO que `t062` (compensar por
frecuencia inversa, calculado SOLO con `train`), pero no la misma
FÓRMULA — cada librería espera un parámetro distinto.
`LogisticRegression.weightCol` (t062) pedía un peso por fila;
`XGBClassifier` usa `scale_pos_weight` (un solo escalar, aplicado
únicamente a la clase positiva) = `n_negativos_train / n_positivos_train`.
Documentado aquí para que no se lea como una inconsistencia entre
scripts — es la forma estándar de cada librería, no un criterio
distinto.

Fuga de datos en loan_int_rate_norm para loan_default (hallazgo real,
Sesión 32 — historial completo en `train_baseline_model.py`,
`prepare_loan_default_proxies()`): la primera corrida de este script
dio AUC~0.96 con `loan_int_rate_norm` concentrando 58.6% de la
importancia; un primer intento de corrección (exponer el flag de
imputación como feature aparte) lo empeoró a AUC~0.996 con 92.8% de
importancia en ese flag. El diagnóstico decisivo
(`peek_imputation_leakage.py`) confirmó fuga de datos real: dentro de
CADA `loan_type`, el flag de imputación predice el default con 100%
de exactitud — 99.45% de los defaults reales de `loan_default` caen
exactamente en las filas con el dato imputado. Es un artefacto del
dataset original de Kaggle, no señal financiera ni proxy de
`loan_type`. Corrección final: `loan_int_rate_norm` neutro para el
100% de `loan_default` (real solo en `credit_risk`, confirmado
limpio). Este script usa `ml_features_baseline` ya con la corrección
final — hay que reconstruirla (`t062`) antes de volver a correr esto.
PENDIENTE para el mentor, no resuelto aquí: el IRFI de
`calculate_kpis.py` (Fase 4, ya aprobada) usa el mismo
`loan_int_rate_norm` sin neutralizar, con peso real — probablemente
tiene esta misma fuga.

Alcance de `t063` (para no invadir `t064`/`t065`/`t066`):
  Entrena la población "genérica" (igual que `t062`, sin filtrar por
  segmento) con hiperparámetros razonables fijados a mano (sin grid
  search / tuning extenso — no estaba en el alcance pedido; si hace
  falta optimizarlos, es una tarea aparte, no implícita en "avanzado").
  Reporta las mismas métricas que `t062` (AUC, F1, matriz de
  confusión) para comparación directa, más `feature_importances_`
  (equivalente no lineal a los coeficientes de `t062`). NO serializa
  el modelo (`t066`). NO entrena la variante segmentada `<30` (`t065`).

Lee:
    s3a://gold/ml_features_baseline/  (t062 — ya tiene las 5 features
    + split_set ensamblados, no se recalcula nada aquí)

Escribe:
    Nada — igual que `t062`, esta corrida solo imprime métricas al
    log. `t066` decide qué modelo (baseline o avanzado, genérico o
    segmentado) se serializa, una vez comparados en `t064`/`t065`.

Uso (dentro del contenedor de Airflow, DESPUÉS de reconstruir la
imagen con xgboost/scikit-learn/pandas — ver Dockerfile.airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/train_advanced_model.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import logging
import os
import sys
import time

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from sklearn.metrics import confusion_matrix, f1_score, roc_auc_score
from xgboost import XGBClassifier
from pipeline_timing import log_execution

GOLD_ML_FEATURES_PATH = "s3a://gold/ml_features_baseline/"

FEATURE_COLUMNS = [
    "credit_score_norm",
    "debt_to_income_norm",
    "income_monthly_norm",
    "loan_int_rate_norm",
    "neg_amortization_flag",
]
LABEL_COLUMN = "default_flag_unificada"

# Hiperparámetros fijados a mano, sin tuning (ver docstring, alcance
# de t063). Valores conservadores y comunes para un dataset chico
# (181K filas, 5 features): profundidad baja para no sobreajustar con
# tan pocas columnas, learning_rate moderado compensado con más
# árboles.
XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.1,
    "eval_metric": "logloss",
    "random_state": 42,  # mismo criterio de semilla fija que t061 (seed=42)
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("train_advanced_model")


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
        SparkSession.builder.appName("train_advanced_model")
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


def load_train_test_pandas(spark: SparkSession) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee ml_features_baseline (Spark, s3a://) y devuelve (train, test)
    como pandas — única conversión Spark->pandas del script, sobre una
    tabla ya chica (181,081 filas x 10 columnas)."""
    df_spark = spark.read.parquet(GOLD_ML_FEATURES_PATH)
    total_rows = df_spark.count()
    logger.info("ml_features_baseline leída: %s filas", total_rows)

    # Cast explícito a double ANTES de toPandas(): algunas de estas
    # columnas llegan como DecimalType desde Spark (mismo TYPING_RULES
    # del proyecto para montos/ratios financieros — ver
    # silver_transformations.py). Vía Arrow, DecimalType se mapea a
    # `object` (Python Decimal) en pandas, no a float, y XGBoost
    # rechaza `object` (hallazgo real, Sesión 32 — no se sabía antes de
    # correr esto). VectorAssembler de Spark ML (t062) no tiene este
    # problema porque no pasa por Arrow/pandas.
    df_pandas = df_spark.select(
        "split_set",
        col(LABEL_COLUMN).cast("double").alias(LABEL_COLUMN),
        *[col(c).cast("double").alias(c) for c in FEATURE_COLUMNS],
    ).toPandas()

    df_train = df_pandas[df_pandas["split_set"] == "train"].reset_index(drop=True)
    df_test = df_pandas[df_pandas["split_set"] == "test"].reset_index(drop=True)
    logger.info(
        "Convertido a pandas: train=%s filas, test=%s filas",
        len(df_train),
        len(df_test),
    )
    return df_train, df_test


def train_and_evaluate(df_train: pd.DataFrame, df_test: pd.DataFrame) -> None:
    n_pos = (df_train[LABEL_COLUMN] == 1.0).sum()
    n_neg = (df_train[LABEL_COLUMN] == 0.0).sum()
    scale_pos_weight = n_neg / n_pos
    logger.info(
        "Distribución de clases en train: 0.0=%s, 1.0=%s -> scale_pos_weight=%.4f",
        n_neg,
        n_pos,
        scale_pos_weight,
    )

    model = XGBClassifier(scale_pos_weight=scale_pos_weight, **XGB_PARAMS)
    model.fit(df_train[FEATURE_COLUMNS], df_train[LABEL_COLUMN])

    logger.info("--- Importancia de features (gain, equivalente no lineal a t062) ---")
    for feature_name, importance in zip(FEATURE_COLUMNS, model.feature_importances_):
        logger.info("  %s: %.4f", feature_name, importance)

    for split_name, df_split in [("train", df_train), ("test", df_test)]:
        y_true = df_split[LABEL_COLUMN]
        y_proba = model.predict_proba(df_split[FEATURE_COLUMNS])[:, 1]
        y_pred = model.predict(df_split[FEATURE_COLUMNS])

        auc = roc_auc_score(y_true, y_proba)
        f1 = f1_score(y_true, y_pred)  # F1 binario de la clase 1.0 (default) —
        # NO weighted como en t062: aquí interesa directo el desempeño
        # sobre la clase de interés, sin que la clase mayoritaria lo
        # infle (ver hallazgo de t062 sobre F1 weighted engañoso).
        cm = confusion_matrix(y_true, y_pred)

        logger.info("--- Métricas en %s ---", split_name)
        logger.info("  AUC: %.4f", auc)
        logger.info("  F1 (clase default=1, no weighted): %.4f", f1)
        logger.info("  Matriz de confusión [[TN, FP], [FN, TP]]:")
        logger.info("  %s", cm.tolist())


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo ml_features_baseline y convirtiendo a pandas...")
        df_train, df_test = load_train_test_pandas(spark)

        logger.info("Entrenando XGBoost (población genérica, train completo)...")
        train_and_evaluate(df_train, df_test)

        logger.info("t063 completado.")
    except Exception:
        status = "failed"
        logger.exception("Falló el entrenamiento del modelo avanzado.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("train_advanced_model", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

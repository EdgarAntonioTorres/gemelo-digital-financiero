"""
ML — Comparar modelo segmentado (<30, solo credit_risk) vs. modelo
genérico sin segmentar

Decisión de diseño (con el alumno, Sesión 33): se entrena un modelo
GENÉRICO (igual que `t063`/`t064`, con todo `train`) y un modelo
SEGMENTADO (mismo algoritmo, solo con las filas
`es_segmento_prioritario_lt30 == True` de `train`) — no al revés
(entrenar solo con `<30` como candidato a producción). Razón: un
modelo entrenado solo con `<30` no podría dar recomendaciones para
`established` ni para `loan_default` (que ni siquiera tiene el
segmento definido, ver `t061`) — sería inútil para el resto de la
base de usuarios. El genérico sí sirve para todos. El segmentado se
entrena únicamente para responder la pregunta de investigación:
¿especializar mejora tanto la predicción para `<30` que valdría la
pena mantener 2 modelos en producción?

Solo XGBoost (no se repite Logistic Regression aquí): `t064` ya
mostró una diferencia clara y consistente a favor de XGBoost en las
4 métricas — no hay ambigüedad que amerite repetir la comparación de
algoritmos, este script compara POBLACIONES de entrenamiento, no
algoritmos.

Comparación justa: ambos modelos (genérico y segmentado) se evalúan
en el MISMO subconjunto — `test` filtrado a `es_segmento_prioritario_lt30
== True` únicamente. Es la única forma de saber si especializar ayuda,
sin que el genérico "pierda" solo por incluir población que el
segmentado nunca vio. Además, se reporta cómo le va al genérico en el
resto de la población (`established` + `loan_default`) — el
segmentado no se evalúa ahí porque sería comparar contra una
distribución que nunca vio, no aporta información real.

Alcance de `t065`:
  Solo compara y recomienda con datos — NO decide unilateralmente cuál
  modelo va a producción (esa es una decisión de negocio/mentor, este
  script da el insumo). NO serializa nada.

Lee:
    s3a://gold/ml_features_baseline/  (t062, con es_segmento_prioritario_lt30)

Uso:
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/compare_segmented_vs_generic.py

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
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
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
SEGMENTO_COLUMN = "es_segmento_prioritario_lt30"

# Mismos hiperparámetros que t063/t064 — se compara población de
# entrenamiento, no algoritmo, así que se mantiene todo lo demás fijo.
XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.1,
    "eval_metric": "logloss",
    "random_state": 42,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("compare_segmented_vs_generic")


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
        SparkSession.builder.appName("compare_segmented_vs_generic")
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
    """Mismo patrón que t063/t064: cast explícito a double antes de
    toPandas()."""
    df_spark = spark.read.parquet(GOLD_ML_FEATURES_PATH)
    df_pandas = df_spark.select(
        "split_set",
        SEGMENTO_COLUMN,
        col(LABEL_COLUMN).cast("double").alias(LABEL_COLUMN),
        *[col(c).cast("double").alias(c) for c in FEATURE_COLUMNS],
    ).toPandas()

    df_train = df_pandas[df_pandas["split_set"] == "train"].reset_index(drop=True)
    df_test = df_pandas[df_pandas["split_set"] == "test"].reset_index(drop=True)
    return df_train, df_test


def train_xgboost(df_train: pd.DataFrame) -> XGBClassifier:
    n_pos = (df_train[LABEL_COLUMN] == 1.0).sum()
    n_neg = (df_train[LABEL_COLUMN] == 0.0).sum()
    scale_pos_weight = n_neg / n_pos if n_pos > 0 else 1.0
    model = XGBClassifier(scale_pos_weight=scale_pos_weight, **XGB_PARAMS)
    model.fit(df_train[FEATURE_COLUMNS], df_train[LABEL_COLUMN])
    return model


def evaluate_on(model: XGBClassifier, df_eval: pd.DataFrame, label: str) -> None:
    y_true = df_eval[LABEL_COLUMN]
    y_proba = model.predict_proba(df_eval[FEATURE_COLUMNS])[:, 1]
    y_pred = model.predict(df_eval[FEATURE_COLUMNS])
    auc = roc_auc_score(y_true, y_proba)
    f1 = f1_score(y_true, y_pred)
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall = recall_score(y_true, y_pred, zero_division=0)
    cm = confusion_matrix(y_true, y_pred).tolist()
    logger.info(
        "  [%s] filas=%s AUC=%.4f F1=%.4f Precision=%.4f Recall=%.4f",
        label,
        len(df_eval),
        auc,
        f1,
        precision,
        recall,
    )
    logger.info("    Matriz de confusión [[TN, FP], [FN, TP]]: %s", cm)


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo ml_features_baseline y convirtiendo a pandas...")
        df_train, df_test = load_train_test_pandas(spark)

        df_train_segmento = df_train[df_train[SEGMENTO_COLUMN].eq(True)]
        df_test_segmento = df_test[df_test[SEGMENTO_COLUMN].eq(True)]
        df_test_resto = df_test[df_test[SEGMENTO_COLUMN].eq(False)]

        logger.info(
            "Población <30 (credit_risk, early_career): train=%s (%.1f%% del "
            "train total), test=%s",
            len(df_train_segmento),
            100 * len(df_train_segmento) / len(df_train),
            len(df_test_segmento),
        )

        logger.info("--- Entrenando modelo GENÉRICO (train completo) ---")
        modelo_generico = train_xgboost(df_train)

        logger.info(
            "--- Entrenando modelo SEGMENTADO (solo <30 de credit_risk, " "train) ---"
        )
        modelo_segmentado = train_xgboost(df_train_segmento)

        logger.info(
            "--- Comparación justa: ambos modelos evaluados SOLO en el test " "<30 ---"
        )
        evaluate_on(modelo_generico, df_test_segmento, "GENÉRICO en test <30")
        evaluate_on(modelo_segmentado, df_test_segmento, "SEGMENTADO en test <30")

        logger.info(
            "--- Contexto: modelo GENÉRICO en el resto de la población "
            "(established + loan_default) ---"
        )
        evaluate_on(modelo_generico, df_test_resto, "GENÉRICO en resto")

        logger.info(
            "--- Contexto: modelo GENÉRICO en TODO el test (referencia, "
            "mismo número que t064) ---"
        )
        evaluate_on(modelo_generico, df_test, "GENÉRICO en test completo")

        logger.info("Completado.")
    except Exception:
        status = "failed"
        logger.exception("Falló la comparación segmentado vs. genérico.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("compare_segmented_vs_generic", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

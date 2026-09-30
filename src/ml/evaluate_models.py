"""
ML — Evaluación comparativa: AUC, F1, importancia de variables,
Logistic Regression (`t062`) vs. XGBoost (`t063`) (`t064`)

Por qué reentrena en vez de reusar los modelos de t062/t063
directamente: esos 2 scripts viven en frameworks distintos (PySpark
ML vs. pandas/XGBoost), cada uno con sus propias funciones de
métricas — ya documentamos en t063 que el F1 de uno (weighted,
default de PySpark) y el del otro (binario, sklearn) NO son
comparables tal cual. Para una comparación real, este script reentrena
AMBOS modelos dentro de un solo framework (pandas + scikit-learn +
xgboost), con los MISMOS hiperparámetros/criterio de balanceo ya
validados:
  - Logistic Regression: `class_weight="balanced"` de scikit-learn —
    misma fórmula matemática que el `weightCol` calculado a mano en
    t062 (`n_total / (n_clases · n_clase)`), aplicada directamente.
  - XGBoost: idéntico a t063 (`scale_pos_weight`, mismos
    hiperparámetros — ver XGB_PARAMS).

Este script es la fuente OFICIAL de comparación para `t065`. Los
números que imprimieron `t062`/`t063` en su momento sirvieron para
desarrollo y sanity-check individual, no para comparar entre sí.

Alcance de `t064` (para no invadir `t065`/`t066`):
  Solo evalúa y reporta — AUC, F1, precisión/recall de la clase de
  interés, matriz de confusión, e importancia de variables (ambos
  modelos, población genérica sin filtrar por segmento). NO decide
  cuál modelo es "mejor" ni compara segmentado vs. genérico (`t065`).
  NO serializa nada (`t066`).

Lee:
    s3a://gold/ml_features_baseline/  (t062 — ya con la corrección de
    la fuga de datos aplicada, Sesión 33)

Uso:
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/evaluate_models.py

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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
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

# Mismos hiperparámetros que t063 — no se retunea aquí, este script
# evalúa, no reoptimiza.
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
logger = logging.getLogger("evaluate_models")


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
        SparkSession.builder.appName("evaluate_models")
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
    """Mismo patrón que t063: cast explícito a double antes de
    toPandas() (DecimalType -> object/Decimal rompe scikit-learn y
    XGBoost igual que rompía XGBoost solo)."""
    df_spark = spark.read.parquet(GOLD_ML_FEATURES_PATH)
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


def evaluate(y_true, y_pred, y_proba) -> dict:
    return {
        "auc": roc_auc_score(y_true, y_proba),
        "f1": f1_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred),
        "recall": recall_score(y_true, y_pred),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
    }


def log_metrics(model_name: str, split_name: str, metrics: dict) -> None:
    logger.info(
        "  [%s | %s] AUC=%.4f  F1=%.4f  Precision=%.4f  Recall=%.4f",
        model_name,
        split_name,
        metrics["auc"],
        metrics["f1"],
        metrics["precision"],
        metrics["recall"],
    )
    logger.info(
        "    Matriz de confusión [[TN, FP], [FN, TP]]: %s", metrics["confusion_matrix"]
    )


def train_logistic_regression(
    df_train: pd.DataFrame,
) -> tuple[LogisticRegression, StandardScaler]:
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(df_train[FEATURE_COLUMNS])
    model = LogisticRegression(class_weight="balanced", random_state=42)
    model.fit(X_train_scaled, df_train[LABEL_COLUMN])
    return model, scaler


def train_xgboost(df_train: pd.DataFrame) -> XGBClassifier:
    n_pos = (df_train[LABEL_COLUMN] == 1.0).sum()
    n_neg = (df_train[LABEL_COLUMN] == 0.0).sum()
    scale_pos_weight = n_neg / n_pos
    model = XGBClassifier(scale_pos_weight=scale_pos_weight, **XGB_PARAMS)
    model.fit(df_train[FEATURE_COLUMNS], df_train[LABEL_COLUMN])
    return model


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo ml_features_baseline y convirtiendo a pandas...")
        df_train, df_test = load_train_test_pandas(spark)

        logger.info("--- Entrenando Logistic Regression (equivalente a t062) ---")
        lr_model, scaler = train_logistic_regression(df_train)
        X_train_scaled = scaler.transform(df_train[FEATURE_COLUMNS])
        X_test_scaled = scaler.transform(df_test[FEATURE_COLUMNS])

        logger.info("--- Entrenando XGBoost (idéntico a t063) ---")
        xgb_model = train_xgboost(df_train)

        resultados = {}
        for model_name, model, X_train, X_test in [
            ("LogisticRegression", lr_model, X_train_scaled, X_test_scaled),
            ("XGBoost", xgb_model, df_train[FEATURE_COLUMNS], df_test[FEATURE_COLUMNS]),
        ]:
            for split_name, X, df_split in [
                ("train", X_train, df_train),
                ("test", X_test, df_test),
            ]:
                y_true = df_split[LABEL_COLUMN]
                y_proba = model.predict_proba(X)[:, 1]
                y_pred = model.predict(X)
                metrics = evaluate(y_true, y_pred, y_proba)
                resultados[(model_name, split_name)] = metrics
                log_metrics(model_name, split_name, metrics)

        logger.info("--- Importancia de variables ---")
        logger.info(
            "  Logistic Regression (coeficientes sobre features estandarizadas):"
        )
        for feature_name, coef in zip(FEATURE_COLUMNS, lr_model.coef_[0]):
            logger.info("    %s: %.4f", feature_name, coef)
        logger.info("  XGBoost (importancia por gain):")
        for feature_name, importance in zip(
            FEATURE_COLUMNS, xgb_model.feature_importances_
        ):
            logger.info("    %s: %.4f", feature_name, importance)

        logger.info("--- Resumen comparativo (test) ---")
        for model_name in ("LogisticRegression", "XGBoost"):
            m = resultados[(model_name, "test")]
            logger.info(
                "  %s: AUC=%.4f F1=%.4f Precision=%.4f Recall=%.4f",
                model_name,
                m["auc"],
                m["f1"],
                m["precision"],
                m["recall"],
            )

        logger.info("t064 completado.")
    except Exception:
        status = "failed"
        logger.exception("Falló la evaluación comparativa de modelos.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("evaluate_models", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

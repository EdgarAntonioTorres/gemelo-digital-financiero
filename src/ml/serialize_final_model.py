"""
ML — Serializar el modelo final: XGBoost genérico (`t066`)

Decisión final (con el alumno, Sesión 33, tras t064/t065):
  - Modelo: XGBoost genérico (no segmentado). t065 mostró que el
    segmentado gana por margen chico en `<30` (+0.016 AUC) usando 8x
    menos datos, y que el genérico ya rinde bien en ese segmento
    (AUC=0.8868) — no justifica mantener 2 modelos en producción. El
    genérico además es el único que sirve para `established` y
    `loan_default` (el segmentado sería inútil ahí).
  - Datos: se reentrena con TRAIN + TEST completos (no solo train).
    Ya se cumplió el propósito de tener un test separado — evaluar
    limpio en `t064`/`t065` — así que a partir de aquí más datos solo
    puede ayudar al modelo que va a producción. Práctica estándar:
    separar para evaluar, reentrenar con todo antes de servir.

Mismos hiperparámetros que `t063`/`t064`/`t065` (XGB_PARAMS) — no se
retunea aquí, esa decisión ya quedó cerrada, este script solo fija la
versión final.

Guarda 2 archivos junto al modelo (mismo criterio de trazabilidad que
`age_synthetic_flag`/`irfi_proxy_flag`: nunca dejar un artefacto sin
poder reconstruir cómo se generó):
  - modelo_riesgo_default.pkl: el modelo serializado (joblib).
  - modelo_riesgo_default_metadata.json: features usadas, hiperparámetros,
    fecha de entrenamiento, y las métricas de t064/t065 que motivaron
    la elección — para que cualquiera que abra el .pkl sepa de dónde
    salió sin tener que releer la Bitácora completa.

Lee:
    s3a://gold/ml_features_baseline/  (t062)

Escribe (filesystem local del contenedor, NO a MinIO/Postgres — el
README de src/ml ya establece que los modelos serializados viven bajo
/models, no versionados en git):
    /opt/airflow/src/ml/models/modelo_riesgo_default.pkl
    /opt/airflow/src/ml/models/modelo_riesgo_default_metadata.json

    Como ./src está montado como volumen (docker-compose.yml), esto
    también queda escrito directamente en el host, en
    src/ml/models/ — no hace falta copiar nada manualmente después de
    correr el script.

Uso:
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/ml/serialize_final_model.py

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from xgboost import XGBClassifier
from pipeline_timing import log_execution

GOLD_ML_FEATURES_PATH = "s3a://gold/ml_features_baseline/"
MODELS_DIR = Path("/opt/airflow/src/ml/models")
MODEL_PATH = MODELS_DIR / "modelo_riesgo_default.pkl"
METADATA_PATH = MODELS_DIR / "modelo_riesgo_default_metadata.json"

FEATURE_COLUMNS = [
    "credit_score_norm",
    "debt_to_income_norm",
    "income_monthly_norm",
    "loan_int_rate_norm",
    "neg_amortization_flag",
]
LABEL_COLUMN = "default_flag_unificada"

# Idénticos a t063/t064/t065 — decisión ya cerrada, no se retunea aquí.
XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.1,
    "eval_metric": "logloss",
    "random_state": 42,
}

# Métricas de referencia de t064/t065 (test, ANTES de este reentrenamiento
# final con train+test) — se guardan en la metadata como registro de por
# qué se eligió este modelo, no como métricas de ESTE artefacto exacto
# (que ya no tiene test propio, se entrenó con todo).
METRICAS_REFERENCIA_T064_T065 = {
    "t064_test_completo": {
        "auc": 0.8124,
        "f1": 0.6015,
        "precision": 0.5563,
        "recall": 0.6546,
    },
    "t065_test_segmento_lt30": {
        "auc": 0.8868,
        "f1": 0.6984,
        "precision": 0.6458,
        "recall": 0.7604,
    },
    "t065_test_resto_poblacion": {
        "auc": 0.7981,
        "f1": 0.5881,
        "precision": 0.5440,
        "recall": 0.6401,
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("serialize_final_model")


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
        SparkSession.builder.appName("serialize_final_model")
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


def load_full_dataset_pandas(spark: SparkSession) -> pd.DataFrame:
    """Lee TODA la población de modelado (train + test, sin filtrar
    por split_set) — ver docstring del módulo, decisión de reentrenar
    con todo para el modelo final."""
    df_spark = spark.read.parquet(GOLD_ML_FEATURES_PATH)
    df_pandas = df_spark.select(
        col(LABEL_COLUMN).cast("double").alias(LABEL_COLUMN),
        *[col(c).cast("double").alias(c) for c in FEATURE_COLUMNS],
    ).toPandas()
    return df_pandas


def main() -> None:
    spark = None
    status = "success"
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo ml_features_baseline COMPLETA (train+test)...")
        df_full = load_full_dataset_pandas(spark)
        logger.info("Población total: %s filas", len(df_full))

        n_pos = (df_full[LABEL_COLUMN] == 1.0).sum()
        n_neg = (df_full[LABEL_COLUMN] == 0.0).sum()
        scale_pos_weight = n_neg / n_pos
        logger.info(
            "Distribución de clases (todo el dataset): 0.0=%s, 1.0=%s -> "
            "scale_pos_weight=%.4f",
            n_neg,
            n_pos,
            scale_pos_weight,
        )

        logger.info("Entrenando modelo FINAL (XGBoost genérico, train+test)...")
        modelo_final = XGBClassifier(scale_pos_weight=scale_pos_weight, **XGB_PARAMS)
        modelo_final.fit(df_full[FEATURE_COLUMNS], df_full[LABEL_COLUMN])

        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        logger.info("Serializando modelo en: %s", MODEL_PATH)
        joblib.dump(modelo_final, MODEL_PATH)

        metadata = {
            "modelo": "XGBoost genérico (población completa, sin segmentar)",
            "decision_tomada": (
                "t065 mostró que el modelo segmentado <30 gana por margen "
                "chico (+0.016 AUC) usando 8x menos datos; no justifica "
                "mantener 2 modelos en producción. El genérico además es "
                "el único que sirve para established y loan_default."
            ),
            "feature_columns": FEATURE_COLUMNS,
            "label_column": LABEL_COLUMN,
            "hiperparametros": XGB_PARAMS,
            "scale_pos_weight_entrenamiento_final": scale_pos_weight,
            "filas_entrenamiento_final": len(df_full),
            "nota_datos_entrenamiento_final": (
                "Entrenado con TODO el dataset (train+test de t061), no "
                "solo train — el test ya cumplió su propósito de evaluar "
                "limpio en t064/t065. Las métricas de referencia abajo son "
                "de ESE entrenamiento (solo train), no de este modelo "
                "final, que no tiene test propio."
            ),
            "metricas_referencia_t064_t065": METRICAS_REFERENCIA_T064_T065,
            "features_excluidas_y_por_que": {
                "irfi_ica": "casi circulares, ya son combinación lineal "
                "de estos mismos componentes",
                "emp_stability_credit_hist_norm_housing_penalty": "0.5 constante en el 100%"
                "de loan_default, sin dato crudo detrás",
                "fuente_one_hot": "dejado fuera del baseline a propósito",
            },
            "hallazgo_critico_loan_int_rate_norm": (
                "loan_int_rate_norm es neutro (0.5) para el 100% de "
                "loan_default — se descubrió fuga de datos real en "
                "rate_of_interest_imputed_flag (Sesión 32-33, ver "
                "Bitácora). Real solo en credit_risk. Mismo componente "
                "usado en el IRFI de Fase 4 (calculate_kpis.py) SIN esta "
                "corrección — pendiente de validar con el mentor."
            ),
            "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
            "sesion": "Sesión 33 (2026-09-25)",
            "estado": "Finalizado, pendiente de aprobación explícita del mentor BBVA",
        }
        logger.info("Escribiendo metadata en: %s", METADATA_PATH)
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info("t066 completado.")
    except Exception:
        status = "failed"
        logger.exception("Falló la serialización del modelo final.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        log_execution("serialize_final_model", elapsed_seconds, status)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

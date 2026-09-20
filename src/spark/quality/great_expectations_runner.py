"""
Runner de Great Expectations — Fase 3.

Traduce las reglas declarativas de `expectations_config.py` a
expectativas de Great Expectations sobre un `SparkDFDataset`, corre la
validación y devuelve un resumen agregado (nunca filas individuales —
ver nota abajo sobre por qué la cuarentena fila a fila vive aparte,
en `quarantine.py`).

Se usa la API legacy `great_expectations.dataset.SparkDFDataset` (no
la API moderna de `DataContext`/Fluent Datasources) a propósito: para
un job de Spark que corre una sola vez dentro de un `spark-submit`
(sin proyecto GE persistente, sin Data Docs servidos), la API legacy
evita tener que mantener un `great_expectations.yml` completo solo
para 3 fuentes con ~8 reglas cada una. Si el proyecto creciera y
necesitara Data Docs / checkpoints versionados, esto se migraría a la
API de `DataContext` — no es necesario para el alcance.

Uso (dentro de build_silver_<fuente>.py, después de limpiar pero antes
de escribir a Silver):

    from great_expectations_runner import run_expectations

    summary = run_expectations(df_clean, "loan_default")
    logger.info("Calidad %s: %.1f%% de expectativas OK (%s/%s)",
                summary["source"], summary["pass_rate"] * 100,
                summary["passed"], summary["total"])
    if not summary["success"]:
        for f in summary["failed_expectations"]:
            logger.warning("Expectativa fallida: %s", f["description"])

Nota importante — por qué esto NO decide la cuarentena:
Great Expectations sobre Spark reporta agregados (cuántas filas violan
cada expectativa, `unexpected_percent`) pero no expone de forma
confiable un índice de fila reutilizable bajo un motor distribuido
(a diferencia de PandasDataset). Por eso `quarantine.py` reimplementa
las MISMAS reglas (desde el mismo `expectations_config.py`) como
condiciones nativas de Spark — este módulo es el "qué tan bien está
el dataset en conjunto" (para el reporte), no el "qué fila
individual se aparta".
"""

from __future__ import annotations

import logging
from typing import Any

from great_expectations.dataset import SparkDFDataset
from pyspark.sql import DataFrame

from expectations_config import QualityRule, get_rules, master_record_id_rules

logger = logging.getLogger(__name__)


def _apply_rule(gdf: SparkDFDataset, rule: QualityRule) -> dict[str, Any]:
    """Aplica una regla declarativa como expectativa de GE y devuelve
    su resultado crudo (dict de GE)."""
    rule_type = rule["type"]
    column = rule["column"]

    if rule_type == "not_null":
        result = gdf.expect_column_values_to_not_be_null(column)
    elif rule_type == "between":
        result = gdf.expect_column_values_to_be_between(
            column,
            min_value=rule.get("min"),
            max_value=rule.get("max"),
        )
    elif rule_type == "in_set":
        result = gdf.expect_column_values_to_be_in_set(column, rule["values"])
    elif rule_type == "unique":
        result = gdf.expect_column_values_to_be_unique(column)
    elif rule_type == "regex":
        result = gdf.expect_column_values_to_match_regex(column, rule["pattern"])
    else:
        raise ValueError(f"Tipo de regla no soportado: '{rule_type}'")

    return dict(result)


def run_expectations(
    df: DataFrame, source_name: str, on_master: bool = False
) -> dict[str, Any]:
    """Corre las expectativas de calidad de una fuente sobre `df`.

    Args:
        df: DataFrame Silver ya limpio (tipado, deduplicado, imputado,
            winsorizado) de la fuente indicada, o el dataset maestro
            si `on_master=True`.
        source_name: una de "loan_default", "credit_risk",
            "personal_finance_tracker".
        on_master: si True, valida las reglas de `record_id`
            (`master_record_id_rules()`) en vez de las reglas de
            columnas crudas — usar sobre el dataset ya unificado por
            `build_silver_master.py`, filtrado a `fuente == source_name`.

    Returns:
        dict con: source, total (nº de expectativas evaluadas),
        passed, failed, pass_rate (0-1), success (bool, todas
        pasaron), failed_expectations (lista de dicts con column,
        description, unexpected_count, unexpected_percent).
    """
    rules = master_record_id_rules(source_name) if on_master else get_rules(source_name)
    gdf = SparkDFDataset(df)

    failed_expectations: list[dict[str, Any]] = []
    passed = 0

    for rule in rules:
        raw_result = _apply_rule(gdf, rule)
        success = bool(raw_result.get("success"))
        if success:
            passed += 1
        else:
            result_details = raw_result.get("result", {}) or {}
            failed_expectations.append(
                {
                    "column": rule["column"],
                    "type": rule["type"],
                    "description": rule.get("description", ""),
                    "unexpected_count": result_details.get("unexpected_count"),
                    "unexpected_percent": result_details.get("unexpected_percent"),
                }
            )

    total = len(rules)
    summary = {
        "source": source_name,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total) if total else 1.0,
        "success": passed == total,
        "failed_expectations": failed_expectations,
    }

    logger.info(
        "Expectativas %s (%s): %s/%s OK (%.1f%%)",
        source_name,
        "master/record_id" if on_master else "columnas crudas",
        passed,
        total,
        summary["pass_rate"] * 100,
    )
    for fail in failed_expectations:
        logger.warning(
            "FALLO %s.%s: %s (unexpected_count=%s, unexpected_percent=%s)",
            source_name,
            fail["column"],
            fail["description"],
            fail["unexpected_count"],
            fail["unexpected_percent"],
        )

    return summary


if __name__ == "__main__":
    # Verificación manual, mismo espíritu que el bloque __main__ de
    # silver_transformations.py: no escribe nada, solo corre las
    # expectativas contra Silver ya escrito y muestra el resumen.
    import os

    from pyspark.sql import SparkSession

    def build_spark_session() -> SparkSession:
        spark = (
            SparkSession.builder.appName("verify_t045_expectations")
            .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
            .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
            .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
            .config(
                "spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem"
            )
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        return spark

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    SILVER_PATHS = {
        "loan_default": "s3a://silver/loan_default/",
        "credit_risk": "s3a://silver/credit_risk/",
        "personal_finance_tracker": "s3a://silver/personal_finance_tracker/",
    }

    spark = build_spark_session()
    try:
        for source, path in SILVER_PATHS.items():
            df_source = spark.read.parquet(path)
            run_expectations(df_source, source)
    finally:
        spark.stop()

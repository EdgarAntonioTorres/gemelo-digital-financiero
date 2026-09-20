"""
Cuarentena de registros inválidos — Fase 3.

Separa un DataFrame Silver en (válidas, cuarentena) según las MISMAS
reglas de `expectations_config.py` que usa `great_expectations_runner.py`
una sola fuente de verdad, ver docstring de ese módulo.

Por qué esto no usa los resultados de Great Expectations directamente:
`SparkDFDataset.validate()` da agregados (cuántas filas violan cada
expectativa) pero no un índice de fila fiable bajo el motor
distribuido de Spark para poder hacer `df.filter(fila en la lista de
GE)`. Reimplementar las reglas como condiciones de Spark (`when`/`col`)
es la forma estándar de resolver esto en pipelines Spark+GE reales:
GE audita "qué tan bien está el dataset", esta cuarentena decide "qué
fila se aparta, y por qué" fila a fila. No hay lógica de negocio nueva
aquí — es literalmente la misma regla de `expectations_config.py`,
solo evaluada con `pyspark.sql.functions` en vez de con expectativas
de GE.

Nota sobre "unique": una violación de unicidad no se puede detectar
mirando una fila sola (se necesita comparar contra el resto del
dataset). Se maneja aparte, marcando TODAS las filas que comparten un
valor duplicado como inválidas — no participa en `_row_passes()`.

Salida: 2 DataFrames (válidas, cuarentena). El caller decide dónde
escribir cada uno — ver `quarantine_and_write()` para el patrón
recomendado (mismo estilo que `build_silver_master.py`: la escritura
ocurre una sola vez, al final).
"""

from __future__ import annotations

import logging

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

from expectations_config import QualityRule, get_rules

logger = logging.getLogger(__name__)

QUARANTINE_PATHS = {
    "loan_default": "s3a://silver/quarantine/loan_default/",
    "credit_risk": "s3a://silver/quarantine/credit_risk/",
    "personal_finance_tracker": "s3a://silver/quarantine/personal_finance_tracker/",
}


def _condition_for_rule(rule: QualityRule) -> Column:
    """Traduce una regla declarativa a una condición de Spark que es
    True cuando la fila CUMPLE la regla (no cuando falla)."""
    rule_type = rule["type"]
    column = F.col(rule["column"])

    if rule_type == "not_null":
        return column.isNotNull()

    if rule_type == "between":
        condition = F.lit(True)
        if "min" in rule:
            condition = condition & (column >= F.lit(rule["min"]))
        if "max" in rule:
            condition = condition & (column <= F.lit(rule["max"]))
        # Un valor NULL nunca "pasa" un chequeo de rango por sí solo —
        # si la columna también tiene una regla `not_null` separada,
        # esa es la que debe reportarlo; aquí se documenta explícito
        # para no dejar que NULL <= max evalúe a NULL/None silencioso.
        return F.when(column.isNull(), F.lit(False)).otherwise(condition)

    if rule_type == "in_set":
        return column.isin(rule["values"])

    if rule_type == "regex":
        return column.rlike(rule["pattern"])

    if rule_type == "unique":
        # No se evalúa aquí — ver _mark_duplicates().
        return F.lit(True)

    raise ValueError(f"Tipo de regla no soportado en cuarentena: '{rule_type}'")


def _mark_duplicates(df: DataFrame, rules: list[QualityRule]) -> DataFrame:
    """Agrega `_dup_violation` = True para toda fila cuyo valor en una
    columna con regla `unique` se repita en el dataset."""
    df = df.withColumn("_dup_violation", F.lit(False))
    for rule in rules:
        if rule["type"] != "unique":
            continue
        column_name = rule["column"]
        dup_values = (
            df.groupBy(column_name)
            .count()
            .filter(F.col("count") > 1)
            .select(column_name)
        )
        df = df.withColumn(
            "_dup_violation",
            F.col("_dup_violation")
            | F.col(column_name).isin(
                [row[column_name] for row in dup_values.collect()]
            ),
        )
    return df


def quarantine(df: DataFrame, source_name: str) -> tuple[DataFrame, DataFrame]:
    """Separa `df` en (válidas, cuarentena) según las reglas de
    `expectations_config.py` para `source_name`.

    Agrega a AMBAS salidas la columna `_failure_reasons` (array de
    strings, vacío en las válidas) con la descripción de cada regla
    que la fila violó — para que la cuarentena sea explicable, no un
    balde genérico de "algo falló".
    """
    rules = get_rules(source_name)
    df = _mark_duplicates(df, rules)

    row_wise_rules = [r for r in rules if r["type"] != "unique"]

    # Una columna booleana + una razón (o NULL si pasa) por cada regla.
    reason_columns = []
    overall_pass = F.lit(True) & (~F.col("_dup_violation"))
    for rule in row_wise_rules:
        passes = _condition_for_rule(rule)
        reason_columns.append(
            F.when(~passes, F.lit(rule.get("description", rule["column"])))
        )
        overall_pass = overall_pass & passes

    dup_reason = F.when(
        F.col("_dup_violation"), F.lit("valor duplicado en columna única")
    )
    reason_columns.append(dup_reason)

    df = df.withColumn(
        "_failure_reasons",
        F.array_except(F.array(*reason_columns), F.array(F.lit(None).cast("string"))),
    )
    df = df.withColumn("_quality_valid", overall_pass).drop("_dup_violation")

    valid_df = df.filter(F.col("_quality_valid")).drop(
        "_quality_valid", "_failure_reasons"
    )
    invalid_df = df.filter(~F.col("_quality_valid")).drop("_quality_valid")

    valid_count = valid_df.count()
    invalid_count = invalid_df.count()
    total = valid_count + invalid_count
    pass_rate = (valid_count / total) if total else 1.0

    logger.info(
        "Cuarentena %s: %s válidas, %s en cuarentena de %s (%.1f%% OK)",
        source_name,
        valid_count,
        invalid_count,
        total,
        pass_rate * 100,
    )

    return valid_df, invalid_df


def quarantine_and_write(df: DataFrame, source_name: str) -> DataFrame:
    """Patrón recomendado para usar dentro de `build_silver_<fuente>.py`:
    separa, escribe la cuarentena a `s3a://silver/quarantine/<fuente>/`
    (modo overwrite, mismo criterio que el resto de Silver), y devuelve
    SOLO las filas válidas para que el script siga con su `write()`
    normal a Silver.

    No detiene el pipeline si hay registros en cuarentena — se registran
    y se dejan visibles para `t047` (reporte de % de validación), no
    para bloquear la corrida.
    """
    valid_df, invalid_df = quarantine(df, source_name)

    quarantine_path = QUARANTINE_PATHS[source_name]
    logger.info("Escribiendo cuarentena de %s en: %s", source_name, quarantine_path)
    invalid_df.write.mode("overwrite").option("compression", "snappy").parquet(
        quarantine_path
    )

    return valid_df

"""
Transformaciones Silver — módulo compartido.

Cada tarea de Fase 3 agrega sus propias funciones puras a este
módulo: reciben un DataFrame de Bronze y devuelven un DataFrame transformado,
SIN escribir nada a MinIO. La escritura real a `s3a://silver/` ocurre una
sola vez, al final de la cadena completa, en un script aparte
(build_silver_<fuente>.py) que encadena todas las funciones — así Silver
no queda "a medio cocinar" mientras se van resolviendo.

Tipado correcto (timestamps, decimales):
  1. `ingestion_timestamp` (las 3 fuentes): venía como `string` pese a ser
     una fecha-hora real, sin que nada le dijera a Spark que la
     tratara como tal. Se convierte a `timestamp` nativo.
  2. Columnas de dinero: Spark las infirió como `double` (binario, con
     imprecisión de redondeo — ej. 0.1 + 0.2 != 0.3 exacto). Se convierten
     a `DecimalType(18, 2)` (base 10 exacta, estándar en sistemas
     financieros/contables), decisión deliberada para un proyecto
     financiero, no solo un ejercicio de tipado.
  3. Columnas de tasa/ratio (porcentajes, proporciones): mismo problema de
     precisión que el dinero, pero con más decimales relevantes y montos
     más pequeños — se usa `DecimalType(10, 4)` en vez de `DecimalType(18, 2)`.

No se tocan (fuera de alcance, resuelto en tareas posteriores):
  - Nulos (`dtir1` 16% nulos, etc.).
  - Outliers (`person_income` ~90x la media, etc.).
  - Bins de `age` en Loan Default (categórico por diseño del dataset,
    no es un tipo "incorrecto").
  - Columnas hipotecarias/administrativas que se descartan del núcleo
    maestro (5.2.2 del Contexto Maestro). Aquí se tipan igual
    porque siguen existiendo en Bronze/Silver por fuente.
"""

from pyspark.sql import DataFrame
from pyspark.sql.functions import coalesce, col, to_timestamp
from pyspark.sql.types import DecimalType

# Precisión/escala para columnas de dinero (montos) vs. tasas/ratios.
# 18 dígitos totales / 2 decimales: suficiente para cualquier monto real
# de este proyecto (ingresos, préstamos) sin desperdiciar espacio.
MONETARY_DECIMAL = DecimalType(18, 2)
# 10 dígitos totales / 4 decimales: tasas de interés y ratios necesitan
# más precisión decimal relativa (ej. 0.0399 = 3.99%) aunque el monto
# absoluto sea pequeño.
RATIO_DECIMAL = DecimalType(10, 4)

# Dos formatos porque datetime.isoformat() en Python omite los
# microsegundos cuando son exactamente 0 (caso raro pero posible) —
# coalesce() prueba el primero y si no matchea (devuelve NULL) intenta
# el segundo, sin arriesgar convertir filas válidas en NULL por accidente.
_TS_FORMAT_CON_MICROS = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX"
_TS_FORMAT_SIN_MICROS = "yyyy-MM-dd'T'HH:mm:ssXXX"

# Mapeo por fuente: qué columnas son dinero vs. tasa/ratio.
# Basado en el schema real de Bronze (confirmado con dump_schema_bronze.py,
# 2026-08-26) y en la semántica de cada columna documentada en el
# Contexto Maestro (§5, §5.2, §8 variables candidatas).
TYPING_RULES = {
    "loan_default": {
        "monetary": ["loan_amount", "Upfront_charges", "property_value", "income"],
        "ratio": ["rate_of_interest", "Interest_rate_spread", "LTV", "dtir1"],
    },
    "credit_risk": {
        "monetary": ["person_income", "loan_amnt"],
        "ratio": ["loan_int_rate", "loan_percent_income"],
    },
    "personal_finance_tracker": {
        "monetary": [
            "monthly_income",
            "monthly_expense_total",
            "budget_goal",
            "loan_payment",
            "investment_amount",
            "emergency_fund",
            "discretionary_spending",
            "essential_spending",
            "rent_or_mortgage",
            "actual_savings",
        ],
        "ratio": ["savings_rate", "debt_to_income_ratio"],
    },
}


def _cast_ingestion_timestamp(df: DataFrame) -> DataFrame:
    """Convierte `ingestion_timestamp` de string ISO 8601 a timestamp real."""
    return df.withColumn(
        "ingestion_timestamp",
        coalesce(
            to_timestamp(col("ingestion_timestamp"), _TS_FORMAT_CON_MICROS),
            to_timestamp(col("ingestion_timestamp"), _TS_FORMAT_SIN_MICROS),
        ),
    )


def _cast_decimal_columns(
    df: DataFrame, columns: list[str], target_type: DecimalType
) -> DataFrame:
    """Convierte una lista de columnas numéricas (double/int) a DecimalType."""
    for column_name in columns:
        df = df.withColumn(column_name, col(column_name).cast(target_type))
    return df


def apply_typing(df: DataFrame, source_name: str) -> DataFrame:
    """Aplica el tipado correcto a un DataFrame de Bronze de una fuente.

    Args:
        df: DataFrame leído directamente de Bronze (schema crudo, inferido
            por Spark en la ingesta).
        source_name: una de "loan_default", "credit_risk",
            "personal_finance_tracker" — determina qué columnas de dinero
            y de ratio se convierten a DecimalType.

    Returns:
        El mismo DataFrame con `ingestion_timestamp` como timestamp real
        y las columnas de dinero/ratio como DecimalType. El resto de las
        columnas queda sin tocar (su tipo inferido por Spark ya era
        correcto — ver docstring del módulo).
    """
    if source_name not in TYPING_RULES:
        raise ValueError(
            f"Fuente desconocida: '{source_name}'. Debe ser una de: "
            f"{list(TYPING_RULES.keys())}"
        )

    rules = TYPING_RULES[source_name]
    df = _cast_ingestion_timestamp(df)
    df = _cast_decimal_columns(df, rules["monetary"], MONETARY_DECIMAL)
    df = _cast_decimal_columns(df, rules["ratio"], RATIO_DECIMAL)
    return df


# ==============================================================================
# Verificación manual (NO escribe a Silver — solo confirma que el tipado
# se aplicó correctamente, leyendo la partición de hoy de cada fuente).
# ==============================================================================
if __name__ == "__main__":
    import os

    from pyspark.sql import SparkSession

    def build_spark_session() -> SparkSession:
        spark = (
            SparkSession.builder.appName("verify_t038_typing")
            .config("spark.hadoop.fs.s3a.endpoint", os.environ["MINIO_ENDPOINT"])
            .config("spark.hadoop.fs.s3a.access.key", os.environ["MINIO_ACCESS_KEY"])
            .config("spark.hadoop.fs.s3a.secret.key", os.environ["MINIO_SECRET_KEY"])
            .config("spark.hadoop.fs.s3a.path.style.access", "true")
            .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
            .config(
                "spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem"
            )
            .config("spark.sql.parquet.mergeSchema", "true")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        return spark

    BRONZE_PATHS = {
        "loan_default": "s3a://bronze/loan_default/",
        "credit_risk": "s3a://bronze/credit_risk/",
        "personal_finance_tracker": "s3a://bronze/personal_finance_tracker/",
    }

    spark = build_spark_session()
    try:
        for source, path in BRONZE_PATHS.items():
            print(
                f"\n=== {source}: valores crudos de ingestion_timestamp por partición ==="
            )
            df_raw = spark.read.parquet(path)
            df_raw.select("ingestion_date", "ingestion_timestamp").distinct().orderBy(
                "ingestion_date"
            ).show(truncate=False)

            df_typed = apply_typing(df_raw, source)

            # Verificación de que no se perdieron filas al castear
            # ingestion_timestamp (si el coalesce no matcheara ningún
            # formato, la fila quedaría con NULL en vez de fallar).
            nulos_ts = df_typed.filter(col("ingestion_timestamp").isNull()).count()
            print(f"Filas con ingestion_timestamp NULL tras el cast: {nulos_ts}")
    finally:
        spark.stop()

"""
Smoke test: confirma que las 3 fuentes en Bronze son legibles desde PySpark,
que traen el schema esperado (incl. columnas de trazabilidad), y que el
conteo de filas coincide con el tamaño conocido de cada dataset.

Lee el histórico COMPLETO de cada fuente (todas las particiones de
ingestion_date, no solo la de hoy) con mergeSchema=true, ya que conviven
particiones viejas (sin las 3 columnas de trazabilidad agregadas)
con las nuevas — sin mergeSchema, Spark puede tomar el schema de un
archivo viejo y las columnas nuevas no aparecerían en el DataFrame
aunque sí estén escritas físicamente.

Uso (dentro del contenedor de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        /opt/airflow/src/spark/smoke_test_bronze.py

Variables de entorno requeridas (mismas que los scripts de ingesta):
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY

Ubicación: src/spark/smoke_test_bronze.py
"""

import logging
import os

from pyspark.sql import SparkSession

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# path Bronze -> filas esperadas POR PARTICIÓN de ingestion_date (tamaño real
# conocido de cada dataset, confirmado para loan_default y en los
# logs de ingesta para las otras 2). No es el total acumulado:
# Bronze conserva el histórico de todas las corridas, así que cada
# partición diaria debe tener este tamaño, pero el total crece con los días.
BRONZE_SOURCES = {
    "loan_default": {"path": "s3a://bronze/loan_default/", "filas_esperadas": 148670},
    "credit_risk": {"path": "s3a://bronze/credit_risk/", "filas_esperadas": 32581},
    "personal_finance_tracker": {
        "path": "s3a://bronze/personal_finance_tracker/",
        "filas_esperadas": 3000,
    },
}

TRAZABILIDAD_COLS = {
    "ingestion_date",
    "ingestion_timestamp",
    "source_file",
    "dag_run_id",
}


def get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o falla con un mensaje claro.

    Mismo patrón que get_required_env() en los scripts de ingesta
    (ingest_credit_risk.py, etc.) — falla explícita y temprana si falta
    alguna variable de MinIO, en vez de dejar que Spark falle más abajo
    con un error de credenciales menos claro.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Crea la sesión de Spark configurada para hablar con MinIO vía S3A.

    Misma configuración que build_spark_session() en los scripts de
    ingesta (endpoint/access.key/secret.key de MinIO, path-style access,
    SSL deshabilitado en local, driver S3AFileSystem), más
    mergeSchema=true para poder leer el histórico completo de Bronze
    con particiones de schema distinto (ver docstring del módulo).
    """
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("smoke_test_bronze")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.sql.parquet.mergeSchema", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def main() -> None:
    spark = None
    try:
        spark = build_spark_session()
        resultados = {}
        fallos = []

        for nombre, cfg in BRONZE_SOURCES.items():
            path = cfg["path"]
            esperadas = cfg["filas_esperadas"]

            logger.info("Leyendo %s desde %s", nombre, path)
            df = spark.read.parquet(path)

            cols_presentes = set(df.columns)
            faltantes = TRAZABILIDAD_COLS - cols_presentes

            # Se valida CADA partición de ingestion_date por separado, no el
            # total acumulado — Bronze conserva el histórico de todas las
            # corridas, así que el total crece con cada día que
            # pasa. Lo que debe mantenerse constante es el tamaño de CADA
            # corrida individual (una descarga completa del dataset por día).
            conteo_por_particion = df.groupBy("ingestion_date").count().collect()
            particiones = {
                row["ingestion_date"]: row["count"] for row in conteo_por_particion
            }
            particiones_mal = {
                fecha: filas
                for fecha, filas in particiones.items()
                if filas != esperadas
            }

            resultados[nombre] = {
                "particiones_encontradas": len(particiones),
                "filas_esperadas_por_particion": esperadas,
                "columnas": len(cols_presentes),
                "trazabilidad_ok": not faltantes,
                "trazabilidad_faltante": faltantes,
                "particiones_con_conteo_incorrecto": particiones_mal,
            }

            logger.info(
                "%s -> %s particiones encontradas, %s filas/partición esperadas, "
                "%s columnas, trazabilidad_ok=%s",
                nombre,
                len(particiones),
                esperadas,
                len(cols_presentes),
                not faltantes,
            )

            if faltantes:
                logger.warning(
                    "Faltan columnas de trazabilidad en %s: %s", nombre, faltantes
                )
                fallos.append(f"{nombre}: faltan columnas de trazabilidad {faltantes}")

            if particiones_mal:
                logger.warning(
                    "%s tiene particiones con conteo incorrecto: %s",
                    nombre,
                    particiones_mal,
                )
                fallos.append(
                    f"{nombre}: particiones con conteo != {esperadas}: {particiones_mal}"
                )

        logger.info("=== Resumen smoke test Bronze ===")
        for nombre, r in resultados.items():
            logger.info("%s: %s", nombre, r)

        if fallos:
            raise AssertionError("Smoke test Bronze FALLÓ:\n" + "\n".join(fallos))

        logger.info(
            "Smoke test OK — 3 fuentes legibles, schema y conteos por partición esperados."
        )
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

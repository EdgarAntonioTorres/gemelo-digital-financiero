"""
Ingesta Bronze — Personal Finance Tracker Dataset

Descarga el dataset desde Kaggle vía kagglehub y lo escribe crudo,
sin transformaciones, a la capa Bronze en MinIO en formato Parquet.

El particionado por fecha de ingesta y el manejo de errores más
fino se agregan en tareas siguientes; este script cubre el
camino feliz de descarga + escritura, con logging básico y overwrite
idempotente sobre el path completo.

Uso standalone (para probarlo suelto antes de envolverlo en el DAG):
    spark-submit src/spark/ingest_personal_finance_tracker.py

Variables de entorno requeridas (ya definidas en docker-compose.yml):
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
"""

# ==============================================================================
# 1. IMPORTACIÓN DE LIBRERÍAS Y CONFIGURACIÓN INICIAL
# ==============================================================================
# Módulos del sistema y logging
import logging
import os
import sys

# Módulos de descarga de Kaggle y SparkSession
import kagglehub
from pyspark.sql import SparkSession

# Parámetros del dataset Personal Finance Tracker y ruta destino
KAGGLE_DATASET = "khushikyad001/personal-finance-tracker-dataset"
BRONZE_PATH = "s3a://bronze/personal_finance_tracker/"

# Configuración del logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_personal_finance_tracker")


# ==============================================================================
# 2. VALIDACIÓN DE ENTORNO Y CONEXIÓN
# ==============================================================================
def get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o falla con un mensaje claro."""
    # Validación de variables de entorno para autenticación S3
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Crea la sesión de Spark configurada para hablar con MinIO vía S3A."""
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    # Instanciación de SparkSession con el driver S3A configurado para MinIO
    spark = (
        SparkSession.builder.appName("ingest_personal_finance_tracker_bronze")
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


# ==============================================================================
# 3. EXTRACCIÓN (DESCARGA DESDE FUENTE)
# ==============================================================================
def download_dataset() -> str:
    """Descarga el dataset desde Kaggle vía kagglehub y devuelve la ruta local del CSV."""
    logger.info("Descargando dataset '%s' desde Kaggle...", KAGGLE_DATASET)
    # Descarga desde Kaggle
    dataset_dir = kagglehub.dataset_download(KAGGLE_DATASET)
    logger.info("Dataset descargado en: %s", dataset_dir)

    # Identificación del archivo CSV resultante
    csv_files = [f for f in os.listdir(dataset_dir) if f.lower().endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError(
            f"No se encontró ningún .csv en {dataset_dir} tras la descarga de kagglehub."
        )
    if len(csv_files) > 1:
        logger.warning(
            "Se encontraron varios CSV (%s); se usará el primero: %s",
            csv_files,
            csv_files[0],
        )
    return os.path.join(dataset_dir, csv_files[0])


# ==============================================================================
# 4. INGESTA, VALIDACIÓN DE ESQUEMA Y PERSISTENCIA (RAW A BRONZE)
# ==============================================================================
def ingest(spark: SparkSession, csv_path: str) -> None:
    """Lee el CSV crudo y lo escribe tal cual a Bronze, sin transformar columnas."""
    logger.info("Leyendo CSV crudo desde: %s", csv_path)
    # Lectura del archivo CSV crudo
    df = spark.read.csv(csv_path, header=True, inferSchema=True)

    row_count = df.count()
    col_count = len(df.columns)
    logger.info("Filas leídas: %s | Columnas: %s", row_count, col_count)

    # Validación de integridad: archivo no vacío
    if row_count == 0:
        raise ValueError("El CSV descargado está vacío — abortando la ingesta.")

    # Chequeo suave (Data Quality / Drift check):
    # Compara contra la dimensionalidad base documentada (3000x25). Emite warning sin frenar ejecución.
    if row_count != 3000 or col_count != 25:
        logger.warning(
            "Dimensiones distintas a las documentadas (3000x25): %s filas x %s columnas. "
            "Verificar si el dataset fuente cambió.",
            row_count,
            col_count,
        )

    # Persistencia en formato Parquet comprimido con snappy
    logger.info("Escribiendo a Bronze en: %s", BRONZE_PATH)
    df.write.mode("overwrite").option("compression", "snappy").parquet(BRONZE_PATH)
    logger.info("Ingesta completada: %s filas escritas en %s", row_count, BRONZE_PATH)


# ==============================================================================
# 5. ORQUESTACIÓN Y MANEJO DEL CICLO DE VIDA
# ==============================================================================
def main() -> None:
    spark = None
    try:
        # Pipeline de ejecución principal
        spark = build_spark_session()
        csv_path = download_dataset()
        ingest(spark, csv_path)
    except Exception:
        # Registro de errores críticos en log
        logger.exception("Falló la ingesta de Personal Finance Tracker a Bronze.")
        sys.exit(1)
    finally:
        # Limpieza y cierre seguro de Spark
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()
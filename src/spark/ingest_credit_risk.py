"""
Ingesta Bronze — Credit Risk Dataset

Descarga el dataset desde Kaggle vía kagglehub y lo escribe crudo,
sin transformaciones, a la capa Bronze en MinIO en formato Parquet.

El particionado por fecha de ingesta y el manejo de errores más
fino se agregan en tareas siguientes; este script cubre el
camino feliz de descarga + escritura, con logging básico y overwrite
idempotente sobre el path completo.

Uso standalone (para probarlo suelto antes de envolverlo en el DAG):
    spark-submit src/spark/ingest_credit_risk.py

Variables de entorno requeridas (ya definidas en docker-compose.yml):
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
"""

# ==============================================================================
# 1. IMPORTACIÓN DE LIBRERÍAS Y CONFIGURACIÓN INICIAL
# ==============================================================================
# Módulos estándar para logging, variables de entorno y control del sistema
import logging
import os
import sys

# Cliente de Kaggle para descarga de datasets y SparkSession para procesamiento distribuido
import kagglehub
from pyspark.sql import SparkSession

# Constantes del dataset de origen en Kaggle y la ruta destino S3 (MinIO Bronze)
KAGGLE_DATASET = "laotse/credit-risk-dataset"
BRONZE_PATH = "s3a://bronze/credit_risk/"

# Configuración del logger para trazabilidad con timestamp y nivel de severidad
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_credit_risk")


# ==============================================================================
# 2. VALIDACIÓN DE ENTORNO Y CONEXIÓN
# ==============================================================================
def get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o falla con un mensaje claro."""
    # Valida la existencia de credenciales y endpoints requeridos por el contenedor
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Crea la sesión de Spark configurada para hablar con MinIO vía S3A."""
    # Extracción de credenciales de MinIO
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    # Inicialización de Spark con el conector S3A y acceso compatible con MinIO (sin SSL/Path-Style)
    spark = (
        SparkSession.builder.appName("ingest_credit_risk_bronze")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .getOrCreate()
    )
    # Reduce el ruido de logs internos de Spark en la terminal
    spark.sparkContext.setLogLevel("WARN")
    return spark


# ==============================================================================
# 3. EXTRACCIÓN (DESCARGA DESDE FUENTE)
# ==============================================================================
def download_dataset() -> str:
    """Descarga el dataset desde Kaggle vía kagglehub y devuelve la ruta local del CSV."""
    logger.info("Descargando dataset '%s' desde Kaggle...", KAGGLE_DATASET)
    # Descarga local en caché administrada por kagglehub
    dataset_dir = kagglehub.dataset_download(KAGGLE_DATASET)
    logger.info("Dataset descargado en: %s", dataset_dir)

    # Detección y selección del archivo .csv descargado
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
# 4. INGESTA Y PERSISTENCIA (RAW A BRONZE)
# ==============================================================================
def ingest(spark: SparkSession, csv_path: str) -> None:
    """Lee el CSV crudo y lo escribe tal cual a Bronze, sin transformar columnas."""
    logger.info("Leyendo CSV crudo desde: %s", csv_path)
    # Lectura del archivo crudo infiriendo tipos de datos sin aplicar transformaciones de negocio
    df = spark.read.csv(csv_path, header=True, inferSchema=True)

    row_count = df.count()
    col_count = len(df.columns)
    logger.info("Filas leídas: %s | Columnas: %s", row_count, col_count)

    # Control de calidad básico: prevenir escrituras vacías
    if row_count == 0:
        raise ValueError("El CSV descargado está vacío — abortando la ingesta.")

    # Escritura en capa Bronze: formato Parquet optimizado
    logger.info("Escribiendo a Bronze en: %s", BRONZE_PATH)
    df.write.mode("overwrite").option("compression", "snappy").parquet(BRONZE_PATH)
    logger.info("Ingesta completada: %s filas escritas en %s", row_count, BRONZE_PATH)


# ==============================================================================
# 5. ORQUESTACIÓN Y MANEJO DEL CICLO DE VIDA
# ==============================================================================
def main() -> None:
    spark = None
    try:
        # Flujo principal: Inicialización -> Descarga -> Ingesta
        spark = build_spark_session()
        csv_path = download_dataset()
        ingest(spark, csv_path)
    except Exception:
        # Captura cualquier falla, registra el stack trace y sale con código de error
        logger.exception("Falló la ingesta de Credit Risk a Bronze.")
        sys.exit(1)
    finally:
        # Garantiza el cierre de la sesión de Spark y liberación de recursos
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

"""
Ingesta Bronze — Loan Default Dataset

Descarga el dataset desde Kaggle vía kagglehub y lo escribe crudo,
sin transformaciones de negocio, a la capa Bronze en MinIO en
formato Parquet, particionado por fecha de ingesta, con
reintentos y manejo de errores por categoría.

Por qué particionar por fecha:
Antes cada corrida hacía overwrite sobre TODO el path de Bronze, así que
si corrías el script dos días distintos, el segundo día borraba lo que
había escrito el primero. Con overwrite dinámico + partición por
ingestion_date, cada corrida solo toca la carpeta del día en que se
ejecuta, dejando intactas las de días anteriores.

Qué agrega el manejo de errores:
1. Reintentos con backoff en la descarga de Kaggle — el paso más expuesto
   a fallas transitorias de red, ya que depende de un servicio externo.
2. Categorías de error distintas con su propio código de salida, para que
   quien lea los logs (o el futuro DAG de Airflow) pueda distinguir
   de un vistazo qué tipo de falla ocurrió sin tener que leer el stack
   trace completo:
     - exit(2): falta configuración de entorno (env vars de MinIO).
     - exit(3): problema con los datos/fuente (CSV vacío, no encontrado,
       o falla persistente de conexión a Kaggle tras los reintentos).
     - exit(1): cualquier otra falla no anticipada (ej. error al escribir
       en MinIO/S3A).
3. Se loguea la duración total de la corrida, éxito o falla, útil para
   detectar degradación de performance con el tiempo.

Uso standalone (para probarlo suelto antes de envolverlo en el DAG de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 src/spark/ingest_loan_default.py

Variables de entorno requeridas (ya definidas en docker-compose.yml / .env):
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
"""

# ==============================================================================
# 1. IMPORTS Y CONFIGURACIÓN INICIAL
# ==============================================================================
# Módulos estándar: rutas/env vars (os), salida controlada (sys), logging
# estructurado (logging), fecha/hora en UTC (datetime), y time para medir
# duración de la corrida y para las pausas entre reintentos (backoff).
import logging
import os
import sys
import time
from datetime import datetime, timezone

# kagglehub: cliente que descarga datasets públicos de Kaggle a un caché local.
# SparkSession: punto de entrada para todo el procesamiento distribuido.
# lit(): permite crear una columna nueva con un valor constante (aquí,
#        la fecha de ingesta, igual para todas las filas del batch).
import kagglehub
from pyspark.sql import SparkSession
from pyspark.sql.functions import lit

# Identificador del dataset en Kaggle (usuario/nombre-del-dataset) y la ruta
# raíz en MinIO donde queda la capa Bronze de esta fuente.
KAGGLE_DATASET = "yasserh/loan-default-dataset"
BRONZE_PATH = "s3a://bronze/loan_default/"

# Parámetros de reintento para la descarga desde Kaggle. 3 intentos
# con backoff lineal (5s, 10s) cubren la mayoría de fallas transitorias de
# red sin alargar demasiado una corrida que sí está condenada a fallar.
MAX_DOWNLOAD_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_loan_default")


# ==============================================================================
# 2. VALIDACIÓN DE ENTORNO Y CONEXIÓN A SPARK/MINIO
# ==============================================================================
def get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o falla con un mensaje claro.

    Levanta RuntimeError a propósito (no una excepción genérica): en
    main() se atrapa RuntimeError por separado para loguearlo como un
    problema de CONFIGURACIÓN (exit code 2), distinto de un problema de
    DATOS (exit code 3) — así se sabe de inmediato, sin leer el stack
    trace, si hay que revisar el .env o el dataset de origen.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Crea la sesión de Spark configurada para hablar con MinIO vía S3A.

    - endpoint/access.key/secret.key: credenciales de conexión a MinIO.
    - path.style.access=true: MinIO necesita direcciones tipo
      http://host/bucket/objeto, no el estilo AWS real.
    - connection.ssl.enabled=false: no hay HTTPS configurado en local.
    - S3AFileSystem: driver que permite a Spark leer/escribir rutas s3a://.
    - partitionOverwriteMode=dynamic: hace que un
      .mode("overwrite") con partitionBy() solo reemplace la partición
      del día de hoy, sin borrar el histórico de días anteriores.
    """
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("ingest_loan_default_bronze")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


# ==============================================================================
# 3. EXTRACCIÓN — DESCARGA DEL CSV CRUDO DESDE KAGGLE (CON REINTENTOS)
# ==============================================================================
def _download_with_retry() -> str:
    """Descarga el dataset desde Kaggle con reintentos ante fallas
    transitorias de red.

    kagglehub.dataset_download() depende de un servicio externo — puede
    fallar por timeouts, caídas momentáneas de conexión, etc. En vez de
    dejar que un solo fallo transitorio tumbe toda la corrida, se
    reintenta hasta MAX_DOWNLOAD_RETRIES veces con una pausa creciente
    entre intentos (backoff lineal: 5s, 10s).
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
        try:
            logger.info(
                "Descargando dataset '%s' desde Kaggle (intento %s/%s)...",
                KAGGLE_DATASET,
                attempt,
                MAX_DOWNLOAD_RETRIES,
            )
            return kagglehub.dataset_download(KAGGLE_DATASET)
        except (
            Exception
        ) as exc:  # noqa: BLE001 — se relanza abajo si se agotan los intentos
            last_error = exc
            logger.warning(
                "Intento %s/%s de descarga falló: %s",
                attempt,
                MAX_DOWNLOAD_RETRIES,
                exc,
            )
            if attempt < MAX_DOWNLOAD_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    # Se agotaron los reintentos: se relanza como ConnectionError, que en
    # main() se trata como un problema de DATOS/FUENTE (exit code 3), no
    # como una falla inesperada genérica.
    raise ConnectionError(
        f"No se pudo descargar '{KAGGLE_DATASET}' tras {MAX_DOWNLOAD_RETRIES} intentos"
    ) from last_error


def download_dataset() -> str:
    """Descarga el dataset (con reintentos) y devuelve la ruta local del CSV."""
    dataset_dir = _download_with_retry()
    logger.info("Dataset descargado en: %s", dataset_dir)

    # kagglehub descarga una carpeta completa — buscamos el .csv dentro,
    # sin asumir un nombre fijo (Kaggle a veces cambia el nombre del
    # archivo entre versiones del dataset).
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
# 4. INGESTA — LECTURA, SELLADO DE FECHA Y ESCRITURA PARTICIONADA A BRONZE
# ==============================================================================
def ingest(spark: SparkSession, csv_path: str, ingestion_date: str) -> None:
    """Lee el CSV crudo, le agrega la columna ingestion_date, y lo escribe
    a Bronze particionado por esa fecha.

    Bronze = capa cruda: no se limpian valores, no se renombran columnas,
    no se filtran filas — eso es trabajo de Silver (Fase 3).
    """
    logger.info("Leyendo CSV crudo desde: %s", csv_path)
    df = spark.read.csv(csv_path, header=True, inferSchema=True)

    row_count = df.count()
    col_count = len(df.columns)
    logger.info("Filas leídas: %s | Columnas: %s", row_count, col_count)

    # Control de calidad mínimo: preferimos abortar acá con un error claro
    # (ValueError, categorizado como problema de DATOS en main()) en vez
    # de escribir un Bronze vacío silenciosamente.
    if row_count == 0:
        raise ValueError("El CSV descargado está vacío — abortando la ingesta.")

    df = df.withColumn("ingestion_date", lit(ingestion_date))

    logger.info(
        "Escribiendo a Bronze en: %s (partición ingestion_date=%s)",
        BRONZE_PATH,
        ingestion_date,
    )
    # partitionBy + overwrite dinámico (config en build_spark_session):
    # solo reemplaza la partición de HOY, preserva el histórico previo.
    df.write.mode("overwrite").partitionBy("ingestion_date").option(
        "compression", "snappy"
    ).parquet(BRONZE_PATH)
    logger.info("Ingesta completada: %s filas escritas en %s", row_count, BRONZE_PATH)


# ==============================================================================
# 5. ORQUESTACIÓN — PUNTO DE ENTRADA, CATEGORÍAS DE ERROR Y CICLO DE VIDA
# ==============================================================================
def main() -> None:
    """Encadena los pasos del script (conectar → descargar → ingerir),
    clasifica cualquier fallo en una de 3 categorías con su propio
    código de salida, y garantiza el cierre de Spark siempre.
    """
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()
        ingestion_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        csv_path = download_dataset()
        ingest(spark, csv_path, ingestion_date)
    except RuntimeError:
        # Problema de CONFIGURACIÓN: falta una env var de MinIO. No es un
        # problema de los datos ni de Kaggle — hay que revisar el .env.
        logger.exception(
            "Configuración de entorno incompleta (revisar variables de MinIO)."
        )
        sys.exit(2)
    except (FileNotFoundError, ValueError, ConnectionError):
        # Problema de DATOS/FUENTE: CSV vacío, no encontrado, o falla
        # persistente de conexión a Kaggle tras agotar los reintentos.
        logger.exception("Falló la obtención o validación de los datos de origen.")
        sys.exit(3)
    except Exception:
        # Cualquier otra falla no anticipada (ej. error al escribir en
        # MinIO/S3A): se trata como caso genérico, exit code 1.
        logger.exception(
            "Falló la ingesta de Loan Default a Bronze por un error inesperado."
        )
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

"""
Ingesta Bronze — Personal Finance Tracker Dataset

Descarga el dataset desde Kaggle vía kagglehub y lo escribe crudo,
sin transformaciones de negocio, a la capa Bronze en MinIO en
formato Parquet, particionado por fecha de ingesta (t031).

Por qué particionar por fecha:
Antes (t030b original) cada corrida hacía overwrite sobre TODO el path
de Bronze, así que si corrías el script dos días distintos, el segundo
día borraba por completo lo que había escrito el primero. Con overwrite
dinámico + partición por ingestion_date, cada corrida solo toca la
carpeta del día en que se ejecuta (ingestion_date=YYYY-MM-DD/), dejando
intactas las carpetas de días anteriores. Así Bronze funciona como un
histórico real de ingestas, no como una "foto" que se pisa cada vez.

Uso standalone (para probarlo suelto antes de envolverlo en el DAG de Airflow):
    spark-submit --packages org.apache.hadoop:hadoop-aws:3.3.4 \\
        src/spark/ingest_personal_finance_tracker.py

Variables de entorno requeridas (ya definidas en docker-compose.yml / .env):
    MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
"""

# ==============================================================================
# 1. IMPORTS Y CONFIGURACIÓN INICIAL
# ==============================================================================
# Módulos estándar de Python: manejo de rutas/variables de entorno (os),
# salida controlada del programa (sys), logging estructurado (logging) y
# fecha/hora en UTC para el sello de ingestion_date (datetime).
import logging
import os
import sys
from datetime import datetime, timezone

# kagglehub: cliente que descarga datasets públicos de Kaggle a un caché local.
# SparkSession: punto de entrada para todo el procesamiento distribuido.
# lit(): permite crear una columna nueva con un valor constante (aquí,
#        la fecha de ingesta, igual para todas las filas del batch).
import kagglehub
from pyspark.sql import SparkSession
from pyspark.sql.functions import lit

# Identificador del dataset en Kaggle (usuario/nombre-del-dataset) y la ruta
# raíz en MinIO donde queda la capa Bronze de esta fuente. Todo lo demás del
# script depende de estas dos constantes, así que si cambia el dataset de
# origen o el bucket destino, solo hay que tocar estas dos líneas.
KAGGLE_DATASET = "khushikyad001/personal-finance-tracker-dataset"
BRONZE_PATH = "s3a://bronze/personal_finance_tracker/"

# Configuración del logger: cada línea de log queda con timestamp, nivel
# (INFO/WARNING/ERROR) y el nombre del logger, para poder rastrear qué pasó
# y cuándo si algo falla en una corrida del DAG (no solo en local).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_personal_finance_tracker")


# ==============================================================================
# 2. VALIDACIÓN DE ENTORNO Y CONEXIÓN A SPARK/MINIO
# ==============================================================================
def get_required_env(name: str) -> str:
    """Lee una variable de entorno obligatoria o falla con un mensaje claro.

    Se usa para MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY: si falta
    alguna, es mejor que el script truene de inmediato con un mensaje
    explícito, en vez de arrastrar un error confuso más adelante (por
    ejemplo, un fallo de conexión sin contexto de qué variable faltó).
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Crea la sesión de Spark configurada para hablar con MinIO vía S3A.

    Cada .config(...) tiene un propósito puntual:
    - endpoint/access.key/secret.key: cómo y con qué credenciales conectarse
      a MinIO (que actúa como un S3 "simulado" corriendo en Docker).
    - path.style.access=true: MinIO necesita direcciones tipo
      http://host/bucket/objeto en vez del estilo AWS real
      (http://bucket.host/objeto).
    - connection.ssl.enabled=false: en local no hay HTTPS configurado
      entre Spark y MinIO, así que se desactiva la verificación SSL.
    - S3AFileSystem: el driver que le permite a Spark leer/escribir
      rutas s3a:// (sin esto, Spark no sabe qué hacer con ese esquema).
    - partitionOverwriteMode=dynamic: la pieza clave de t031 — hace que
      un .mode("overwrite") con partitionBy() solo reemplace las
      particiones que el DataFrame realmente trae (en este caso, la
      partición del día de hoy), en vez de borrar TODO el path como
      hacía el overwrite "estático" por defecto.
    """
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("ingest_personal_finance_tracker_bronze")
        .config("spark.hadoop.fs.s3a.endpoint", minio_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", minio_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", minio_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .getOrCreate()
    )
    # Silencia el ruido de logs internos de Spark (deja pasar solo WARNING
    # en adelante), para que la terminal muestre sobre todo lo que loguea
    # este script, no el detalle interno del motor de Spark.
    spark.sparkContext.setLogLevel("WARN")
    return spark


# ==============================================================================
# 3. EXTRACCIÓN — DESCARGA DEL CSV CRUDO DESDE KAGGLE
# ==============================================================================
def download_dataset() -> str:
    """Descarga el dataset desde Kaggle vía kagglehub y devuelve la ruta
    local del CSV ya descargado.

    kagglehub cachea la descarga en ~/.cache/kagglehub/ — si el dataset ya
    se había bajado antes en esta máquina, no lo vuelve a descargar, solo
    reutiliza la copia local (por eso correr el script varias veces no
    genera tráfico repetido a Kaggle).
    """
    logger.info("Descargando dataset '%s' desde Kaggle...", KAGGLE_DATASET)
    dataset_dir = kagglehub.dataset_download(KAGGLE_DATASET)
    logger.info("Dataset descargado en: %s", dataset_dir)

    # kagglehub descarga una carpeta completa, no un archivo puntual —
    # buscamos el .csv dentro de esa carpeta, sin asumir un nombre fijo
    # (Kaggle a veces cambia el nombre del archivo entre versiones).
    csv_files = [f for f in os.listdir(dataset_dir) if f.lower().endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError(
            f"No se encontró ningún .csv en {dataset_dir} tras la descarga de kagglehub."
        )
    if len(csv_files) > 1:
        # Defensivo: si el dataset trae más de un CSV, avisamos cuál se usó
        # en vez de fallar o elegir uno al azar sin dejar rastro.
        logger.warning(
            "Se encontraron varios CSV (%s); se usará el primero: %s",
            csv_files,
            csv_files[0],
        )
    return os.path.join(dataset_dir, csv_files[0])


# ==============================================================================
# 4. INGESTA — LECTURA, VALIDACIÓN LIGERA, SELLADO DE FECHA Y ESCRITURA
# ==============================================================================
def ingest(spark: SparkSession, csv_path: str, ingestion_date: str) -> None:
    """Lee el CSV crudo, le agrega la columna ingestion_date, y lo escribe
    a Bronze particionado por esa fecha.

    Bronze = capa cruda: no se limpian valores, no se renombran columnas,
    no se filtran filas — eso es trabajo de Silver (Fase 3, t038-t043).
    El único chequeo "de negocio" que se permite acá es el warning de
    dimensiones (más abajo), y es deliberadamente no-bloqueante: solo
    avisa, nunca frena la ingesta.
    """
    logger.info("Leyendo CSV crudo desde: %s", csv_path)
    # inferSchema=True deja que Spark detecte tipos de datos automáticamente
    # (int, double, string, etc.) en vez de forzar todo a texto. header=True
    # usa la primera fila del CSV como nombres de columna.
    df = spark.read.csv(csv_path, header=True, inferSchema=True)

    row_count = df.count()
    col_count = len(df.columns)
    logger.info("Filas leídas: %s | Columnas: %s", row_count, col_count)

    # Control de calidad mínimo: si Kaggle devolviera un CSV vacío (por un
    # problema de su lado, o una descarga corrupta), preferimos abortar acá
    # con un error claro, en vez de escribir un Bronze vacío silenciosamente.
    if row_count == 0:
        raise ValueError("El CSV descargado está vacío — abortando la ingesta.")

    # Chequeo suave de deriva de datos (data drift): el Contexto Maestro
    # documenta este dataset como 3,000 filas x 25 columnas. Si Kaggle
    # actualiza el dataset y cambian esas dimensiones, no queremos que la
    # ingesta falle sola — solo dejamos un WARNING visible en el log para
    # que alguien lo revise a tiempo.
    if row_count != 3000 or col_count != 25:
        logger.warning(
            "Dimensiones distintas a las documentadas (3000x25): %s filas x %s columnas. "
            "Verificar si el dataset fuente cambió.",
            row_count,
            col_count,
        )

    # Agrega la columna de partición: mismo valor (la fecha de hoy en UTC)
    # para todas las filas de esta corrida. Esta columna es la que Spark
    # usa para decidir en qué subcarpeta (ingestion_date=YYYY-MM-DD/) cae
    # cada fila al escribir.
    df = df.withColumn("ingestion_date", lit(ingestion_date))

    logger.info(
        "Escribiendo a Bronze en: %s (partición ingestion_date=%s)",
        BRONZE_PATH,
        ingestion_date,
    )
    # partitionBy("ingestion_date") crea una subcarpeta por fecha dentro de
    # BRONZE_PATH. Combinado con partitionOverwriteMode=dynamic (definido
    # en build_spark_session), mode("overwrite") aquí SOLO reemplaza la
    # subcarpeta de ingestion_date=<hoy>, sin tocar las de días anteriores
    # — eso es lo que preserva el histórico.
    df.write.mode("overwrite").partitionBy("ingestion_date").option(
        "compression", "snappy"
    ).parquet(BRONZE_PATH)
    logger.info("Ingesta completada: %s filas escritas en %s", row_count, BRONZE_PATH)


# ==============================================================================
# 5. ORQUESTACIÓN — PUNTO DE ENTRADA Y CICLO DE VIDA DE LA SESIÓN DE SPARK
# ==============================================================================
def main() -> None:
    """Encadena los pasos del script (conectar → descargar → ingerir) y
    garantiza que la sesión de Spark se cierre siempre, haya éxito o error.
    """
    # spark se inicializa en None para que el bloque finally pueda revisar
    # de forma segura si llegó a crearse antes de intentar spark.stop() —
    # si build_spark_session() falla, spark nunca se sobreescribe y el
    # finally simplemente no hace nada, en vez de tronar con un error
    # adicional de "variable no definida".
    spark = None
    try:
        spark = build_spark_session()
        # Fecha de ingesta calculada una sola vez al arrancar la corrida,
        # en UTC para que no dependa de la zona horaria de la máquina que
        # ejecuta el script (importante si el DAG de Airflow corre en un
        # contenedor con otro huso horario).
        ingestion_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        csv_path = download_dataset()
        ingest(spark, csv_path, ingestion_date)
    except Exception:
        # Captura cualquier excepción no manejada en el flujo de arriba,
        # deja el stack trace completo en el log, y sale con código 1 para
        # que el DAG de Airflow (t033) sepa que esta tarea falló.
        logger.exception("Falló la ingesta de Personal Finance Tracker a Bronze.")
        sys.exit(1)
    finally:
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

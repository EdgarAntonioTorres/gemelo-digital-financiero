"""
Gold → PostgreSQL — Carga de FACT_KPI_PERFIL a postgres-dw

`calculate_kpis.py` (transformations/) ya escribe FACT_KPI_PERFIL en
Parquet a s3a://gold/fact_kpi_perfil/ — ese script no toca Postgres
directamente (Contexto Maestro §6.4). Este script es la pieza aparte
que cierra: lee ese Parquet y lo carga a la base analítica
(`postgres-dw`, esquema `gold`, ver config/init-dw-schemas.sql), para
que el dashboard técnico/ejecutivo (Streamlit, Fase 4) y el futuro
Text-to-SQL (Fase 5) puedan consultarlo con SQL estándar en vez de
leer Parquet directo.

Nuevo directorio `src/spark/loaders/` (no `transformations/` ni
`diagnostics/`): no transforma datos (ya vienen calculados) ni
diagnostica (escribe, no solo lee/valida) — es su propia categoría.
Igual que `diagnostics/` (convención §7.3), no importa nada de
`transformations/`: es autocontenido.

Motor de escritura: JDBC nativo de Spark (`spark.write.jdbc`), mismo
patrón conceptual que el conector S3A — el driver de PostgreSQL NO se
instala en el Dockerfile (igual que hadoop-aws no se instala ahí), se
resuelve en runtime vía `--packages` junto con hadoop-aws, para no
tener que reconstruir la imagen de Airflow cada vez que cambia la
versión del driver:

    spark-submit \\
        --packages org.apache.hadoop:hadoop-aws:3.3.4,org.postgresql:postgresql:42.7.3 \\
        /opt/airflow/src/spark/loaders/load_gold_postgres.py

Compactación ("Z-Ordering/compactación" del checklist original):
Z-Ordering es una optimización nativa de Delta Lake y este proyecto usa
Parquet plano (Contexto Maestro §7) — no aplica literalmente. Se
interpreta como compactación de particiones: el Parquet de origen
puede traer varios part-files (fragmentados por la corrida de
`calculate_kpis.py`); antes de escribir a Postgres se hace
`coalesce(N_PARTITIONS_JDBC)` para no abrir una conexión JDBC
concurrente por cada part-file de origen — ver `N_PARTITIONS_JDBC`.

Modo de escritura — resuelto en 2 fases (Sesión 27, documentado para
no perder el porqué):
  Fase 1 (corrida inicial): `mode="overwrite"` SIN `truncate` — Spark
  dropeó y recreó `gold.fact_kpi_perfil` con tipos inferidos, porque
  la tabla no existía todavía en `init-dw-schemas.sql`. Confirmó el
  esquema real (ver `config/init-dw-schemas.sql`, sección).
  Fase 2 (ESTE script, ahora): con los tipos ya confirmados y la tabla
  declarada explícitamente en `init-dw-schemas.sql` (con PK en
  `record_id`), el loader pasa a `mode="overwrite"` CON
  `.option("truncate", "true")` — Spark hace TRUNCATE + INSERT en vez
  de DROP + CREATE, preservando la PK entre corridas. Requisito: la
  tabla debe existir de antemano con la estructura correcta (la crea
  `init-dw-schemas.sql` en un volumen nuevo; en un volumen ya
  existente, correr el DDL a mano una vez — ver nota en ese archivo).

Nota (Sesión 30): `calculate_kpis.py` agregó la columna `segmento`
(hallazgo — nunca se había propagado a Gold, ver comentario junto a
`SEGMENTO_AGE_THRESHOLD` en ese script). Como este loader usa
`truncate=true` (TRUNCATE + INSERT, no DROP + CREATE — ver "Modo de
escritura" abajo), la tabla real en Postgres necesita esa columna
declarada ANTES de la próxima corrida, o el INSERT falla por columna
inexistente. Correr una vez, a mano, antes de volver a ejecutar este
script:

    ALTER TABLE gold.fact_kpi_perfil ADD COLUMN IF NOT EXISTS segmento VARCHAR(20);

Lee:
    s3a://gold/fact_kpi_perfil/   (Parquet, escrito por calculate_kpis.py)

Escribe:
    postgres-dw / gemelo_digital / gold.fact_kpi_perfil

Variables de entorno requeridas: MINIO_ENDPOINT, MINIO_ACCESS_KEY,
MINIO_SECRET_KEY (lectura del Parquet en MinIO) + DW_POSTGRES_HOST,
DW_POSTGRES_DB, DW_POSTGRES_USER, DW_POSTGRES_PASSWORD (escritura en
Postgres) — las 4 de Postgres ya están declaradas en
`x-airflow-common-env` del docker-compose.yml, no hay que agregar
nada nuevo ahí.

Nota sobre el host/puerto: DW_POSTGRES_HOST=postgres-dw apunta al
puerto interno 5432 del contenedor (red de Docker Compose) — el
mapeo "5433:5432" en docker-compose.yml es solo para acceder a
postgres-dw desde el HOST (ej. un cliente psql local), no aplica
para la comunicación contenedor-a-contenedor que hace este script.
"""

import logging
import os
import sys
import time

from pyspark.sql import DataFrame, SparkSession

FACT_KPI_PATH = "s3a://gold/fact_kpi_perfil/"
TARGET_TABLE = "gold.fact_kpi_perfil"
JDBC_DRIVER = "org.postgresql.Driver"

# Particiones al escribir por JDBC = conexiones concurrentes abiertas
# contra Postgres. 4 es compactación suficiente para ~184k filas sin
# saturar postgres-dw (que también atiende otras cargas del proyecto)
# ni degradar a una sola conexión secuencial.
N_PARTITIONS_JDBC = 4

# Filas por INSERT batch — evita 1 round-trip por fila (184k inserts
# individuales sería lentísimo) sin armar un batch tan grande que
# dispare el uso de memoria del driver JDBC.
JDBC_BATCH_SIZE = 5000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("load_gold_postgres")


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def build_spark_session() -> SparkSession:
    """Mismo patrón de config S3A que calculate_kpis.py/build_silver_master.py
    — este script necesita leer de MinIO (origen) aunque escriba a
    Postgres (destino)."""
    minio_endpoint = get_required_env("MINIO_ENDPOINT")
    minio_access_key = get_required_env("MINIO_ACCESS_KEY")
    minio_secret_key = get_required_env("MINIO_SECRET_KEY")

    spark = (
        SparkSession.builder.appName("load_gold_postgres")
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


def build_jdbc_url() -> str:
    host = get_required_env("DW_POSTGRES_HOST")
    db = get_required_env("DW_POSTGRES_DB")
    # Puerto interno de postgres-dw en la red de Docker Compose (no el
    # 5433 publicado al host, ver docstring del módulo).
    return f"jdbc:postgresql://{host}:5432/{db}"


def write_to_postgres(df: DataFrame) -> None:
    jdbc_url = build_jdbc_url()
    jdbc_user = get_required_env("DW_POSTGRES_USER")
    jdbc_password = get_required_env("DW_POSTGRES_PASSWORD")

    original_partitions = df.rdd.getNumPartitions()
    df_compact = df.coalesce(N_PARTITIONS_JDBC)
    logger.info(
        "Compactando particiones antes de escribir: %s -> %s",
        original_partitions,
        df_compact.rdd.getNumPartitions(),
    )

    # FASE 2 (ver docstring del módulo): overwrite + truncate=true =
    # Spark hace TRUNCATE + INSERT, no DROP+CREATE — preserva la PK y
    # cualquier constraint definida en gold.fact_kpi_perfil (ver
    # config/init-dw-schemas.sql). Requiere que la tabla YA exista con
    # una estructura compatible; si no existe, esta corrida falla.
    (
        df_compact.write.format("jdbc")
        .option("url", jdbc_url)
        .option("dbtable", TARGET_TABLE)
        .option("user", jdbc_user)
        .option("password", jdbc_password)
        .option("driver", JDBC_DRIVER)
        .option("batchsize", JDBC_BATCH_SIZE)
        .option("truncate", "true")
        .mode("overwrite")
        .save()
    )


def main() -> None:
    spark = None
    start_time = time.monotonic()
    try:
        spark = build_spark_session()

        logger.info("Leyendo FACT_KPI_PERFIL desde: %s", FACT_KPI_PATH)
        df_fact = spark.read.parquet(FACT_KPI_PATH)

        total_rows = df_fact.count()
        logger.info("Filas leídas de Gold (Parquet): %s", total_rows)
        logger.info("Esquema inferido (útil para la Fase 2, ver docstring):")
        df_fact.printSchema()

        logger.info("Escribiendo %s en postgres-dw...", TARGET_TABLE)
        write_to_postgres(df_fact)
        logger.info(
            "Carga completada: %s filas escritas en %s.", total_rows, TARGET_TABLE
        )
    except Exception:
        logger.exception("Falló la carga de Gold a PostgreSQL.")
        sys.exit(1)
    finally:
        elapsed_seconds = time.monotonic() - start_time
        logger.info("Duración total de la corrida: %.1f segundos", elapsed_seconds)
        if spark is not None:
            spark.stop()


if __name__ == "__main__":
    main()

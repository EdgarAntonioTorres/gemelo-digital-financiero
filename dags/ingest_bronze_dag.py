"""
DAG — Ingesta a Bronze (3 fuentes)

Primer DAG de Airflow que orquesta los 3 scripts de ingesta ya
existentes en src/spark/, sin modificarles una sola
línea. Cada script ya es responsable de su propio ciclo de vida
completo (descarga con reintentos, conexión a Spark/MinIO, escritura
particionada, manejo de errores por categoría con exit codes 1/2/3) —
este DAG solo decide CUÁNDO y CÓMO se disparan, no reimplementa nada
de esa lógica.

Por qué BashOperator y no PythonOperator:
Los scripts están escritos para correr como procesos standalone vía
`spark-submit` (así se documentó y probó en la guía de entorno local,
§7.1 del Contexto Maestro). Reusar exactamente ese mismo comando desde
el DAG, en vez de importar las funciones y llamarlas desde Python,
evita que el comportamiento diverja entre "corrida manual" y "corrida
orquestada" — es el mismo proceso, con el mismo flag --packages para
el conector S3A.

Por qué las 3 tareas van ENCADENADAS y no en paralelo (corregido tras
la primera corrida real, 2026-08-21):
Loan Default, Credit Risk y Personal Finance Tracker son fuentes
independientes entre sí en términos de negocio — ninguna depende del
resultado de otra. El diseño original las lanzaba en paralelo por esa
razón. En la práctica, correrlas al mismo tiempo hizo que los 3
procesos `spark-submit` intentaran resolver/descargar el conector S3A
(`--packages org.apache.hadoop:hadoop-aws:3.3.4`) simultáneamente
hacia el mismo caché compartido de Ivy (`~/.ivy2` dentro del
contenedor) — la escritura concurrente corrompió uno de los `.jar`
descargados (`ZipFile invalid LOC header`), tumbando las 3 tareas.
Encadenarlas evita la carrera: solo la primera paga el costo de la
descarga inicial del `.jar`; las siguientes ya lo encuentran cacheado
y resuelto. El orden entre ellas no importa (no hay dependencia de
datos real) — se eligió alfabético/de creación por simplicidad.

Por qué las 3 tareas van en paralelo (sin dependencias entre ellas):
Loan Default, Credit Risk y Personal Finance Tracker son fuentes
independientes entre sí — ninguna depende del resultado de otra para
escribir su propia partición de Bronze. No hay ninguna razón de
negocio para forzar un orden secuencial, y correrlas en paralelo
reduce el tiempo total del DAG.

Reintentos a dos niveles (deliberado, no redundante):
- Dentro del script: 3 reintentos con backoff SOLO para la descarga de
  Kaggle (la parte más expuesta a fallas transitorias de red).
- A nivel de tarea de Airflow (`retries` abajo): cubre cualquier otro
  tipo de falla transitoria que el script no atrapa a su propio nivel
  (ej. una caída momentánea de MinIO al escribir, o del propio
  contenedor). Si el script termina con exit code distinto de 0 por
  cualquier motivo, Airflow reintenta la tarea completa.

Trazabilidad:
Cada comando spark-submit se antecede de `AIRFLOW_RUN_ID='{{ run_id }}'`
— Jinja templating nativo de BashOperator sobre `bash_command`, sin
tocar `env` (que reemplazaría el resto del entorno heredado, ver
`spark_submit_command()`). Cada script de ingesta ya sabe leer esta
variable y sellar cada fila de Bronze con ella (ver docstring de
`ingest_loan_default.py` y análogos) — así cualquier fila de Bronze se
puede rastrear de vuelta a la corrida exacta del DAG que la escribió.

Alcance (deliberadamente no incluido, corresponde a otras tareas):
- configurar logging nativo de Airflow (más allá del default).
- probar ejecución manual + validar idempotencia end-to-end.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

# Conector S3A: mismo flag y misma versión que en la guía de entorno
# local (§7.1) y en el docstring de cada script — así el comando es
# idéntico corras el script a mano o vía este DAG.
SPARK_PACKAGES = "org.apache.hadoop:hadoop-aws:3.3.4"

# Ruta dentro del contenedor de Airflow: docker-compose.yml monta
# ./src del repo en /opt/airflow/src (ver x-airflow-common → volumes).
SPARK_SCRIPTS_DIR = "/opt/airflow/src/spark/ingestion"

default_args = {
    "owner": "gemelo-digital-financiero",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    # Backoff exponencial entre reintentos de Airflow (5min, 10min) —
    # complementa, no duplica, el backoff interno de cada script para
    # la descarga de Kaggle.
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
}


def spark_submit_command(script_filename: str) -> str:
    """Arma el comando spark-submit para un script de ingesta, idéntico
    al que se corre a mano según la guía de entorno local (§7.1),
    salvo la ruta (dentro del contenedor en vez del host) y la variable
    AIRFLOW_RUN_ID antepuesta (trazabilidad).

    Se antepone la variable directamente en el string del comando (en
    vez de usar el parámetro `env=` de BashOperator) a propósito: `env=`
    reemplaza TODO el entorno del proceso hijo en vez de extenderlo, lo
    que rompería MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY que
    los scripts necesitan (heredadas del entorno del contenedor de
    Airflow, ver docker-compose.yml). `{{ run_id }}` es Jinja nativo de
    Airflow sobre `bash_command` — no hace falta declarar `template_fields`.
    """
    return (
        f"AIRFLOW_RUN_ID='{{{{ run_id }}}}' "
        f"spark-submit --packages {SPARK_PACKAGES} "
        f"{SPARK_SCRIPTS_DIR}/{script_filename}"
    )


with DAG(
    dag_id="ingest_bronze_pipeline",
    description="Ingesta de las 3 fuentes (Loan Default, Credit Risk, "
    "Personal Finance Tracker) a la capa Bronze en MinIO.",
    default_args=default_args,
    schedule="@daily",
    start_date=datetime(2026, 8, 21),
    catchup=False,
    max_active_runs=1,
    tags=["bronze", "ingesta", "fase-2"],
) as dag:

    ingest_loan_default = BashOperator(
        task_id="ingest_loan_default",
        bash_command=spark_submit_command("ingest_loan_default.py"),
    )

    ingest_credit_risk = BashOperator(
        task_id="ingest_credit_risk",
        bash_command=spark_submit_command("ingest_credit_risk.py"),
    )

    ingest_personal_finance_tracker = BashOperator(
        task_id="ingest_personal_finance_tracker",
        bash_command=spark_submit_command("ingest_personal_finance_tracker.py"),
    )

    # Encadenadas a propósito (ver docstring del módulo) — evita que los
    # 3 procesos spark-submit compitan por el mismo caché de Ivy al
    # resolver el conector S3A en la primera corrida.
    ingest_loan_default >> ingest_credit_risk >> ingest_personal_finance_tracker

"""
DAG — Ingesta a Bronze (3 fuentes)

Primer DAG de Airflow que orquesta los 3 scripts de ingesta ya
existentes en src/spark/, sin modificarles una sola
línea. Cada script ya es responsable de su propio ciclo de vida
completo (descarga con reintentos, conexión a Spark/MinIO, escritura
particionada, manejo de errores por categoría con exit codes 1/2/3).

Fase 6 (`t083`/`t084`):
- SLAs: SLA de 4 minutos por tarea individual y SLA global del pipeline.
- Alertas: Callbacks on_failure_callback y sla_miss_callback conectados
  a operational.pipeline_alerts en postgres-dw vía alerts.py.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

from alerts import sla_miss_alert, task_failure_alert

SPARK_PACKAGES = "org.apache.hadoop:hadoop-aws:3.3.4"
SPARK_SCRIPTS_DIR = "/opt/airflow/src/spark/ingestion"

# SLAs de Fase 6 (t083)
TASK_SLA = timedelta(minutes=4)
DAG_SLA = timedelta(minutes=10)

default_args = {
    "owner": "gemelo-digital-financiero",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "on_failure_callback": task_failure_alert,
    "sla": TASK_SLA,
}


def spark_submit_command(script_filename: str) -> str:
    """Arma el comando spark-submit para un script de ingesta."""
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
    sla_miss_callback=sla_miss_alert,
    tags=["bronze", "ingesta", "fase-2", "fase-6"],
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

    ingest_loan_default >> ingest_credit_risk >> ingest_personal_finance_tracker

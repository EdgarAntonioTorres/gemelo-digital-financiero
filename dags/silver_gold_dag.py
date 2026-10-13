"""
DAG — Silver a Gold (`t033b`)

Segundo DAG de Airflow del proyecto. Orquesta limpieza + calidad de
las 3 fuentes en Silver, unificación al dataset maestro, cálculo de
KPIs (IRFI/ICA), features de comportamiento y carga a postgres-dw.

Fase 6 (`t083`/`t084`):
- SLAs: SLA de 5 minutos por tarea de procesamiento/carga.
- Alertas: Callbacks on_failure_callback y sla_miss_callback conectados
  a operational.pipeline_alerts en postgres-dw vía alerts.py.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

from alerts import sla_miss_alert, task_failure_alert

SPARK_PACKAGES_S3A = "org.apache.hadoop:hadoop-aws:3.3.4"
SPARK_PACKAGES_S3A_JDBC = f"{SPARK_PACKAGES_S3A},org.postgresql:postgresql:42.7.3"

TRANSFORMATIONS_DIR = "/opt/airflow/src/spark/transformations"
LOADERS_DIR = "/opt/airflow/src/spark/loaders"

# SLAs de Fase 6 (t083)
TASK_SLA = timedelta(minutes=5)
DAG_SLA = timedelta(minutes=15)

default_args = {
    "owner": "gemelo-digital-financiero",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "on_failure_callback": task_failure_alert,
    "sla": TASK_SLA,
}


def spark_submit_command(script_dir: str, script_filename: str, packages: str) -> str:
    """Arma el comando spark-submit para un script de Silver/Gold."""
    return (
        f"AIRFLOW_RUN_ID='{{{{ run_id }}}}' "
        f"spark-submit --packages {packages} "
        f"{script_dir}/{script_filename}"
    )


with DAG(
    dag_id="silver_gold_pipeline",
    description="Limpieza/calidad Silver, unificación al dataset maestro, "
    "KPIs de riesgo/ahorro (IRFI/ICA), features de comportamiento y carga "
    "de Gold a postgres-dw.",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 9, 21),
    catchup=False,
    max_active_runs=1,
    sla_miss_callback=sla_miss_alert,
    tags=["silver", "gold", "kpi", "fase-3", "fase-4", "fase-6"],
) as dag:

    build_silver_loan_default = BashOperator(
        task_id="build_silver_loan_default",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "build_silver_loan_default.py", SPARK_PACKAGES_S3A
        ),
    )

    build_silver_credit_risk = BashOperator(
        task_id="build_silver_credit_risk",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "build_silver_credit_risk.py", SPARK_PACKAGES_S3A
        ),
    )

    build_silver_personal_finance_tracker = BashOperator(
        task_id="build_silver_personal_finance_tracker",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR,
            "build_silver_personal_finance_tracker.py",
            SPARK_PACKAGES_S3A,
        ),
    )

    build_silver_master = BashOperator(
        task_id="build_silver_master",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "build_silver_master.py", SPARK_PACKAGES_S3A
        ),
    )

    calculate_kpis = BashOperator(
        task_id="calculate_kpis",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "calculate_kpis.py", SPARK_PACKAGES_S3A
        ),
    )

    build_fact_comportamiento = BashOperator(
        task_id="build_fact_comportamiento",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "build_fact_comportamiento.py", SPARK_PACKAGES_S3A
        ),
    )

    load_gold_postgres = BashOperator(
        task_id="load_gold_postgres",
        bash_command=spark_submit_command(
            LOADERS_DIR, "load_gold_postgres.py", SPARK_PACKAGES_S3A_JDBC
        ),
    )

    load_fact_comportamiento_postgres = BashOperator(
        task_id="load_fact_comportamiento_postgres",
        bash_command=spark_submit_command(
            LOADERS_DIR,
            "load_fact_comportamiento_postgres.py",
            SPARK_PACKAGES_S3A_JDBC,
        ),
    )

    (
        build_silver_loan_default
        >> build_silver_credit_risk
        >> build_silver_personal_finance_tracker
        >> build_silver_master
        >> [calculate_kpis, build_fact_comportamiento]
        >> load_gold_postgres
        >> load_fact_comportamiento_postgres
    )

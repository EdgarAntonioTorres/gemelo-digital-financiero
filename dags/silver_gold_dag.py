"""
DAG — Silver a Gold (`t033b`)

Segundo DAG de Airflow del proyecto. Orquesta todo lo que hoy corre a
mano vía `spark-submit` (Bitácora, Sesión 30): limpieza + calidad de
las 3 fuentes en Silver, unificación al dataset maestro, cálculo de
KPIs (IRFI/ICA), features de comportamiento (`FACT_COMPORTAMIENTO`) y
carga de ambas tablas Gold a `postgres-dw`. Mismo criterio que
`ingest_bronze_dag.py` (`t033`): no reimplementa nada de la lógica de
los scripts de `src/spark/`, solo decide cuándo y cómo se disparan.

Por qué BashOperator y no PythonOperator: mismo motivo que el DAG de
Bronze — los scripts están escritos para correr como procesos
standalone vía `spark-submit`, y reusar ese comando exacto evita que
el comportamiento diverja entre "corrida manual" y "corrida
orquestada".

Topología (ver razonamiento completo en cada bloque de comentarios
más abajo):

    build_silver_loan_default
        >> build_silver_credit_risk
        >> build_silver_personal_finance_tracker
        >> build_silver_master
        >> [calculate_kpis, build_fact_comportamiento]
        >> load_gold_postgres
        >> load_fact_comportamiento_postgres

Encadenado de los 3 `build_silver_*` (mismo hallazgo que `t033`,
Contexto Maestro §7.2): estos 3 scripts también resuelven el conector
S3A vía `--packages org.apache.hadoop:hadoop-aws:3.3.4` contra el
mismo caché compartido de Ivy dentro del contenedor de Airflow. Aunque
son fuentes independientes entre sí (ninguna depende del resultado de
otra — mismo razonamiento de negocio que en Bronze), lanzarlas en
paralelo arriesga la misma corrupción de caché (`ZipFile invalid LOC
header`) ya documentada. Se encadenan por el mismo motivo, no por una
dependencia de datos real.

`calculate_kpis` y `build_fact_comportamiento` SÍ van en paralelo: para
cuando ambas arrancan, el jar de `hadoop-aws` ya se resolvió y quedó
cacheado por la primera tarea de la cadena de arriba — el riesgo de
carrera era sobre la RESOLUCIÓN/descarga concurrente del jar, no sobre
leerlo ya resuelto. Ambas leen de rutas distintas en Gold/Silver y no
comparten ningún archivo de salida, así que no hay razón adicional
para encadenarlas.

Los 2 `load_*_postgres` SÍ van encadenados entre sí: agregan un jar
nuevo (`org.postgresql:postgresql:42.7.3`) que ningún script anterior
en este DAG resolvió todavía — correrlos en paralelo la primera vez
expondría exactamente el mismo tipo de carrera de Ivy que ya se
documentó para el conector S3A (`t033`), solo que con el driver de
Postgres. Se aplica el mismo criterio preventivo, no una corrección ya
observada en producción.

Nota (fuera de alcance de este DAG, documentado para no perderlo):
si en el futuro se quiere paralelizar `load_gold_postgres` y
`load_fact_comportamiento_postgres`, la forma correcta —igual que ya
se anotó para el conector S3A en §7.2— es pre-hornear el jar de
Postgres en `Dockerfile.airflow` durante el build de la imagen.

Reintentos a dos niveles: mismo criterio que `ingest_bronze_dag.py` —
reintentos internos de cada script (los que ya tengan) cubren fallas
transitorias específicas de su propia lógica; `retries` a nivel de
tarea de Airflow cubre cualquier otra falla transitoria de
infraestructura (MinIO, Postgres, el propio contenedor).

Trazabilidad: mismo patrón de `AIRFLOW_RUN_ID='{{ run_id }}'`
antepuesto al comando (Jinja nativo de BashOperator sobre
`bash_command`, sin tocar `env=`) que en `ingest_bronze_dag.py`. A
diferencia de los scripts de ingesta, los scripts de este DAG no están
confirmados como consumidores de esta variable — se antepone de
cualquier forma por consistencia y por si se instrumenta más adelante
junto con `pipeline_timing.py` (hoy `log_execution()` solo registra
duración/estado, sin `run_id`, ver `t049`).

Scheduling (decisión NO tomada en la documentación del proyecto,
asumida aquí — confirmar/ajustar): `schedule=None` (disparo manual).
La Bitácora (Sesión 30) documenta que hoy todo Silver→Gold corre a
mano y no hay una decisión registrada sobre si este DAG debe
encadenarse automáticamente después de que termine
`ingest_bronze_pipeline` (`@daily`). Si se decide que sí, la forma
más simple es un `TriggerDagRunOperator` al final del DAG de Bronze, o
usar Airflow Datasets sobre las rutas de `s3a://bronze/`.

Alcance (deliberadamente no incluido, corresponde a otras tareas):
- alertas/SLAs de Airflow (`t083`-`t084`, Fase 6).
- instrumentar `AIRFLOW_RUN_ID` dentro de los scripts de Gold/loaders
  (ninguno lo lee hoy, a diferencia de los 3 scripts de ingesta).
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

# Conector S3A: misma versión que ingest_bronze_dag.py y que la guía
# de entorno local (§7.1) — así el comando es idéntico corras el
# script a mano o vía cualquiera de los 2 DAGs del proyecto.
SPARK_PACKAGES_S3A = "org.apache.hadoop:hadoop-aws:3.3.4"

# Los 2 loaders necesitan además el driver JDBC de Postgres, resuelto
# en runtime (no horneado en Dockerfile.airflow) — mismo criterio que
# hadoop-aws, ver docstring de load_gold_postgres.py.
SPARK_PACKAGES_S3A_JDBC = f"{SPARK_PACKAGES_S3A},org.postgresql:postgresql:42.7.3"

# Rutas dentro del contenedor de Airflow: docker-compose.yml monta
# ./src del repo en /opt/airflow/src (ver x-airflow-common -> volumes).
TRANSFORMATIONS_DIR = "/opt/airflow/src/spark/transformations"
LOADERS_DIR = "/opt/airflow/src/spark/loaders"

default_args = {
    "owner": "gemelo-digital-financiero",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
}


def spark_submit_command(script_dir: str, script_filename: str, packages: str) -> str:
    """Arma el comando spark-submit para un script de Silver/Gold,
    mismo patrón que `spark_submit_command()` en `ingest_bronze_dag.py`
    (ver ese docstring para el porqué de `AIRFLOW_RUN_ID` antepuesto en
    vez de usar `env=` de BashOperator)."""
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
    schedule=None,  # ver nota de "Scheduling" en el docstring del módulo
    start_date=datetime(2026, 9, 21),
    catchup=False,
    max_active_runs=1,
    tags=["silver", "gold", "kpi", "fase-3", "fase-4"],
) as dag:

    # --- Silver: limpieza + calidad por fuente (encadenadas, riesgo de
    # caché de Ivy compartido — ver docstring del módulo) ---
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

    # --- Silver: dataset maestro unificado + sub-dimensiones
    # (DIM_PERFIL_*, DIM_COMPORTAMIENTO_PFT) — requiere las 3 fuentes
    # ya limpias en Silver ---
    build_silver_master = BashOperator(
        task_id="build_silver_master",
        bash_command=spark_submit_command(
            TRANSFORMATIONS_DIR, "build_silver_master.py", SPARK_PACKAGES_S3A
        ),
    )

    # --- Gold: KPIs (IRFI/ICA) y features de comportamiento — en
    # paralelo, ver docstring del módulo (caché de Ivy ya resuelto en
    # este punto de la cadena) ---
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

    # --- Gold -> Postgres: encadenados entre sí, ver docstring del
    # módulo (jar del driver de Postgres, nunca resuelto antes en este
    # DAG) ---
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

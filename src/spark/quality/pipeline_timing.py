"""
Instrumentación de tiempos de pipeline — Fase 3 (`t049`).

Registra la duración de cada script en `operational.pipeline_execution_log`
(Postgres) vía `psycopg2` (conexión directa, sin JDBC — evita agregar
la coordenada `org.postgresql:postgresql` a CADA `spark-submit` solo
para esto).

Por qué esto y no la metadata de Airflow: `t033b` (Sesión 30, ver
Bitácora) documenta que todavía no existe un DAG de Silver→Gold —
todo corre a mano. Leer `task_instance` de Airflow para `t049` habría
funcionado si ese DAG ya existiera; como no existe, cada script se
instrumenta a sí mismo. Cuando se resuelva `t033b`, este mismo log
puede seguir usándose desde dentro de las tareas del DAG sin cambiar
nada — no es una solución descartable, es la misma pieza que va a
seguir sirviendo.

Uso (dentro del `finally` de cada script, justo antes de `spark.stop()`,
con `elapsed_seconds` ya calculado):

    from pipeline_timing import log_execution

    log_execution("build_silver_loan_default", elapsed_seconds, status)

`status` es un string libre ("success" / "failed") — se pasa
explícito en vez de inferirse aquí, porque cada script ya sabe si
entró a su bloque `except` o no.
"""

from __future__ import annotations

import logging
import os

import psycopg2

logger = logging.getLogger(__name__)

PIPELINE_EXECUTION_LOG_TABLE = "operational.pipeline_execution_log"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {PIPELINE_EXECUTION_LOG_TABLE} (
    id SERIAL PRIMARY KEY,
    script_name VARCHAR(200) NOT NULL,
    run_timestamp TIMESTAMP NOT NULL DEFAULT now(),
    duration_seconds DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) NOT NULL
);
"""

_INSERT_SQL = f"""
INSERT INTO {PIPELINE_EXECUTION_LOG_TABLE} (script_name, duration_seconds, status)
VALUES (%s, %s, %s);
"""


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def log_execution(script_name: str, duration_seconds: float, status: str) -> None:
    """Inserta una fila de duración. Nunca lanza excepción hacia arriba
    — un fallo al loguear la métrica no debe tumbar un pipeline que sí
    corrió bien (o que ya está manejando su propio error real)."""
    try:
        conn = psycopg2.connect(
            host=get_required_env("DW_POSTGRES_HOST"),
            dbname=get_required_env("DW_POSTGRES_DB"),
            user=get_required_env("DW_POSTGRES_USER"),
            password=get_required_env("DW_POSTGRES_PASSWORD"),
        )
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(_CREATE_TABLE_SQL)
                    cur.execute(_INSERT_SQL, (script_name, duration_seconds, status))
            logger.info(
                "Tiempo de ejecución registrado: %s (%.1fs, %s)",
                script_name,
                duration_seconds,
                status,
            )
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "No se pudo registrar el tiempo de ejecución de %s en %s "
            "(no bloqueante).",
            script_name,
            PIPELINE_EXECUTION_LOG_TABLE,
        )

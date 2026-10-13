"""
Módulo de Alertas y Observabilidad para Airflow — Fase 6 (`t084`).

Gestiona los callbacks de fallo de tareas, fallos de DAG y violaciones
de SLA (`sla_miss_callback`).

Persiste las alertas en la tabla `operational.pipeline_alerts` en `postgres-dw`
utilizando `psycopg2` (mismo patrón no bloqueante que `pipeline_timing.py`),
además de emitir logs estructurados y permitir la notificación opcional vía
webhook HTTP si la variable `AIRFLOW_ALERT_WEBHOOK_URL` está configurada.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

import psycopg2

logger = logging.getLogger(__name__)

ALERTS_TABLE = "operational.pipeline_alerts"

_CREATE_ALERTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {ALERTS_TABLE} (
    id SERIAL PRIMARY KEY,
    alert_timestamp TIMESTAMP NOT NULL DEFAULT now(),
    alert_type VARCHAR(50) NOT NULL,
    dag_id VARCHAR(200) NOT NULL,
    task_id VARCHAR(200),
    run_id VARCHAR(200),
    execution_date VARCHAR(100),
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    details JSONB
);
"""

_INSERT_ALERT_SQL = f"""
INSERT INTO {ALERTS_TABLE} (
    alert_type, dag_id, task_id, run_id, execution_date, severity, message, details
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
"""


def _get_env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _persist_alert_to_db(
    alert_type: str,
    dag_id: str,
    task_id: str | None,
    run_id: str | None,
    execution_date: str | None,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Inserta la alerta en Postgres de forma no bloqueante."""
    host = _get_env("DW_POSTGRES_HOST")
    db = _get_env("DW_POSTGRES_DB")
    user = _get_env("DW_POSTGRES_USER")
    pwd = _get_env("DW_POSTGRES_PASSWORD")

    if not all([host, db, user, pwd]):
        logger.warning(
            "Faltan credenciales de DW_POSTGRES_*; se omite persistencia en BD."
        )
        return

    try:
        conn = psycopg2.connect(host=host, dbname=db, user=user, password=pwd)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(_CREATE_ALERTS_TABLE_SQL)
                    cur.execute(
                        _INSERT_ALERT_SQL,
                        (
                            alert_type,
                            dag_id,
                            task_id,
                            run_id,
                            execution_date,
                            severity,
                            message,
                            json.dumps(details or {}),
                        ),
                    )
            logger.info(
                "Alerta registrada en %s: [%s] %s", ALERTS_TABLE, alert_type, message
            )
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "No se pudo registrar la alerta en %s (no bloqueante).", ALERTS_TABLE
        )


def _send_optional_webhook(payload: dict[str, Any]) -> None:
    """Envía un webhook HTTP si AIRFLOW_ALERT_WEBHOOK_URL está configurada."""
    webhook_url = _get_env("AIRFLOW_ALERT_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            logger.info("Webhook de alerta enviado. HTTP Status: %s", response.status)
    except Exception:
        logger.exception("Fallo al enviar webhook opcional de alerta (no bloqueante).")


def task_failure_alert(context: dict[str, Any]) -> None:
    """Callback invocado por Airflow cuando una tarea falla definitivamente tras sus retries."""
    dag_id = context.get("dag", None).dag_id if context.get("dag") else "unknown_dag"
    task_instance = context.get("task_instance")
    task_id = task_instance.task_id if task_instance else "unknown_task"
    run_id = context.get("run_id", "unknown_run")
    exec_date = str(context.get("execution_date", ""))
    exception = context.get("exception", "Sin detalle de excepción")

    msg = f"Fallo definitivo en tarea '{task_id}' del DAG '{dag_id}' tras reintentos."
    logger.critical(
        "ALERTA AIRFLOW [TASK_FAILURE] | DAG: %s | Task: %s | Run ID: %s | Excepción: %s",
        dag_id,
        task_id,
        run_id,
        exception,
    )

    details = {
        "exception": str(exception),
        "try_number": task_instance.try_number if task_instance else None,
        "max_tries": task_instance.max_tries if task_instance else None,
        "log_url": task_instance.log_url if task_instance else None,
    }

    _persist_alert_to_db(
        alert_type="TASK_FAILURE",
        dag_id=dag_id,
        task_id=task_id,
        run_id=run_id,
        execution_date=exec_date,
        severity="CRITICAL",
        message=msg,
        details=details,
    )

    _send_optional_webhook(
        {
            "text": f":rotating_light: *Airflow Task Failure*\n"
            f"*DAG:* `{dag_id}`\n*Task:* `{task_id}`\n*Run ID:* `{run_id}`\n"
            f"*Error:* ```{exception}```",
        }
    )


def sla_miss_alert(
    dag: Any,
    task_list: list[Any],
    blocking_task_list: list[Any],
    slas: list[Any],
    blocking_tis: list[Any],
    **kwargs: Any,
) -> None:
    """Callback de Airflow ante violaciones de SLA (tiempos máximos superados)."""
    dag_id = getattr(dag, "dag_id", "unknown_dag")
    affected_tasks = [getattr(t, "task_id", str(t)) for t in task_list]
    msg = f"Violación de SLA en DAG '{dag_id}'. Tareas afectadas: {', '.join(affected_tasks)}"

    logger.warning(
        "ALERTA AIRFLOW [SLA_MISS] | DAG: %s | Tareas: %s", dag_id, affected_tasks
    )

    details = {
        "task_list": affected_tasks,
        "blocking_tasks": [getattr(t, "task_id", str(t)) for t in blocking_task_list],
        "slas_count": len(slas) if slas else 0,
    }

    _persist_alert_to_db(
        alert_type="SLA_MISS",
        dag_id=dag_id,
        task_id=",".join(affected_tasks) if affected_tasks else None,
        run_id=None,
        execution_date=datetime.now().isoformat(),
        severity="WARNING",
        message=msg,
        details=details,
    )

    _send_optional_webhook(
        {
            "text": f":warning: *Airflow SLA Missed*\n"
            f"*DAG:* `{dag_id}`\n*Tareas afectadas:* `{affected_tasks}`",
        }
    )

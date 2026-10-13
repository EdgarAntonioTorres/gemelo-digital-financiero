"""
Pruebas de integridad, retries e idempotencia de DAGs — Fase 6 (`t087`).
"""

import sys
import unittest

# Asegurar que el cargador de Airflow encuentre alerts.py en dags/
sys.path.insert(0, "/opt/airflow/dags")

try:
    from airflow.models import DagBag

    AIRFLOW_DISPONIBLE = True
except ImportError:
    AIRFLOW_DISPONIBLE = False


class TestDagIntegrityAndIdempotency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not AIRFLOW_DISPONIBLE:
            raise unittest.SkipTest(
                "Airflow no está instalado en este entorno (ejecutar en airflow-scheduler)."
            )
        # Carga los DAGs de la carpeta /opt/airflow/dags
        cls.dagbag = DagBag(dag_folder="/opt/airflow/dags", include_examples=False)

    def test_sin_errores_de_importacion(self):
        """Verifica que ningún DAG tenga errores de sintaxis o broken DAGs."""
        self.assertEqual(
            len(self.dagbag.import_errors),
            0,
            f"Errores de importación en DAGs: {self.dagbag.import_errors}",
        )

    def test_dag_ingest_bronze_configuracion(self):
        """Verifica retries, idempotencia y callbacks en ingest_bronze_pipeline."""
        dag = self.dagbag.get_dag("ingest_bronze_pipeline")
        self.assertIsNotNone(dag, "El DAG ingest_bronze_pipeline no fue encontrado.")

        # Garantías contra traslapes
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)

        # Verificar cada tarea
        for task in dag.tasks:
            self.assertGreaterEqual(
                task.retries,
                2,
                f"La tarea {task.task_id} debe tener al menos 2 retries",
            )
            self.assertIsNotNone(
                task.on_failure_callback,
                f"La tarea {task.task_id} debe tener on_failure_callback configurado",
            )

    def test_dag_silver_gold_configuracion(self):
        """Verifica retries, idempotencia y callbacks en silver_gold_pipeline."""
        dag = self.dagbag.get_dag("silver_gold_pipeline")
        self.assertIsNotNone(dag, "El DAG silver_gold_pipeline no fue encontrado.")

        # Garantías contra traslapes
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)

        # Verificar cada tarea
        for task in dag.tasks:
            self.assertGreaterEqual(
                task.retries,
                2,
                f"La tarea {task.task_id} debe tener al menos 2 retries",
            )
            self.assertIsNotNone(
                task.on_failure_callback,
                f"La tarea {task.task_id} debe tener on_failure_callback configurado",
            )


if __name__ == "__main__":
    unittest.main()

# /dags

DAGs de Apache Airflow que orquestan el pipeline del Gemelo Digital Financiero.

Convención de nombres: `<fase>_<proceso>.py`, por ejemplo:
- `bronze_ingesta_loan_default.py` (Fase 2 — t029, t033)
- `bronze_ingesta_credit_risk.py` (Fase 2 — t030)
- `bronze_ingesta_personal_finance_tracker.py` (Fase 2 — t030b)
- `bronze_ingesta_personal_finance_tracker.py` (Fase 2 — t030b, t033)
- `silver_calidad_datos.py` (Fase 3)
- `gold_kpis_features.py` (Fase 4)

Cada DAG debe incluir: retries configurados, logging, y ser idempotente (t035, t036).
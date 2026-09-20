"""
Configuración declarativa de expectativas de calidad — Fase 3.

Cada regla se escribe UNA sola vez aquí y la consumen 2 lugares:
  - `great_expectations_runner.py`: las traduce a expectativas
    de Great Expectations y genera el reporte agregado (% que pasa).
  - `quarantine.py`: las traduce a condiciones nativas de Spark
    para decidir, fila por fila, si se cuarentena o no.

Por qué una sola fuente de verdad: si las reglas vivieran duplicadas
en ambos módulos, sería fácil que el reporte de "% de registros que
pasan validación" no coincidiera con lo que realmente se
cuarentenó — el mismo tipo de bug de desincronización que ya
se documentó para `record_id` en Sesión 26 (Contexto Maestro §6.2.1),
solo que aquí entre 2 módulos de código en vez de 2 llamadas a una
función.

Reglas soportadas (`type`):
  - "not_null":  la columna no puede ser NULL.
  - "between":   la columna debe estar en [min, max] (cualquiera de
                 los 2 límites es opcional).
  - "in_set":    la columna debe estar dentro de un conjunto de
                 valores permitidos.
  - "unique":    la columna no debe repetirse en todo el dataset
                 (chequeo agregado — no participa en la cuarentena
                 fila a fila, ver nota en quarantine.py).
  - "regex":     la columna debe matchear un patrón.

Alcance: estas reglas corren SOBRE Silver ya tipado/deduplicado/
imputado/winsorizado (después de `apply_typing()`, `deduplicate()`,
`impute_numeric_*()`, `cap_income_outliers()` — antes del `write()`
final de cada `build_silver_<fuente>.py`). Son un gate de salida de
calidad, no reemplazan esas transformaciones.
"""

from __future__ import annotations

from typing import Any, TypedDict


class QualityRule(TypedDict, total=False):
    type: str
    column: str
    min: float
    max: float
    values: list[Any]
    pattern: str
    description: str


# ==============================================================================
# loan_default
# ==============================================================================
LOAN_DEFAULT_RULES: list[QualityRule] = [
    {
        "type": "not_null",
        "column": "loan_amount",
        "description": "loan_amount no debe ser nulo",
    },
    {
        "type": "not_null",
        "column": "income",
        "description": "income no debe tener nulos residuales tras la imputación",
    },
    {
        "type": "not_null",
        "column": "dtir1",
        "description": "dtir1 no debe tener nulos residuales tras la imputación",
    },
    {
        "type": "not_null",
        "column": "rate_of_interest",
        "description": "rate_of_interest no debe tener nulos residuales",
    },
    {
        "type": "between",
        "column": "dtir1",
        "min": 0,
        "max": 100,
        "description": "dtir1 es una escala de puntos 0-100 antes de /100",
    },
    {
        "type": "in_set",
        "column": "Status",
        "values": [0, 1],
        "description": "Status es binaria (0=al corriente, 1=default)",
    },
    {
        "type": "between",
        "column": "income",
        "min": 0,
        "description": "income no puede ser negativo",
    },
]

# ==============================================================================
# credit_risk
# ==============================================================================
CREDIT_RISK_RULES: list[QualityRule] = [
    {
        "type": "not_null",
        "column": "person_income",
        "description": "person_income no debe ser nulo",
    },
    {
        "type": "not_null",
        "column": "loan_int_rate",
        "description": "loan_int_rate no debe tener nulos residuales",
    },
    {
        "type": "not_null",
        "column": "person_emp_length",
        "description": "person_emp_length no debe tener nulos residuales",
    },
    {
        "type": "between",
        "column": "loan_percent_income",
        "min": 0,
        "max": 1,
        "description": "loan_percent_income es una proporción decimal (0-0.83 observado)",
    },
    {
        "type": "between",
        "column": "person_age",
        "min": 18,
        "max": 100,
        "description": "person_age dentro de un rango plausible de adulto",
    },
    {
        "type": "in_set",
        "column": "loan_status",
        "values": [0, 1],
        "description": "loan_status es binaria (0=al corriente, 1=default)",
    },
    {
        "type": "in_set",
        "column": "loan_grade",
        "values": ["A", "B", "C", "D", "E", "F", "G"],
        "description": "loan_grade debe caer en la escala ordinal documentada (§5.2)",
    },
    {
        "type": "between",
        "column": "person_income",
        "min": 0,
        "description": "person_income no puede ser negativo",
    },
]

# ==============================================================================
# personal_finance_tracker
# ==============================================================================
PFT_RULES: list[QualityRule] = [
    {
        "type": "not_null",
        "column": "monthly_income",
        "description": "monthly_income no debe ser nulo",
    },
    {
        "type": "between",
        "column": "monthly_income",
        "min": 0,
        "description": "monthly_income no puede ser negativo",
    },
    {
        "type": "in_set",
        "column": "segmento",
        "values": ["early_career", "established"],
        "description": "segmento debe venir de derive_synthetic_age()",
    },
    {
        "type": "between",
        "column": "age",
        "min": 20,
        "max": 60,
        "description": "age sintética debe caer en el rango de clip de derive_synthetic_age()",
    },
    {
        "type": "between",
        "column": "debt_to_income_ratio",
        "min": 0,
        "max": 1,
        "description": "debt_to_income_ratio es una proporción decimal (0.1-0.6 observado)",
    },
    {
        "type": "not_null",
        "column": "fraud_flag",
        "description": "fraud_flag no debe ser nulo (usada directo, sin proxy)",
    },
    {
        "type": "between",
        "column": "subscription_services",
        "min": 1,
        "max": 9,
        "description": "subscription_services es un CONTEO 1-9, no un monto",
    },
    {
        "type": "between",
        "column": "emergency_fund",
        "min": 0,
        "description": "emergency_fund no puede ser negativo",
    },
]

# Reglas transversales, aplicadas DESPUÉS de `_add_record_id()` (es decir,
# sobre el dataset maestro ya unificado, no sobre cada fuente por
# separado) — mismo criterio que verify_silver.py (chequeos 1 y 2).
RECORD_ID_PREFIX_BY_SOURCE = {
    "loan_default": "LD",
    "credit_risk": "CR",
    "personal_finance_tracker": "PFT",
}


def master_record_id_rules(source_name: str) -> list[QualityRule]:
    """Reglas de `record_id` para una fuente, aplicadas sobre el
    dataset maestro (post `_add_record_id`, ver build_silver_master.py).
    """
    prefix = RECORD_ID_PREFIX_BY_SOURCE[source_name]
    return [
        {
            "type": "not_null",
            "column": "record_id",
            "description": "record_id no debe ser nulo",
        },
        {
            "type": "unique",
            "column": "record_id",
            "description": "record_id no debe repetirse (ver verify_silver.py, chequeo 1)",
        },
        {
            "type": "regex",
            "column": "record_id",
            "pattern": rf"^{prefix}_\d{{7}}$",
            "description": f"record_id debe matchear '{prefix}_0000000' (7 dígitos)",
        },
    ]


RULES_BY_SOURCE: dict[str, list[QualityRule]] = {
    "loan_default": LOAN_DEFAULT_RULES,
    "credit_risk": CREDIT_RISK_RULES,
    "personal_finance_tracker": PFT_RULES,
}


def get_rules(source_name: str) -> list[QualityRule]:
    if source_name not in RULES_BY_SOURCE:
        raise ValueError(
            f"Fuente desconocida: '{source_name}'. Debe ser una de: "
            f"{list(RULES_BY_SOURCE.keys())}"
        )
    return RULES_BY_SOURCE[source_name]

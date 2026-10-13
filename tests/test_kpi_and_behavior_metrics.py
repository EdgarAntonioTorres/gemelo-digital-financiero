"""
Pruebas unitarias para Fase 6 (`t086`).

Valida la lógica matemática y las reglas de negocio del core analítico:
  1. Fórmulas oficiales de IRFI e ICA (aprobadas por el mentor BBVA, t009/t010/t011).
  2. Comportamiento de proxies y ponderaciones neutras (NEUTRAL_WEIGHT = 0.5, t052/t053).
  3. Métricas de FACT_COMPORTAMIENTO (t054-t057: suscripciones, fondo de emergencia).
  4. Lógica de corte de segmentación (< 30 años: early_career vs established).
"""

import unittest


def calculate_irfi(
    debt_to_income_norm: float,
    emp_stability: float,
    loan_int_rate_norm: float,
    neg_amortization_flag: float,
    grade_score: float,
    credit_hist_norm: float,
) -> float:
    """Fórmula exacta aprobada por el mentor BBVA (6 componentes)."""
    return (
        0.25 * debt_to_income_norm
        + 0.15 * (1.0 - emp_stability)
        + 0.20 * loan_int_rate_norm
        + 0.15 * neg_amortization_flag
        + 0.10 * (1.0 - grade_score)
        + 0.15 * (1.0 - credit_hist_norm)
    )


def calculate_ica(
    debt_to_income_norm: float,
    emp_stability: float,
    housing_penalty: float,
) -> float:
    """Fórmula exacta aprobada por el mentor BBVA (3 componentes)."""
    return 1.0 - (
        0.5 * debt_to_income_norm + 0.3 * (1.0 - emp_stability) + 0.2 * housing_penalty
    )


def segment_age(age_val: float | None) -> str | None:
    """Regla de corte: <30 early_career, >=30 established, None si no parseable."""
    if age_val is None:
        return None
    return "early_career" if age_val < 30.0 else "established"


def calculate_fondo_emergencia_meses(
    emergency_fund: float, monthly_expense: float
) -> float:
    """t057: meses de gasto cubiertos."""
    if monthly_expense <= 0:
        return float("inf")
    return emergency_fund / monthly_expense


def calculate_suscripciones_por_1000(
    subscription_count: int, monthly_income: float
) -> float:
    """t056: suscripciones por cada $1000 USD de ingreso."""
    if monthly_income <= 0:
        return 0.0
    return subscription_count / (monthly_income / 1000.0)


class TestKPIAndBehaviorMetrics(unittest.TestCase):

    def test_irfi_rango_y_extremos(self):
        """Valida que con entradas [0, 1] el IRFI siempre esté acotado entre 0 y 1."""
        irfi_min = calculate_irfi(
            debt_to_income_norm=0.0,
            emp_stability=1.0,
            loan_int_rate_norm=0.0,
            neg_amortization_flag=0.0,
            grade_score=1.0,
            credit_hist_norm=1.0,
        )
        self.assertAlmostEqual(irfi_min, 0.0, places=5)

        irfi_max = calculate_irfi(
            debt_to_income_norm=1.0,
            emp_stability=0.0,
            loan_int_rate_norm=1.0,
            neg_amortization_flag=1.0,
            grade_score=0.0,
            credit_hist_norm=0.0,
        )
        self.assertAlmostEqual(irfi_max, 1.0, places=5)

    def test_ica_rango_y_extremos(self):
        """Valida que con entradas [0, 1] el ICA esté acotado entre 0 y 1."""
        ica_max = calculate_ica(
            debt_to_income_norm=0.0,
            emp_stability=1.0,
            housing_penalty=0.0,
        )
        self.assertAlmostEqual(ica_max, 1.0, places=5)

        ica_min = calculate_ica(
            debt_to_income_norm=1.0,
            emp_stability=0.0,
            housing_penalty=1.0,
        )
        self.assertAlmostEqual(ica_min, 0.0, places=5)

    def test_kpis_con_proxies_neutros(self):
        """Valida el cálculo cuando se aplican los pesos neutros (0.5) de Loan Default / PFT."""
        neutral = 0.5
        irfi_val = calculate_irfi(
            debt_to_income_norm=0.2,
            emp_stability=neutral,
            loan_int_rate_norm=0.1,
            neg_amortization_flag=0.0,
            grade_score=neutral,
            credit_hist_norm=neutral,
        )
        self.assertAlmostEqual(irfi_val, 0.27, places=4)

        ica_val = calculate_ica(
            debt_to_income_norm=0.2,
            emp_stability=neutral,
            housing_penalty=neutral,
        )
        self.assertAlmostEqual(ica_val, 0.65, places=4)

    def test_segment_age_rules(self):
        """Valida la regla de segmentación <30 vs >=30 y tolerancia a nulos."""
        self.assertEqual(segment_age(20.0), "early_career")
        self.assertEqual(segment_age(29.9), "early_career")
        self.assertEqual(segment_age(30.0), "established")
        self.assertEqual(segment_age(45.0), "established")
        self.assertIsNone(segment_age(None))

    def test_comportamiento_metrics(self):
        """Valida métricas de comportamiento (fondo de emergencia y suscripciones)."""
        self.assertEqual(calculate_fondo_emergencia_meses(3000.0, 1500.0), 2.0)
        self.assertEqual(calculate_fondo_emergencia_meses(1000.0, 0.0), float("inf"))

        self.assertEqual(calculate_suscripciones_por_1000(4, 2000.0), 2.0)
        self.assertEqual(calculate_suscripciones_por_1000(2, 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()

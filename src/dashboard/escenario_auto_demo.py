"""
Escenario 2 — Adquirir primer vehículo (`t069`)

Mismo patrón de wiring que `escenario_renta_demo.py` (`t068`) sobre el
motor genérico de `simulator_engine.py` (`t067`) — nada de lógica de
simulación nueva aquí, solo se define `monto_meta` para este escenario.

Meta del escenario (`monto_meta`): `3 x ingreso_mensual` — enganche
típico recomendado para un primer auto (convención de asesoría
financiera básica: 3 meses de ingreso como enganche), decisión
delegada al análisis técnico (no hay `loan_amount`/precio de auto en
`gold.fact_comportamiento` — esa columna vive en `loan_default`, otra
fuente sin datos de ingreso/gasto para simular junto con ella). Mismo
espíritu que el benchmark de `fondo_emergencia_meses` (convención de
industria, no un dato inventado desde cero) — PENDIENTE de validar
con el mentor, igual que la fórmula de `t068`.

Mismos 3 arquetipos que `t068`, mismos `record_id` — así el pitch
compara escenarios distintos sobre las mismas 3 "personas", no
introduce una variable nueva por cambiar de perfiles entre escenarios.

Uso (dentro del contenedor de streamlit, junto a simulator_engine.py):
    docker compose exec streamlit python escenario_auto_demo.py
"""

from __future__ import annotations

from simulator_engine import (
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)

META_MESES_INGRESO = 3  # ver docstring del módulo
HORIZONTE_DEMO_MESES = 12

ARQUETIPOS = [
    {"label": "No usa la app", "record_id": "PFT_0000413", "ahorro_extra_pct": 0.0},
    {"label": "Empieza a usarla", "record_id": "PFT_0000463", "ahorro_extra_pct": 0.10},
    {
        "label": "Usa la app hace tiempo",
        "record_id": "PFT_0002151",
        "ahorro_extra_pct": 0.25,
    },
]


def monto_meta_escenario_auto(ingreso_mensual: float) -> float:
    """monto_meta = 3 x ingreso_mensual (ver docstring del módulo)."""
    return META_MESES_INGRESO * ingreso_mensual


def main() -> None:
    conn = get_dw_connection()
    try:
        df_comportamiento = load_fact_comportamiento(conn)
    finally:
        conn.close()

    pool = build_disponible_pool(df_comportamiento)

    print(
        f"{'Arquetipo':<25}{'record_id':<14}{'income_type':<12}"
        f"{'disponible':>12}{'meta':>10}{'prob_exito':>12}{'mes p50':>10}"
    )
    print("-" * 95)

    for arquetipo in ARQUETIPOS:
        record_id = arquetipo["record_id"]
        fila = df_comportamiento.loc[df_comportamiento["record_id"] == record_id]
        if fila.empty:
            print(
                f"AVISO: {record_id} no encontrado en fact_comportamiento — se omite."
            )
            continue
        fila = fila.iloc[0]
        income_type = str(fila["income_type"])
        disponible_base = float(fila["ingreso_mensual"]) - float(
            fila["gasto_promedio_3m"]
        )
        monto_meta = monto_meta_escenario_auto(float(fila["ingreso_mensual"]))

        resultado = simulate_goal(
            pool=pool,
            income_type=income_type,
            disponible_base=disponible_base,
            monto_meta=monto_meta,
            horizonte_meses=HORIZONTE_DEMO_MESES,
            ahorro_extra_pct=arquetipo["ahorro_extra_pct"],
            seed=42,
        )

        mes_p50 = (
            f"{resultado.mes_meta_percentiles[50]:.0f}"
            if resultado.mes_meta_percentiles
            else "nunca"
        )
        print(
            f"{arquetipo['label']:<25}{record_id:<14}{income_type:<12}"
            f"{disponible_base:>12.2f}{monto_meta:>10.2f}"
            f"{resultado.prob_exito * 100:>11.1f}%{mes_p50:>10}"
        )


if __name__ == "__main__":
    main()

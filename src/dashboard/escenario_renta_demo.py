"""
Escenario 1 — Independizarse/rentar primer depto (`t068`)

Demo comparativo (no es la UI final de Streamlit, esa es `t071`):
corre `simulate_goal()` (motor genérico de `simulator_engine.py`,
`t067`) sobre 3 perfiles REALES de `gold.fact_comportamiento`
(elegidos a mano en Sesión 34 por tener disponible mensual moderado
y distinto `income_type` — ver conversación de diseño), cada uno
representando un arquetipo de uso de la app:

  - "No usa la app"          -> ahorro_extra_pct = 0%   (línea base, comportamiento actual tal cual)
  - "Empieza a usarla"       -> ahorro_extra_pct = +10%
  - "Usa la app hace tiempo" -> ahorro_extra_pct = +25%

Los 3 valores de ahorro_extra_pct son una propuesta razonada, no un
dato medido — quedan documentados aquí para poder ajustarse fácil si
el mentor pide otro criterio.

Meta del escenario (`monto_meta`): `2 x gasto_promedio_3m` — depósito
+ primer mes de renta, convención estándar de mercado (mismo espíritu
que el benchmark de 3-6 meses ya usado para `fondo_emergencia_meses`,
Contexto Maestro). Se calcula por perfil (cada quien tiene su propio
`gasto_promedio_3m`), NO es un monto fijo igual para los 3 — así la
meta es realista para cada persona, no un número arbitrario común.

No usa `rent_or_mortgage` (columna cruda de Silver-PFT, nunca
persistida a Gold) a propósito — usar esa columna habría requerido
tocar el pipeline de Spark, fuera del alcance de t068 (ver discusión
de diseño).

Uso (dentro del contenedor de streamlit, junto a simulator_engine.py):
    docker compose exec streamlit python escenario_renta_demo.py
"""

from __future__ import annotations

from simulator_engine import (
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)

# Meta del escenario: 2 meses de gasto (depósito + primer mes de
# renta adelantado) — ver docstring del módulo.
META_MESES_GASTO = 2
HORIZONTE_DEMO_MESES = 12

ARQUETIPOS = [
    {
        "label": "No usa la app",
        "record_id": "PFT_0000413",
        "ahorro_extra_pct": 0.0,
    },
    {
        "label": "Empieza a usarla",
        "record_id": "PFT_0000463",
        "ahorro_extra_pct": 0.10,
    },
    {
        "label": "Usa la app hace tiempo",
        "record_id": "PFT_0002151",
        "ahorro_extra_pct": 0.25,
    },
]


def monto_meta_escenario_renta(gasto_promedio_3m: float) -> float:
    """monto_meta = 2 x gasto_promedio_3m (ver docstring del módulo)."""
    return META_MESES_GASTO * gasto_promedio_3m


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
        monto_meta = monto_meta_escenario_renta(float(fila["gasto_promedio_3m"]))

        resultado = simulate_goal(
            pool=pool,
            income_type=income_type,
            disponible_base=disponible_base,
            monto_meta=monto_meta,
            horizonte_meses=HORIZONTE_DEMO_MESES,
            ahorro_extra_pct=arquetipo["ahorro_extra_pct"],
            seed=42,  # misma semilla en los 3 -> la diferencia es SOLO ahorro_extra_pct/perfil
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

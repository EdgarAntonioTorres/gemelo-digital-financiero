"""
Escenario 3 — Cambio de empleo: colchón de emergencia (`t070`)

Mismo patrón de wiring que `t068`/`t069` sobre el motor genérico de
`simulator_engine.py` (`t067`). De las 2 historias que agrupa `t070`
("primera tarjeta de crédito" o "cambio de empleo"), se implementa
SOLO "cambio de empleo" — decisión con el alumno, Sesión 34: es la
interpretación con mejor respaldo de datos reales (usa
`fondo_emergencia_meses`, que YA existe en Gold), a diferencia de
"primera tarjeta" que no tiene un dato natural equivalente a "meta de
ahorro". "Primera tarjeta de crédito" queda fuera de esta tarea — si
se retoma más adelante, es una tarea aparte, no una variante de este
script.

Meta del escenario (`monto_meta`): cerrar la brecha hasta el
benchmark de industria de 3 meses de gasto cubiertos por el fondo de
emergencia (mismo benchmark ya documentado en
`diccionario_features.md` para `fondo_emergencia_meses`, 3-6 meses,
se usa el extremo bajo del rango):

    fondo_actual = fondo_emergencia_meses x gasto_promedio_3m
    monto_meta = max(0, 3 x gasto_promedio_3m - fondo_actual)

Si el perfil YA tiene 3+ meses cubiertos, la meta es $0 — no se
fuerza un número artificial solo para que el escenario tenga algo que
mostrar (mismo criterio de "no fabricar" de todo el proyecto).

Uso (dentro del contenedor de streamlit, junto a simulator_engine.py):
    docker compose exec streamlit python escenario_empleo_demo.py
"""

from __future__ import annotations

from simulator_engine import (
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)

BENCHMARK_MESES_FONDO_EMERGENCIA = 3  # extremo bajo del rango 3-6 (ver docstring)
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


def monto_meta_escenario_empleo(
    fondo_emergencia_meses: float, gasto_promedio_3m: float
) -> float:
    """monto_meta = brecha hasta 3 meses de fondo de emergencia (ver
    docstring del módulo). Nunca negativo — un perfil que ya supera
    el benchmark tiene meta $0, no una meta negativa sin sentido."""
    fondo_actual = fondo_emergencia_meses * gasto_promedio_3m
    meta_objetivo = BENCHMARK_MESES_FONDO_EMERGENCIA * gasto_promedio_3m
    return max(0.0, meta_objetivo - fondo_actual)


def main() -> None:
    conn = get_dw_connection()
    try:
        df_comportamiento = load_fact_comportamiento(conn)
    finally:
        conn.close()

    pool = build_disponible_pool(df_comportamiento)

    print(
        f"{'Arquetipo':<25}{'record_id':<14}{'income_type':<12}"
        f"{'disponible':>12}{'fondo_meses':>12}{'meta':>10}{'prob_exito':>12}{'mes p50':>10}"
    )
    print("-" * 110)

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
        gasto = float(fila["gasto_promedio_3m"])
        fondo_meses = float(fila["fondo_emergencia_meses"])
        disponible_base = float(fila["ingreso_mensual"]) - gasto
        monto_meta = monto_meta_escenario_empleo(fondo_meses, gasto)

        if monto_meta == 0.0:
            print(
                f"{arquetipo['label']:<25}{record_id:<14}{income_type:<12}"
                f"{disponible_base:>12.2f}{fondo_meses:>12.2f}"
                f"{'$0 (ya cubre el benchmark)':>10}"
            )
            continue

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
            f"{disponible_base:>12.2f}{fondo_meses:>12.2f}{monto_meta:>10.2f}"
            f"{resultado.prob_exito * 100:>11.1f}%{mes_p50:>10}"
        )


if __name__ == "__main__":
    main()

"""
Página del Simulador — Selector de perfil + parametrización real (`t071`)

Segunda iteración de `t071` (Sesión 35): además del Escenario 1
(independizarse / primera renta, `t068`, ya validado con datos reales
en la primera iteración), agrega los 3 escenarios del checklist en
UNA sola página, con un selector arriba — decisión explícita de esta
sesión (vs. 3 páginas separadas en la barra lateral).

  1. "Login" simulado vía selector de perfil sintético (`t100`/`t102`,
     Contexto Maestro §10.2): 3 arquetipos con `record_id` REALES de
     `gold.fact_comportamiento` — los MISMOS 3 que usan los 3 scripts
     demo (`escenario_renta_demo.py`, `escenario_auto_demo.py`,
     `escenario_empleo_demo.py`). Es la misma "Ana" en todo el pitch,
     sin importar qué escenario se elija.
  2. Parametrización real de `simulator_engine.simulate_goal()`:
     `horizonte_meses` y `ahorro_extra_pct` quedan editables por el
     usuario (sliders), con un valor por defecto precargado según el
     arquetipo elegido (0%/10%/25%) pero NO fijo.
  3. `monto_meta` se calcula con la MISMA fórmula que cada script demo
     (`t068`/`t069`/`t070`) — se importan las 3 funciones en vez de
     reescribirlas aquí, para no tener 2 fuentes de verdad de la
     misma meta.

Caso especial — Escenario empleo (`t070`): si el perfil YA cubre el
benchmark de 3 meses de fondo de emergencia,
`monto_meta_escenario_empleo()` devuelve `0.0` (ver docstring de
`escenario_empleo_demo.py`). `simulate_goal()` exige `monto_meta > 0`,
así que este caso se intercepta ANTES de llamar al motor y se
muestra un mensaje en vez de un error — mismo criterio que ya usa
`escenario_empleo_demo.py` en consola.

Ubicación: `src/dashboard/pages/1_Simulador.py` — vive en `pages/`
(sistema nativo de páginas de Streamlit, §10.3 Contexto Maestro).
Streamlit la detecta automáticamente porque `quality_dashboard.py`
(el entrypoint real, ver `CMD` en `Dockerfile.streamlit`) vive un
nivel arriba, en `/app` dentro del contenedor. No requiere cambios en
`Dockerfile.streamlit` ni `docker-compose.yml`.

No agrega dependencias nuevas.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

# El directorio raíz del dashboard (/app dentro del contenedor, un
# nivel arriba de pages/) no siempre queda en sys.path cuando
# Streamlit ejecuta un archivo de pages/ como script independiente —
# se agrega explícito para poder importar simulator_engine.py y los
# 3 scripts demo sin duplicar su lógica aquí.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator_engine import (  # noqa: E402
    AHORRO_EXTRA_PCT_MAX,
    AHORRO_EXTRA_PCT_MIN,
    HORIZONTE_DEFAULT_MESES,
    HORIZONTE_MAX_MESES,
    HORIZONTE_MIN_MESES,
    SimulationResult,
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)
from escenario_renta_demo import monto_meta_escenario_renta  # noqa: E402
from escenario_auto_demo import monto_meta_escenario_auto  # noqa: E402
from escenario_empleo_demo import monto_meta_escenario_empleo  # noqa: E402
from perfiles_sinteticos import render_selector_perfil  # noqa: E402

# t081: ARQUETIPOS y render_selector_perfil() se movieron a
# perfiles_sinteticos.py — pages/2_Coach.py (el chat de Centavo)
# necesita la MISMA lista de perfiles, y duplicarla en 2 páginas
# arriesgaba que se desincronizaran (ver docstring de ese módulo).

# Cada escenario define: qué tarea del checklist es, cómo se calcula
# monto_meta a partir de la fila real de fact_comportamiento, y un
# texto que explica esa meta al usuario. La fórmula SIEMPRE viene del
# script demo correspondiente (t068/t069/t070) — nunca se reescribe
# aquí, para no crear una segunda fuente de verdad.
SCENARIOS: dict[str, dict] = {
    "renta": {
        "label": "Independizarte / primera renta",
        "task_id": "t068",
        "monto_meta_fn": lambda fila: monto_meta_escenario_renta(
            fila["gasto_promedio_3m"]
        ),
        "meta_caption": "Depósito + primer mes de renta (2x tu gasto promedio).",
    },
    "auto": {
        "label": "Primer vehículo",
        "task_id": "t069",
        "monto_meta_fn": lambda fila: monto_meta_escenario_auto(
            fila["ingreso_mensual"]
        ),
        "meta_caption": "Enganche estimado (3x tu ingreso mensual).",
    },
    "empleo": {
        "label": "Cambio de empleo / colchón de emergencia",
        "task_id": "t070",
        "monto_meta_fn": lambda fila: monto_meta_escenario_empleo(
            fila["fondo_emergencia_meses"], fila["gasto_promedio_3m"]
        ),
        "meta_caption": (
            "Brecha hasta cubrir 3 meses de gasto con tu fondo de emergencia "
            "(benchmark 3-6 meses, diccionario_features.md)."
        ),
    },
}


@st.cache_resource
def _get_dw_connection():
    # Cacheada a nivel Streamlit (a diferencia de
    # simulator_engine.get_dw_connection(), deliberadamente sin cachear
    # para poder probarse aislado — ver docstring del módulo).
    return get_dw_connection()


@st.cache_data
def _load_pool_and_data():
    conn = _get_dw_connection()
    df = load_fact_comportamiento(conn)
    pool = build_disponible_pool(df)
    return df, pool


def render_selector_escenario() -> str:
    st.subheader("1. ¿Qué quieres simular?")
    keys = list(SCENARIOS.keys())
    idx = st.selectbox(
        "Escenario",
        options=range(len(keys)),
        format_func=lambda i: SCENARIOS[keys[i]]["label"],
        label_visibility="collapsed",
    )
    return keys[idx]


def render_parametros(ahorro_default: float) -> tuple[int, float]:
    st.subheader("3. Ajusta tu simulación")
    col1, col2 = st.columns(2)
    with col1:
        horizonte_meses = st.slider(
            "Horizonte (meses)",
            min_value=HORIZONTE_MIN_MESES,
            max_value=HORIZONTE_MAX_MESES,
            value=HORIZONTE_DEFAULT_MESES,
            help="Entre 6 y 36 meses — metas de corto/mediano plazo (§2 Contexto Maestro).",
        )
    with col2:
        ahorro_extra_pct = st.slider(
            "Ajuste de ahorro sobre tu disponible actual",
            min_value=AHORRO_EXTRA_PCT_MIN,
            max_value=AHORRO_EXTRA_PCT_MAX,
            value=ahorro_default,
            step=0.01,
            help=(
                "Precargado según tu perfil (0.10 = +10%), pero puedes "
                "moverlo: simula qué pasaría si ahorraras más o menos que hoy."
            ),
        )
    return horizonte_meses, ahorro_extra_pct


def render_resultado(resultado: SimulationResult, monto_meta: float) -> None:
    st.subheader("4. Resultado")

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Probabilidad de alcanzar tu meta",
        f"{resultado.prob_exito * 100:.1f}%",
        help=(
            f"IC 95%: [{resultado.prob_exito_ic95[0] * 100:.1f}%, "
            f"{resultado.prob_exito_ic95[1] * 100:.1f}%]"
        ),
    )
    c2.metric("Meta a alcanzar", f"${monto_meta:,.0f}")
    if resultado.mes_meta_percentiles:
        c3.metric(
            "Mes en que la alcanzas (mediana)",
            f"Mes {resultado.mes_meta_percentiles[50]:.0f}",
            help=(
                f"Rango típico: mes {resultado.mes_meta_percentiles[10]:.0f} a "
                f"{resultado.mes_meta_percentiles[90]:.0f}"
            ),
        )
    else:
        c3.metric("Mes en que la alcanzas", "Ninguna simulación llegó a la meta")

    with st.expander("Ver detalle del monto acumulado al final del horizonte"):
        p = resultado.monto_final_percentiles
        st.write(f"P10: ${p[10]:,.0f} · P50: ${p[50]:,.0f} · P90: ${p[90]:,.0f}")
        st.caption(
            f"Basado en {resultado.n_simulaciones:,} simulaciones Monte Carlo "
            f"(bootstrap sobre datos reales de personas con "
            f"income_type='{resultado.income_type}')."
        )


def main() -> None:
    st.set_page_config(page_title="Moneta — Simulador", layout="wide")
    st.title("Simulador de metas")
    st.caption(
        "3 escenarios del checklist (t068 renta, t069 auto, t070 cambio de "
        "empleo), un solo motor (simulator_engine.py, t067)."
    )

    try:
        df_comportamiento, pool = _load_pool_and_data()
    except Exception as exc:
        st.error(f"No se pudo conectar a gold.fact_comportamiento: {exc}")
        return

    escenario_key = render_selector_escenario()
    escenario = SCENARIOS[escenario_key]

    arquetipo = render_selector_perfil("2. Elige tu perfil")
    record_id = arquetipo["record_id"]
    fila = df_comportamiento.loc[df_comportamiento["record_id"] == record_id]
    if fila.empty:
        st.error(
            f"El perfil {record_id} no está en gold.fact_comportamiento — "
            "revisa que el pipeline de Gold ya haya corrido."
        )
        return
    fila = fila.iloc[0]
    income_type = str(fila["income_type"])
    ingreso_mensual = float(fila["ingreso_mensual"])
    gasto_promedio_3m = float(fila["gasto_promedio_3m"])
    disponible_base = ingreso_mensual - gasto_promedio_3m

    st.divider()
    st.caption(
        f"Tu perfil real: income_type={income_type} · ingreso mensual="
        f"${ingreso_mensual:,.0f} · gasto promedio=${gasto_promedio_3m:,.0f} · "
        f"disponible mensual=${disponible_base:,.0f}"
    )

    horizonte_meses, ahorro_extra_pct = render_parametros(
        arquetipo["ahorro_extra_pct_default"]
    )

    monto_meta_fn: Callable[[pd.Series], float] = escenario["monto_meta_fn"]
    monto_meta = float(monto_meta_fn(fila))
    st.caption(f"Tu meta ({escenario['label']}): {escenario['meta_caption']}")

    # Caso especial de t070 (ver docstring del módulo): meta $0 porque
    # el perfil ya cubre el benchmark — no se llama a simulate_goal()
    # (exige monto_meta > 0), se informa directo.
    if monto_meta <= 0.0:
        st.success(
            "Tu fondo de emergencia ya cubre el benchmark de 3 meses — "
            "no hace falta simular una meta adicional para este escenario."
        )
        return

    if st.button("Simular", type="primary"):
        resultado = simulate_goal(
            pool=pool,
            income_type=income_type,
            disponible_base=disponible_base,
            monto_meta=monto_meta,
            horizonte_meses=horizonte_meses,
            ahorro_extra_pct=ahorro_extra_pct,
            seed=None,  # UI real:sin semilla fija (los demos usan seed=42 para comparar arquetipos)
        )
        st.divider()
        render_resultado(resultado, monto_meta)

        # t081: se guarda en session_state (compartido entre páginas de
        # una app multipágina de Streamlit) para que pages/2_Coach.py
        # pueda responder preguntas de categoría "SIMULACION" (t076)
        # sobre ESTA corrida en concreto, sin tener que volver a
        # correr el Monte Carlo. Se guarda como texto ya formado (no el
        # dataclass crudo) porque es justo lo que necesita el
        # System Prompt de Centavo (t075) en RESULTADO_CONSULTA.
        mes_p50_txt = (
            f"mes {resultado.mes_meta_percentiles[50]:.0f}"
            if resultado.mes_meta_percentiles
            else "ninguna simulación llegó a la meta"
        )
        st.session_state["ultima_simulacion"] = (
            f"Escenario: {escenario['label']}. Meta: ${monto_meta:,.0f}. "
            f"Horizonte: {horizonte_meses} meses. Ajuste de ahorro aplicado: "
            f"{ahorro_extra_pct * 100:.0f}%. Probabilidad de éxito: "
            f"{resultado.prob_exito * 100:.1f}% (IC 95%: "
            f"[{resultado.prob_exito_ic95[0] * 100:.1f}%, "
            f"{resultado.prob_exito_ic95[1] * 100:.1f}%]). Mediana del mes en "
            f"que se alcanza la meta: {mes_p50_txt}."
        )


if __name__ == "__main__":
    main()

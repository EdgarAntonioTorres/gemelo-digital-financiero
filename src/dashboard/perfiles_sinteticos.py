"""
Perfiles sintéticos compartidos — "login" simulado (`t100`/`t102`)

Antes vivía duplicado dentro de `pages/1_Simulador.py`. Se extrae aquí
en `t081` porque ahora un SEGUNDO lugar (`pages/2_Coach.py`) necesita
la MISMA lista — duplicarla en 2 páginas arriesgaba que un día alguien
cambie un `record_id` en una y no en la otra, y el pitch mostraría 2
"Anas" distintas. A diferencia de `get_required_env()` (boilerplate de
infraestructura, sí se duplica a propósito entre módulos — ver
`simulator_engine.py`), esto es un dato de negocio: una sola fuente de
verdad.

Vive en `src/dashboard/` (no dentro de `assistant/` ni `pages/`)
porque lo usan páginas de AMBOS lados del dashboard.
"""

from __future__ import annotations

import streamlit as st

# Mismos 3 arquetipos/record_id que los 3 scripts demo
# (escenario_renta_demo.py, etc.) — es el mismo "login" simulado en
# toda la app, sin importar si estás en el Simulador o hablando con
# Centavo.
ARQUETIPOS = [
    {
        "label": "No uso la app",
        "record_id": "PFT_0000413",
        "ahorro_extra_pct_default": 0.0,
        "descripcion": "Tu comportamiento actual, sin ningún cambio de hábito.",
    },
    {
        "label": "Empiezo a usarla",
        "record_id": "PFT_0000463",
        "ahorro_extra_pct_default": 0.10,
        "descripcion": "Ajusta tu disponible mensual +10% (ahorro guiado, recién empiezas).",
    },
    {
        "label": "La uso hace tiempo",
        "record_id": "PFT_0002151",
        "ahorro_extra_pct_default": 0.25,
        "descripcion": "Ajusta tu disponible mensual +25% (hábito ya consolidado).",
    },
]


def render_selector_perfil(subheader: str = "Elige tu perfil") -> dict:
    """UI del selector, reutilizada tal cual en ambas páginas.
    Recuerda la última selección en st.session_state
    ("perfil_activo_idx") — session_state se comparte entre páginas de
    una app multipágina de Streamlit, así que si eliges un perfil en
    el Simulador y luego abres el Coach, sigue seleccionado el mismo
    perfil sin que el usuario tenga que repetirlo."""
    st.subheader(subheader)
    st.caption(
        'Selector de perfil sintético ("login" simulado, §10.2 Contexto '
        "Maestro) — cada opción es un record_id real de "
        "gold.fact_comportamiento, no un dato inventado."
    )
    labels = [a["label"] for a in ARQUETIPOS]
    idx = st.radio(
        "¿Cómo describirías tu uso de la app?",
        options=range(len(ARQUETIPOS)),
        format_func=lambda i: labels[i],
        horizontal=True,
        index=st.session_state.get("perfil_activo_idx", 0),
        key="perfil_activo_idx",
    )
    arquetipo = ARQUETIPOS[idx]
    st.caption(arquetipo["descripcion"])
    return arquetipo

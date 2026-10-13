"""
Perfiles sintéticos compartidos — "login" simulado (`t100`/`t102`)

Vive en `src/dashboard/` (no dentro de `assistant/` ni `pages/`) porque lo
usan páginas de TODOS los lados del dashboard ("Lo que tengo hoy", el
Simulador y el Coach). Es un dato de negocio: una sola fuente de verdad.
A diferencia de `get_required_env()` (boilerplate de infraestructura, que
sí se duplica a propósito entre módulos), duplicar esta lista arriesgaba
que un día alguien cambie un `record_id` en una página y no en otra.

Sesión 36 (`t077` v2.3): la app pasó de 3 arquetipos de "uso de la app" a
DOS perfiles, ambos de Ana, con registros reales de
`gold.fact_comportamiento`:

  * Ana primeriza   — `PFT_0000636` — nivel 1 · Primeros pasos.
  * Ana más madura  — `PFT_0002539` — nivel 2 · Construyendo base.

Son DOS registros distintos, no una trayectoria: Gold es corte
transversal (`t107`), así que la narrativa "Ana mejoró" es ilustrativa y
ningún texto de la app dice cuánto tiempo pasó entre una y otra. Ambas
son Freelance y `early_career`; la edad es derivada
(`age_synthetic_flag = True`). La lógica de Centavo y de `plan_engine` es
general (sirve para cualquier perfil con datos); solo la app se limita a
estas dos.

Cambiar de Ana es cambiar un `record_id` aquí Y resembrar
`gold.fact_perfil_detalle` (`config/create-fact-perfil-detalle.sql`).
`record_id` se genera con `zipWithIndex` (no estable entre corridas del
pipeline de Gold): por eso ese script verifica una "huella" y falla si
los `record_id` se desalinearon.

Contrato (lo usan `1_Simulador.py`, `2_Coach.py` y `0_Lo_que_tengo_hoy.py`):
cada elemento de `ARQUETIPOS` tiene `label`, `record_id`,
`ahorro_extra_pct_default` y `descripcion`. `nombre` (nuevo en el paso 2)
es el nombre de la persona con el que Centavo la saluda: es "Ana" en
ambas, a propósito (historia coherente con una persona con nombre, feedback
del mentor); `label` es solo para el selector y NUNCA se le pasa a Centavo
("primeriza"/"más madura" invitarían a etiquetarla).

`ahorro_extra_pct_default` = 0.0 en ambas [PROPUESTA]: los defaults
anteriores (0%/10%/25%) representaban "nivel de uso de la app", un
concepto que ya no existe; 0.0 es el valor neutro (tu comportamiento
actual) y no inventa un número. El usuario lo mueve con el slider.
"""

from __future__ import annotations

import streamlit as st

ARQUETIPOS = [
    {
        "label": "Ana primeriza",
        "nombre": "Ana",
        "record_id": "PFT_0000636",
        "ahorro_extra_pct_default": 0.0,
        "descripcion": "Ana trabaja por su cuenta y está dando sus primeros pasos con su dinero.",
    },
    {
        "label": "Ana más madura",
        "nombre": "Ana",
        "record_id": "PFT_0002539",
        "ahorro_extra_pct_default": 0.0,
        "descripcion": (
            "Ana trabaja por su cuenta y ya tiene más orden: "
            "menos deudas y un colchón que empieza a crecer."
        ),
    },
]

_CLAVE_SESION = "perfil_activo_idx"


def render_selector_perfil(subheader: str = "Elige tu perfil") -> dict:
    """UI del selector, reutilizada tal cual en todas las páginas.
    Recuerda la última selección en st.session_state
    ("perfil_activo_idx") — session_state se comparte entre páginas de
    una app multipágina de Streamlit, así que si eliges un perfil en una
    página y abres otra, sigue seleccionado el mismo perfil.

    Protección: si en la sesión quedó guardado un índice de la lista
    ANTERIOR (que tenía 3 perfiles, índice 2 incluido), el radio
    fallaría con un índice fuera de rango; se reinicia a 0."""
    st.subheader(subheader)
    st.caption("Perfiles de demostración, armados con registros reales del proyecto.")
    labels = [a["label"] for a in ARQUETIPOS]
    actual = st.session_state.get(_CLAVE_SESION)
    if not isinstance(actual, int) or not (0 <= actual < len(ARQUETIPOS)):
        st.session_state[_CLAVE_SESION] = 0
    idx = st.radio(
        "Perfil",
        options=range(len(ARQUETIPOS)),
        format_func=lambda i: labels[i],
        horizontal=True,
        key=_CLAVE_SESION,
        label_visibility="collapsed",
    )
    arquetipo = ARQUETIPOS[idx]
    st.caption(arquetipo["descripcion"])
    return arquetipo

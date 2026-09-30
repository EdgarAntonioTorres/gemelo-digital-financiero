"""
Página del chat — Centavo (`t081`)

UI mínima de chat sobre `assistant.router.responder_chat()`: selector
de perfil (compartido con el Simulador vía `perfiles_sinteticos.py`),
historial de conversación en `st.session_state`, y un expander opcional
para ver qué categoría/SQL/fragmentos usó cada respuesta — útil para
depurar durante `t082`, no pensado para el usuario final (por eso
queda colapsado por default).

Mismo criterio de ubicación que `1_Simulador.py`: vive en `pages/`,
Streamlit la detecta automáticamente.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator_engine import (  # noqa: E402
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
)
from perfiles_sinteticos import render_selector_perfil  # noqa: E402
from assistant.router import responder_chat  # noqa: E402

HISTORIAL_KEY = "historial_chat"


def _render_respuesta(texto: str) -> None:
    """st.markdown() interpreta cualquier texto entre 2 signos '$' como
    una fórmula LaTeX (KaTeX) — con 2+ montos en dólares en la misma
    respuesta, todo lo que queda entre el primer y el segundo '$' se
    trata como una ecuación, y LaTeX colapsa los espacios en blanco
    dentro de una fórmula. Es justo el bug reportado en Sesión 35 (el
    texto salía pegado tipo "2,845.98almes..."). Se escapan los '$'
    ANTES de renderizar, para que Streamlit los muestre como texto
    normal — el modelo sigue escribiendo montos con '$' con toda
    naturalidad (así lo pide el System Prompt, t075), el arreglo es
    puramente de presentación, no le pedimos a Centavo que cambie
    cómo escribe."""
    st.markdown(texto.replace("$", "\\$"))


@st.cache_resource
def _get_dw_connection():
    return get_dw_connection()


@st.cache_data
def _load_pool_and_data():
    conn = _get_dw_connection()
    df = load_fact_comportamiento(conn)
    pool = build_disponible_pool(df)
    return df, pool


def main() -> None:
    st.set_page_config(page_title="Centavo — Coach financiero", layout="wide")
    st.title("Centavo")
    st.caption(
        "Tu coach financiero. Pregúntame sobre tu situación, sobre conceptos "
        "financieros, o sobre tu última simulación."
    )

    try:
        df_comportamiento, _pool = _load_pool_and_data()
    except Exception as exc:
        st.error(f"No se pudo conectar a gold.fact_comportamiento: {exc}")
        return

    arquetipo = render_selector_perfil("Elige tu perfil")
    record_id = arquetipo["record_id"]
    fila = df_comportamiento.loc[df_comportamiento["record_id"] == record_id]
    if fila.empty:
        st.error(f"El perfil {record_id} no está en gold.fact_comportamiento.")
        return
    fila = fila.iloc[0]

    if HISTORIAL_KEY not in st.session_state:
        st.session_state[HISTORIAL_KEY] = []

    st.divider()

    for turno in st.session_state[HISTORIAL_KEY]:
        with st.chat_message(turno["role"]):
            if turno["role"] == "assistant":
                _render_respuesta(turno["content"])
            else:
                st.markdown(turno["content"])

    pregunta = st.chat_input("Escribe tu pregunta...")
    if pregunta:
        with st.chat_message("user"):
            st.markdown(pregunta)

        with st.chat_message("assistant"):
            with st.spinner("Centavo está pensando..."):
                resultado = responder_chat(
                    pregunta=pregunta,
                    record_id=record_id,
                    fila_perfil=fila,
                    ultima_simulacion=st.session_state.get("ultima_simulacion"),
                    historial=st.session_state[HISTORIAL_KEY],
                )
            _render_respuesta(resultado.respuesta)
            with st.expander("Ver detalle (categoría, SQL, fragmentos)"):
                st.write(f"Categoría detectada: **{resultado.categoria}**")
                st.json(resultado.detalle_debug)

        st.session_state[HISTORIAL_KEY].append({"role": "user", "content": pregunta})
        st.session_state[HISTORIAL_KEY].append(
            {"role": "assistant", "content": resultado.respuesta}
        )

    if st.session_state[HISTORIAL_KEY]:
        if st.button("Borrar conversación"):
            st.session_state[HISTORIAL_KEY] = []
            st.rerun()


if __name__ == "__main__":
    main()

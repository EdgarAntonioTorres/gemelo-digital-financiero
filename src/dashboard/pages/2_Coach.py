"""
Página del Chat — Centavo ("tu gemelo financiero")
Coach financiero empático, sin jerga bancaria (t074-t082).

Alineado al Manual de Identidad de Marca:
  - Header oficial con branding Moneta
  - Píldora contextual de simulación activa
  - Preguntas sugeridas interactivas por nivel
  - Tono pedagógico y conversacional
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.contexto_centavo import preguntas_sugeridas  # noqa: E402
from assistant.plan_engine import PerfilIncoherenteError  # noqa: E402
from assistant.router import responder_chat  # noqa: E402
from perfil_loader import PerfilNoEncontradoError, cargar_perfil  # noqa: E402
from perfiles_sinteticos import ARQUETIPOS  # noqa: E402
from simulator_engine import get_dw_connection  # noqa: E402
from styles import render_header_moneta  # noqa: E402

HISTORIAL_KEY = "historial_chat"
HISTORIAL_PERFIL_KEY = "historial_chat_record_id"
SUGERIDA_KEY = "pregunta_sugerida"


def _h(texto: str) -> str:
    """Texto para un bloque HTML: escapa el HTML y el '$'. El texto de la simulación
    trae varios montos y Streamlit lee dos '$' como LaTeX (Sesión 36)."""
    return html.escape(texto).replace("$", "&#36;")


def _render_respuesta(texto: str) -> None:
    """Escapa signos de dólar para evitar que Streamlit los interprete como LaTeX."""
    st.markdown(texto.replace("$", "\\$"))


@st.cache_resource
def _get_dw_connection():
    return get_dw_connection()


def _elegir_sugerida(pregunta: str) -> None:
    st.session_state[SUGERIDA_KEY] = pregunta


def main() -> None:
    # st.set_page_config(page_title="Moneta — Coach Centavo", layout="wide")

    # Header corporativo oficial Moneta
    render_header_moneta(
        titulo_panel="Coach Financiero — Centavo",
        subtitulo="Tu copiloto digital para traducir decisiones, optimizar gastos y planear metas sin jerga bancaria.",
    )

    idx = st.session_state.get("perfil_activo_idx", 0)
    arquetipo = ARQUETIPOS[idx]
    record_id = arquetipo["record_id"]

    try:
        cargado = cargar_perfil(_get_dw_connection(), record_id)
    except PerfilNoEncontradoError as exc:
        st.error(str(exc))
        return
    except PerfilIncoherenteError as exc:
        st.error(f"Incoherencia en los datos del perfil: {exc}")
        return
    except Exception as exc:
        st.error(f"No se pudo conectar a la base analítica Gold: {exc}")
        return

    # Si cambia el perfil, reiniciar conversación
    if st.session_state.get(HISTORIAL_PERFIL_KEY) != record_id:
        st.session_state[HISTORIAL_KEY] = []
        st.session_state[HISTORIAL_PERFIL_KEY] = record_id
    historial = st.session_state.setdefault(HISTORIAL_KEY, [])

    # Verificar si hay una simulación reciente del perfil activo
    ultima_simulacion = (
        st.session_state.get("ultima_simulacion")
        if st.session_state.get("ultima_simulacion_record_id") == record_id
        else None
    )

    if ultima_simulacion:
        st.markdown(
            f"""
            <div class="fintech-card" style="border-left: 3px solid #00F2FE; padding: 12px 18px; margin-bottom: 20px;">
                <div style="font-size: 0.8rem; color: #00F2FE; font-weight: 600; text-transform: uppercase;">
                    Contexto de Simulación Activo
                </div>
                <div style="font-size: 0.88rem; color: #CBD5E1; margin-top: 4px;">
                    {_h(ultima_simulacion)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div style="font-size: 0.82rem; color: #94A3B8; margin-bottom: 14px;">
            💡 <i>Centavo te asesora de forma educativa y personalizada. Todos los montos se expresan en USD.</i>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Renderizar historial de conversación
    for turno in historial:
        avatar = "🪙" if turno["role"] == "assistant" else "👤"
        with st.chat_message(turno["role"], avatar=avatar):
            if turno["role"] == "assistant":
                _render_respuesta(turno["content"])
            else:
                st.markdown(turno["content"].replace("$", "\\$"))

    # Entrada del usuario
    escrita = st.chat_input(
        "Pregúntale a Centavo (ej. ¿cómo puedo empezar mi colchón?)..."
    )
    pregunta = escrita or st.session_state.pop(SUGERIDA_KEY, None)

    # Sugerencias si el chat está vacío
    if not historial and not pregunta:
        st.markdown(
            "<p style='color: #94A3B8; font-size: 0.9rem; font-weight: 500;'>Preguntas frecuentes para iniciar:</p>",
            unsafe_allow_html=True,
        )
        sugeridas = preguntas_sugeridas(cargado)
        columnas = st.columns(2)
        for i, texto in enumerate(sugeridas):
            with columnas[i % 2]:
                st.button(
                    texto,
                    key=f"sugerida_{i}",
                    on_click=_elegir_sugerida,
                    args=(texto,),
                    use_container_width=True,
                )

    # Procesar turno de chat
    if pregunta:
        with st.chat_message("user", avatar="👤"):
            st.markdown(pregunta.replace("$", "\\$"))

        with st.chat_message("assistant", avatar="🪙"):
            with st.spinner("Centavo está analizando tu gemelo financiero..."):
                resultado = responder_chat(
                    pregunta=pregunta,
                    cargado=cargado,
                    ultima_simulacion=ultima_simulacion,
                    historial=historial,
                    nombre=arquetipo.get("nombre"),
                )
            _render_respuesta(resultado.respuesta)

            with st.expander("🛠️ Ver trazabilidad técnica (Auditoría del Asistente)"):
                st.caption(
                    f"Categoría identificada por el Router: **{resultado.categoria}**"
                )
                st.json(resultado.detalle_debug)

        historial.append({"role": "user", "content": pregunta})
        historial.append({"role": "assistant", "content": resultado.respuesta})

    # Botón de reinicio si hay mensajes
    if historial:
        st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
        col_espacio, col_btn = st.columns([8, 2])
        with col_btn:
            if st.button("Limpiar chat", use_container_width=True):
                st.session_state[HISTORIAL_KEY] = []
                st.rerun()


main()

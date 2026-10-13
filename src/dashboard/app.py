"""
Entrypoint principal de Moneta — Navegación Central y Login Simulado (t100/t102).
"""

from __future__ import annotations

import streamlit as st
from perfiles_sinteticos import ARQUETIPOS
from styles import render_header_moneta

st.set_page_config(
    page_title="Moneta — Tu gemelo financiero",
    page_icon="🪙",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Opciones de ingreso disponibles en el login
OPCIONES_LOGIN = [
    {
        "label": ARQUETIPOS[0]["label"],
        "tipo": "usuario",
        "idx_arquetipo": 0,
        "descripcion": ARQUETIPOS[0]["descripcion"],
        "record_id": ARQUETIPOS[0]["record_id"],
    },
    {
        "label": ARQUETIPOS[1]["label"],
        "tipo": "usuario",
        "idx_arquetipo": 1,
        "descripcion": ARQUETIPOS[1]["descripcion"],
        "record_id": ARQUETIPOS[1]["record_id"],
    },
    {
        "label": "Evaluador (Modo Admin)",
        "tipo": "admin",
        "idx_arquetipo": 0,  # usa por defecto Ana primeriza para las vistas de usuario
        "descripcion": (
            "Acceso técnico a métricas de SLAs, calidad de datos Great "
            "Expectations y auditoría del Lakehouse."
        ),
        "record_id": "ADMIN_METRICS",
    },
]


def _render_login():
    render_header_moneta(
        titulo_panel="Bienvenido a Moneta",
        subtitulo=(
            "Tu gemelo digital financiero para tomar decisiones "
            "informadas sin jerga bancaria."
        ),
    )
    st.markdown("---")

    col_izq, col_der = st.columns([1.2, 1.0], gap="large")

    with col_izq:
        st.subheader("Elige tu perfil de demostración para ingresar")
        st.caption("Selecciona el perfil con el que deseas interactuar:")

        labels = [op["label"] for op in OPCIONES_LOGIN]
        seleccion_idx = st.radio(
            "Selecciona un perfil:",
            options=range(len(OPCIONES_LOGIN)),
            format_func=lambda i: labels[i],
            key="login_selector_idx",
            label_visibility="collapsed",
        )

        perfil_sel = OPCIONES_LOGIN[seleccion_idx]

        borde_color = "#00F2FE" if perfil_sel["tipo"] == "usuario" else "#00E676"
        st.markdown(
            f"""
            <div class="fintech-card" style="margin-top: 15px; border-left: 3px solid {borde_color};">
                <div class="metric-title">{perfil_sel['label']}</div>
                <div style="font-size: 0.95rem; color: #F1F5F9; margin-top: 8px;">
                    {perfil_sel['descripcion']}
                </div>
                <div class="metric-sub" style="margin-top: 8px;">
                    Identificador: <code>{perfil_sel['record_id']}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("Entrar a Moneta", type="primary", use_container_width=True):
            st.session_state["perfil_activo_idx"] = perfil_sel["idx_arquetipo"]
            st.session_state["es_admin"] = perfil_sel["tipo"] == "admin"
            st.session_state["label_activo"] = perfil_sel["label"]
            st.session_state["record_id_activo"] = perfil_sel["record_id"]
            st.session_state["autenticado"] = True
            st.rerun()

    with col_der:
        st.markdown(
            """
            <div class="fintech-card">
                <div class="metric-title">Arquitectura Moneta</div>
                <div style="font-size: 0.9rem; line-height: 1.6; color: #CBD5E1; margin-top: 10px;">
                    Plataforma analítica y conversacional:
                    <ul>
                        <li><b>Perfiles Demo (Ana):</b> Experiencia interactiva para usuarios
                        jóvenes en inserción laboral.</li>
                        <li><b>Modo Admin / Mentor:</b> Observabilidad del Data Warehouse,
                        SLAs y alertas en vivo.</li>
                    </ul>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def main():
    if not st.session_state.get("autenticado", False):
        _render_login()
        return

    es_admin = st.session_state.get("es_admin", False)
    label_activo = st.session_state.get("label_activo", "Usuario")
    record_id_activo = st.session_state.get("record_id_activo", "")

    # Barra lateral con información de la sesión
    with st.sidebar:
        icono = "🛠️" if es_admin else "🪙"
        st.markdown(
            f"""
            <div style="padding: 10px 0 15px 0;">
                <div style="font-size: 0.75rem; color: #94A3B8; text-transform: uppercase; font-weight: 600;">
                    Sesión Activa
                </div>
                <div style="font-size: 1.05rem; font-weight: 700; color: #FFFFFF;">
                    {icono} {label_activo}
                </div>
                <div style="font-size: 0.8rem; color: #00F2FE;">
                    <code>{record_id_activo}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Cerrar sesión / Cambiar perfil", use_container_width=True):
            st.session_state["autenticado"] = False
            st.session_state.pop("historial_chat", None)
            st.session_state.pop("ultima_simulacion", None)
            st.rerun()

    # Páginas del Gemelo Digital
    pag_hoy = st.Page(
        "pages/0_Lo_que_tengo_hoy.py",
        title="Lo que tienes hoy",
        icon="📊",
        default=True,
    )
    pag_sim = st.Page("pages/1_Simulador.py", title="Lo que podrías tener", icon="🎯")
    pag_coach = st.Page("pages/2_Coach.py", title="Qué puedes hacer ahora", icon="💬")

    secciones = {
        "Tu Gemelo Digital": [pag_hoy, pag_sim, pag_coach],
    }

    # Si es Administrador / Mentor, se desbloquea el Quality Dashboard
    if es_admin:
        pag_calidad = st.Page(
            "quality_dashboard.py", title="Observabilidad y SLAs", icon="🛠️"
        )
        secciones["Panel de Auditoría (Admin)"] = [pag_calidad]

    nav = st.navigation(secciones)
    nav.run()


if __name__ == "__main__":
    main()

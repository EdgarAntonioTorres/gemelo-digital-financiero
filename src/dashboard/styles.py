"""
Módulo de Estilos y Branding — Moneta
Basado en el Manual de Identidad y Branding: Moneta ("tu gemelo financiero").

Tokens oficiales:
  - Deep Space Navy: #0B0F19 (Fondo canvas)
  - Surface Slate:   #161F30 (Contenedores y tarjetas)
  - Electric Cyan:   #00F2FE (Interacción, tecnología y gemelo digital)
  - Spring Emerald:  #00E676 (Salud positiva y crecimiento)
  - Electric Coral:  #FF5376 (Atención pedagógica y límites)
  - Muted Text:      #94A3B8 (Texto secundario y divisores)
  - Pure White:      #FFFFFF (Títulos y alto contraste)
"""

from __future__ import annotations
from pathlib import Path
import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "moneta_logo.png"


def aplicar_estilo_ejecutivo() -> None:
    """Inyecta el sistema de diseño del Manual de Identidad de Moneta."""
    st.markdown(
        """
        <style>
        /* Importar fuente oficial Inter */
        @import url(
            'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap'
        );

        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif !important;
        }

        /* Ocultar interfaz nativa de Streamlit */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* Canvas: Deep Space Navy (#0B0F19) */
        .stApp {
            background-color: #0B0F19 !important;
            color: #FFFFFF !important;
        }

        /* Ancho del contenedor y márgenes */
        .block-container {
            padding-top: 1.8rem !important;
            padding-bottom: 3.5rem !important;
            max-width: 1200px !important;
        }

        /* Contenedores UI: Surface Slate (#161F30) con curvatura 14px */
        .fintech-card {
            background-color: #161F30;
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 14px;
            padding: 22px 24px;
            margin-bottom: 14px;
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35);
        }

        .metric-title {
            font-size: 0.76rem;
            color: #94A3B8;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 6px;
            font-weight: 600;
        }

        .metric-value-lg {
            font-size: 1.9rem;
            font-weight: 700;
            color: #FFFFFF;
            letter-spacing: -0.02em;
        }

        .metric-sub {
            font-size: 0.82rem;
            color: #94A3B8;
            margin-top: 3px;
        }

        /* Badges funcionales oficiales */
        .badge-emerald {
            background: rgba(0, 230, 118, 0.12);
            color: #00E676;
            border: 1px solid rgba(0, 230, 118, 0.35);
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-block;
        }
        .badge-cyan {
            background: rgba(0, 242, 254, 0.12);
            color: #00F2FE;
            border: 1px solid rgba(0, 242, 254, 0.35);
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-block;
        }
        .badge-coral {
            background: rgba(255, 83, 118, 0.12);
            color: #FF5376;
            border: 1px solid rgba(255, 83, 118, 0.35);
            padding: 3px 10px;
            border-radius: 9999px;
            font-size: 0.78rem;
            font-weight: 600;
            display: inline-block;
        }

        /* Píldora del Asistente Centavo (Manual §6) */
        .centavo-pill {
            background-color: #161F30;
            border: 1px solid #00F2FE;
            border-radius: 9999px;
            padding: 10px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            margin-top: 16px;
            box-shadow: 0 0 14px rgba(0, 242, 254, 0.18);
        }

        /* Ajuste de contenedor de imagen para unificar fondo */
        .moneta-logo-box img {
            border-radius: 10px;
            background-color: #161F30;
            padding: 4px;
            border: 1px solid rgba(148, 163, 184, 0.15);
            object-fit: contain;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header_moneta(titulo_panel: str, subtitulo: str = "") -> None:
    """
    Renderiza el encabezado oficial:
    Isotipo/Logo + Wordmark 'moneta' + Tagline 'tu gemelo financiero'.
    """
    aplicar_estilo_ejecutivo()
    col_logo, col_txt = st.columns([0.8, 8.2], gap="small")

    with col_logo:
        if LOGO_PATH.exists():
            st.markdown('<div class="moneta-logo-box">', unsafe_allow_html=True)
            st.image(str(LOGO_PATH), width=58)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                "<div style='font-size: 2.2rem;'>🪙</div>", unsafe_allow_html=True
            )

    with col_txt:
        st.markdown(
            f"""
            <div style="display: flex; align-items: baseline; gap: 10px; margin-top: 2px;">
                (
                    '<span style="font-size: 1.6rem; font-weight: 800; color: #FFFFFF; '
                    'letter-spacing: -0.03em;">'
                )
                    moneta
                </span>
                (
                    '<span style="font-size: 0.95rem; color: #00F2FE; font-weight: 400; '
                    'letter-spacing: 0.05em;">'
                )
                    tu gemelo financiero
                </span>
                <span style="color: #94A3B8; font-size: 1.1rem; margin: 0 4px;">|</span>
                <span style="font-size: 1.15rem; font-weight: 600; color: #F1F5F9;">
                    {titulo_panel}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if subtitulo:
            st.caption(subtitulo)

    st.markdown(
        "<hr style='margin-top: 10px; margin-bottom: 24px; border: 0; "
        "border-top: 1px solid rgba(148, 163, 184, 0.15);'>",
        unsafe_allow_html=True,
    )

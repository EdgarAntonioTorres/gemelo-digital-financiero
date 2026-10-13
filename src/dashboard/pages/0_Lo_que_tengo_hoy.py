"""
Pantalla "Lo que tengo hoy" — Dashboard Personal Ejecutivo (Moneta)
Cumple con la Guía Maestra de Identidad y Branding de Moneta.

Sesión 36 (comentarios del mentor):
  * Los rangos, las etiquetas y la fórmula de Salud Financiera ya no viven aquí:
    salen de `assistant/indicadores.py`, la MISMA fuente que usa Centavo (antes la
    pantalla decía "Moderado" y el asistente decía que no existían umbrales).
  * IRFI e ICA se muestran en una barra de rango con su zona buena/regular/atención.
  * El gasto se categoriza con lo que la fuente realmente trae
    (`assistant/categorias_gasto.py`): vivienda, otros gastos básicos, gastos
    flexibles y "sin categorizar". Se muestran como categorías REPORTADAS, con la
    cobertura a la vista; nunca se reparte el gasto total por una proporción
    (la versión anterior mostraba $2,442 de "compromisos fijos" para una persona
    cuyo gasto esencial declarado es $1,787).
  * Las recomendaciones salen de los datos de la persona; no hay porcentajes ni
    estadísticas inventadas.
  * Sin valores por defecto silenciosos: si falta IRFI/ICA o el detalle de
    categorías, la pantalla lo dice en vez de inventar un 0.5 o un 0.60.
"""

from __future__ import annotations

import html
import math
import sys
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitAPIException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import categorias_gasto as cg  # noqa: E402
from assistant import indicadores as ind  # noqa: E402
from assistant.plan_engine import (  # noqa: E402
    MESES_COLCHON_MINIMO,
    UMBRAL_ENDEUDAMIENTO_MANEJABLE,
    PerfilIncoherenteError,
)
from perfil_loader import (  # noqa: E402
    PerfilCargado,
    PerfilNoEncontradoError,
    cargar_perfil,
)
from perfiles_sinteticos import ARQUETIPOS  # noqa: E402
from simulator_engine import get_dw_connection  # noqa: E402
from styles import render_header_moneta  # noqa: E402

TIPOS_DE_INGRESO = {
    "Salary": "Salario",
    "Mixed": "Mixto",
    "Freelance": "Independiente (freelance)",
}
COLOR_CYAN = "#00F2FE"
COLOR_EMERALD = "#00E676"
COLOR_CORAL = "#FF5376"
COLOR_SLATE = "#94A3B8"


@st.cache_resource
def _get_dw_connection():
    return get_dw_connection()


# --- Utilidades --------------------------------------------------------------
def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _md(texto: str) -> None:
    st.markdown(texto.replace("$", "\\$"), unsafe_allow_html=True)


def _cap(texto: str) -> None:
    st.caption(texto.replace("$", "\\$"))


def _h(texto: str) -> str:
    """Texto para un bloque HTML: escapa el HTML y el '$' (Streamlit lee dos '$'
    como LaTeX y se comería el texto entre ambos)."""
    return html.escape(texto).replace("$", "&#36;")


def _fondo_txt(meses: float) -> str:
    if math.isinf(meses):
        return "Sin gasto registrado."
    if meses < 1:
        return f"Cubre {meses * 30:.0f} días de gasto habitual."
    return f"Cubre {meses:.1f} meses de gasto habitual."


def _layout_transparente(
    fig: go.Figure, alto: int, margen: dict | None = None
) -> go.Figure:
    fig.update_layout(
        height=alto,
        margin=margen or {"l": 10, "r": 10, "t": 10, "b": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#FFFFFF", "family": "Inter, sans-serif"},
    )
    return fig


def _barra_rango(
    valor: float, segmentos: list[tuple[float, float, str, str]]
) -> go.Figure:
    """Barra horizontal 0-1 con 3 zonas de color y un marcador en el valor."""
    fig = go.Figure()
    for x0, x1, etiqueta, color in segmentos:
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=0.2,
            y1=0.8,
            fillcolor=color,
            opacity=0.35,
            line=dict(width=0),
            layer="below",
        )
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=0.5,
            text=etiqueta,
            showarrow=False,
            font=dict(size=11, color="#E2E8F0"),
        )
    fig.add_trace(
        go.Scatter(
            x=[min(max(valor, 0.0), 1.0)],
            y=[0.5],
            mode="markers",
            marker=dict(
                symbol="diamond",
                size=18,
                color="#FFFFFF",
                line=dict(color="#0B0F19", width=2),
            ),
            hovertemplate=f"{valor:.2f}<extra></extra>",
            showlegend=False,
        )
    )
    cortes = sorted({0.0, 1.0} | {s[0] for s in segmentos} | {s[1] for s in segmentos})
    fig.update_xaxes(
        range=[0, 1],
        tickvals=cortes,
        tickformat=".2f",
        showgrid=False,
        zeroline=False,
        color=COLOR_SLATE,
        tickfont=dict(size=10),
    )
    fig.update_yaxes(visible=False, range=[0, 1])
    return _layout_transparente(fig, 90, {"l": 8, "r": 8, "t": 4, "b": 26})


# --- Secciones de UI ---------------------------------------------------------
def _render_salud_financiera(c: PerfilCargado) -> None:
    st.subheader("1. Salud Financiera Moneta")
    nota = ind.salud_financiera(c.irfi, c.ica)
    lectura_salud = ind.lectura_salud(nota)
    lectura_irfi, lectura_ica = ind.lectura_irfi(c.irfi), ind.lectura_ica(c.ica)

    if nota is None:
        st.info(
            "Todavía no tenemos tu IRFI o tu ICA, así que no podemos calcular tu Salud "
            "Financiera. No usamos un valor supuesto: preferimos decírtelo."
        )
        return

    col_gauge, col_info = st.columns([1.1, 1.0], gap="medium")
    with col_gauge:
        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=nota,
                number={
                    "suffix": " / 100",
                    "font": {
                        "size": 34,
                        "color": "#FFFFFF",
                        "family": "Inter, sans-serif",
                    },
                },
                gauge={
                    "axis": {
                        "range": [0, 100],
                        "tickwidth": 1,
                        "tickcolor": COLOR_SLATE,
                        "tickmode": "array",
                        "tickvals": [
                            0,
                            ind.SALUD_CORTE_ESTABLE,
                            ind.SALUD_CORTE_OPTIMA,
                            100,
                        ],
                    },
                    "bar": {"color": COLOR_CYAN, "thickness": 0.28},
                    "bgcolor": "rgba(22, 31, 48, 0.4)",
                    "borderwidth": 0,
                    "steps": [
                        {
                            "range": [0, ind.SALUD_CORTE_ESTABLE],
                            "color": "rgba(255, 83, 118, 0.22)",
                        },
                        {
                            "range": [ind.SALUD_CORTE_ESTABLE, ind.SALUD_CORTE_OPTIMA],
                            "color": "rgba(0, 242, 254, 0.20)",
                        },
                        {
                            "range": [ind.SALUD_CORTE_OPTIMA, 100],
                            "color": "rgba(0, 230, 118, 0.22)",
                        },
                    ],
                },
            )
        )
        st.plotly_chart(
            _layout_transparente(fig, 250, {"l": 25, "r": 25, "t": 25, "b": 25}),
            use_container_width=True,
        )

    with col_info:
        plan = c.plan
        st.markdown(
            f"""
            <div class="fintech-card">
                <div class="metric-title">Diagnóstico del Gemelo Digital</div>
                <div style="margin-bottom: 10px; font-size: 0.95rem;">Salud financiera:
                    <span class="{lectura_salud.badge}">{lectura_salud.etiqueta}</span></div>
                <div style="font-size: 0.9rem; margin-bottom: 8px;">
                    <b>Riesgo (IRFI):</b> <span class="{lectura_irfi.badge}">{lectura_irfi.etiqueta}</span>
                    <code>{c.irfi:.2f}</code></div>
                <div style="font-size: 0.9rem; margin-bottom: 8px;">
                    <b>Capacidad de ahorro (ICA):</b> <span class="{lectura_ica.badge}">{lectura_ica.etiqueta}</span>
                    <code>{c.ica:.2f}</code></div>
                <div style="font-size: 0.9rem;">
                    <b>Nivel de madurez:</b> {plan.nivel} · {_h(plan.nombre_nivel)}</div>
                <div class="metric-sub">El nivel mide tus hábitos de deuda y colchón, no lo que sabes.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("**Dónde caen tus indicadores**")
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.markdown(f"**Riesgo (IRFI)** · más bajo es mejor · tú: `{c.irfi:.2f}`")
        st.plotly_chart(
            _barra_rango(
                c.irfi,
                [
                    (0.0, ind.IRFI_CORTE_BAJO, "Bajo", COLOR_EMERALD),
                    (ind.IRFI_CORTE_BAJO, ind.IRFI_CORTE_ALTO, "Moderado", COLOR_CYAN),
                    (ind.IRFI_CORTE_ALTO, 1.0, "Alto", COLOR_CORAL),
                ],
            ),
            use_container_width=True,
            key="barra_irfi",
        )
        _cap(ind.rango_irfi())
    with c2:
        st.markdown(
            f"**Capacidad de ahorro (ICA)** · más alto es mejor · tú: `{c.ica:.2f}`"
        )
        st.plotly_chart(
            _barra_rango(
                c.ica,
                [
                    (0.0, ind.ICA_CORTE_BAJO, "Baja", COLOR_CORAL),
                    (ind.ICA_CORTE_BAJO, ind.ICA_CORTE_ALTO, "Media", COLOR_CYAN),
                    (ind.ICA_CORTE_ALTO, 1.0, "Alta", COLOR_EMERALD),
                ],
            ),
            use_container_width=True,
            key="barra_ica",
        )
        _cap(ind.rango_ica())

    with st.expander("ℹ️ ¿Cómo se leen estos indicadores? (Enfoque pedagógico Moneta)"):
        st.markdown(
            f"""
            * **{ind.NOMBRE_IRFI} (IRFI):** va de 0 a 1 y **más bajo es mejor**. Resume qué tan
              expuesto estás a un problema financiero: pesa sobre todo cuánto de tu ingreso se va
              en deudas, y también la estabilidad de tu ingreso y tu vivienda.
            * **{ind.NOMBRE_ICA} (ICA):** va de 0 a 1 y **más alto es mejor**. Mide cuánto margen
              tienes para ahorrar, a partir de la carga de tus deudas, la estabilidad de tu ingreso
              y tu vivienda.
            * **Salud Financiera:** una nota de 0 a 100 que combina los dos
              ({ind.formula_salud()}). Rangos: {ind.rango_salud()}.
            * **Es un estimado.** En esta fuente de datos varios componentes del IRFI y del ICA no
              se observan y se fijan en un valor neutro, así que léelos como una guía para
              empezar, no como una calificación definitiva.
            """.replace(
                "$", "\\$"
            )
        )


def _render_resumen_mes(c: PerfilCargado) -> None:
    p = c.perfil
    st.subheader("2. Flujo Mensual")
    c1, c2, c3, c4 = st.columns(4)

    tasa_ahorro = (
        (p.ahorro_mes / p.ingreso_mensual * 100) if p.ingreso_mensual > 0 else 0
    )
    tipo = TIPOS_DE_INGRESO.get(
        str(c.comportamiento["income_type"]), str(c.comportamiento["income_type"])
    )
    c1.metric("Ingreso Neto", _usd(p.ingreso_mensual))
    c1.caption(f"Tipo de ingreso: {tipo}")
    c2.metric("Gasto Total", _usd(p.gasto_mensual))
    c3.metric(
        "Ahorro del Mes", _usd(p.ahorro_mes), delta=f"{tasa_ahorro:.0f}% del ingreso"
    )
    c4.metric("Inversión / Retiro", _usd(p.inversion_mensual))

    # A dónde va cada $100 que ganas (aritmética directa de ingreso, gasto y ahorro).
    if p.ingreso_mensual > 0 and p.gasto_mensual < p.ingreso_mensual:
        gasto_pct = p.gasto_mensual / p.ingreso_mensual * 100
        fig = go.Figure()
        for nombre, valor, color in (
            ("Gasto", gasto_pct, COLOR_CORAL),
            ("Ahorro", 100 - gasto_pct, COLOR_EMERALD),
        ):
            fig.add_trace(
                go.Bar(
                    y=["Cada $100"],
                    x=[valor],
                    name=nombre,
                    orientation="h",
                    marker_color=color,
                    text=f"{nombre}: ${valor:,.0f}",
                    textposition="inside",
                    hovertemplate=f"{nombre}: ${valor:,.0f} de cada $100<extra></extra>",
                )
            )
        fig.update_layout(barmode="stack", showlegend=False)
        fig.update_xaxes(visible=False, range=[0, 100])
        fig.update_yaxes(visible=False)
        st.plotly_chart(
            _layout_transparente(fig, 70, {"l": 0, "r": 0, "t": 0, "b": 0}),
            use_container_width=True,
            key="barra_flujo",
        )
        _cap("De cada $100 que ganas, esto se va en gasto y esto queda como ahorro.")
    elif p.ingreso_mensual > 0:
        st.info(
            "Este mes tus gastos igualan o superan tu ingreso, así que no queda ahorro."
        )


def _render_categorizacion_gastos(c: PerfilCargado) -> None:
    d, p = c.detalle, c.perfil
    st.subheader("3. ¿En qué se va tu dinero?")
    g = cg.desde_detalle(p, d)
    suscripciones = int(d.get("suscripciones_activas", 0))

    if g is None:
        _render_gastos_solo_proporcion(c, suscripciones)
        return

    col_chart, col_cards = st.columns([1.2, 1.0], gap="medium")
    colores = {
        cg.VIVIENDA: "rgba(0, 242, 254, 0.95)",
        cg.OTROS_BASICOS: "rgba(0, 242, 254, 0.45)",
        cg.FLEXIBLES: COLOR_CORAL,
        cg.SIN_CATEGORIZAR: COLOR_SLATE,
    }
    with col_chart:
        fig = go.Figure()
        for nombre, monto in g.partes():
            fig.add_trace(
                go.Bar(
                    y=["Gasto"],
                    x=[monto],
                    name=nombre,
                    orientation="h",
                    marker_color=colores[nombre],
                    text=f"{g.porcentaje(monto):.0f}%",
                    textposition="inside",
                    hovertemplate=f"{nombre}: ${monto:,.0f} ({g.porcentaje(monto):.0f}%)<extra></extra>",
                )
            )
        fig.update_layout(
            barmode="stack",
            legend=dict(orientation="h", y=-0.35, x=0, font=dict(size=11)),
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        st.plotly_chart(
            _layout_transparente(fig, 150, {"l": 0, "r": 0, "t": 0, "b": 50}),
            use_container_width=True,
            key="barra_gastos",
        )
        if g.cuadra_con_el_total:
            _cap(
                f"Cobertura: las categorías que reporta la fuente explican "
                f"{g.cobertura * 100:.0f}% de tu gasto total ({_usd(g.gasto_total)}); "
                f"el resto ({_usd(g.sin_categorizar)}) no viene categorizado."
            )
        else:
            _cap(
                f"La fuente reporta estas categorías por separado y suman {_usd(g.categorizado)}, "
                f"{_usd(g.exceso)} más que tu gasto total ({_usd(g.gasto_total)}). Por eso se "
                "muestran como proporciones de lo categorizado, no como partes del total."
            )

    with col_cards:
        vivienda_pct = (
            f"{g.vivienda_pct_ingreso * 100:.0f}% de tu ingreso"
            if g.vivienda_pct_ingreso is not None
            else ""
        )
        st.markdown(
            f"""
            <div class="fintech-card">
                <div class="metric-title">{_h(cg.VIVIENDA)}</div>
                <div class="metric-value-lg">{_h(_usd(g.vivienda))}</div>
                <div class="metric-sub">{_h(vivienda_pct)}</div>
            </div>
            <div class="fintech-card">
                <div class="metric-title">{_h(cg.FLEXIBLES)}</div>
                <div class="metric-value-lg">{_h(_usd(g.flexibles))}</div>
                <div class="metric-sub">{g.porcentaje(g.flexibles):.0f}% del gasto · lo que más se puede ajustar</div>
            </div>
            <div class="fintech-card">
                <div class="metric-title">Suscripciones</div>
                <div class="metric-value-lg">{suscripciones} activas</div>
                <div class="metric-sub">Solo conocemos cuántas son, no cuánto cuestan</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.caption(
        "Hoy distinguimos vivienda, otros gastos básicos y gastos flexibles porque es lo que "
        "reporta la fuente de datos. Con tus transacciones reales, este desglose se haría por "
        "comercio (comida, transporte, entretenimiento…)."
    )


def _render_gastos_solo_proporcion(c: PerfilCargado, suscripciones: int) -> None:
    """Vista de respaldo: si el detalle de categorías aún no está en Gold (migración
    SQL sin correr), solo se muestra la proporción, sin montos inventados."""
    d = c.detalle
    try:
        esencial = float(d["proporcion_esencial"])
    except (KeyError, TypeError, ValueError):
        st.info("Todavía no tenemos el detalle de tus categorías de gasto.")
        return
    fig = go.Figure()
    for nombre, valor, color in (
        ("Gasto básico", esencial * 100, "rgba(0, 242, 254, 0.8)"),
        ("Gasto flexible", (1 - esencial) * 100, COLOR_CORAL),
    ):
        fig.add_trace(
            go.Bar(
                y=["Gasto"],
                x=[valor],
                name=nombre,
                orientation="h",
                marker_color=color,
                text=f"{valor:.0f}%",
                textposition="inside",
            )
        )
    fig.update_layout(barmode="stack", legend=dict(orientation="h", y=-0.35, x=0))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    st.plotly_chart(
        _layout_transparente(fig, 140, {"l": 0, "r": 0, "t": 0, "b": 50}),
        use_container_width=True,
        key="barra_gastos_prop",
    )
    _cap(
        "Es la proporción entre tu gasto básico y tu gasto flexible; no es el desglose de tu "
        f"gasto total. Suscripciones activas: {suscripciones}."
    )


def _render_recomendaciones_recorte(c: PerfilCargado) -> None:
    d, plan, p = c.detalle, c.plan, c.perfil
    suscripciones = int(d.get("suscripciones_activas", 0))
    g = cg.desde_detalle(p, d)

    st.subheader("4. Oportunidades de Optimización")
    with st.container(border=True):
        st.markdown("**Palancas que salen de tus datos:**")
        c1, c2 = st.columns(2)

        with c1:
            if suscripciones >= 3:
                _md(
                    f"• **Suscripciones ({suscripciones} activas):** revisa cuáles usas de verdad. "
                    "Cancelar las que no usas libera dinero cada mes sin cambiar tu rutina."
                )
            else:
                _md(
                    f"• **Suscripciones ({suscripciones}):** tu volumen de pagos recurrentes está controlado."
                )
            if g is not None and g.flexibles > 0:
                _md(
                    f"• **Gastos flexibles ({_usd(g.flexibles)}):** es el rubro que más fácil se "
                    f"ajusta. Como ejemplo, recortar 10% serían {_usd(g.recorte_ilustrativo(0.10))} "
                    "más al mes para tu ahorro (un ejemplo, no una meta)."
                )
            _md(
                "• **Hábitos que suelen bajar los gastos flexibles:** cocinar en casa más días, "
                "elegir lugares más económicos cuando salgas a comer y anotar durante una semana "
                "tus gastos pequeños para ver a dónde se van."
            )

        with c2:
            if plan.fondo_meses < MESES_COLCHON_MINIMO:
                _md(
                    f"• **Prioridad de liquidez ({plan.fondo_meses:.1f} meses cubiertos):** el primer "
                    f"objetivo es llegar a {MESES_COLCHON_MINIMO} meses de gasto antes de "
                    "comprometerte con nuevas compras a plazos."
                )
            else:
                _md(
                    f"• **Colchón sólido ({plan.fondo_meses:.1f} meses cubiertos):** tienes margen para "
                    "planear metas de mediano plazo o inversión."
                )
            if plan.progreso_meta is not None and not plan.meta_cumplida:
                _md(
                    f"• **Meta de ahorro mensual:** te faltan {_usd(plan.falta_meta_mensual)} al mes "
                    f"para completarla ({plan.progreso_meta * 100:.0f}% de avance)."
                )

        st.markdown(
            """
            <div class="centavo-pill">
                <span style="font-size: 1.3rem;">🪙</span>
                <span style="font-size: 0.9rem; color: #FFFFFF;">
                    <b>Centavo:</b> "¿Quieres que armemos juntos un plan para ajustar "
                    "estos gastos sin sacrificar tu estilo de vida?"
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        try:
            st.page_link(
                "pages/2_Coach.py", label="Ir a conversar con Centavo", icon="💬"
            )
        except StreamlitAPIException:
            pass


def _render_colchon_y_meta(c: PerfilCargado) -> None:
    p, plan = c.perfil, c.plan
    st.subheader("5. Colchón de Emergencia y Progreso")

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Fondo de Emergencia Acumulado", _usd(p.fondo_emergencia_usd))
        _cap(_fondo_txt(plan.fondo_meses))

    with c2:
        tope = UMBRAL_ENDEUDAMIENTO_MANEJABLE * 100
        st.metric(
            "Compromiso en Deudas",
            f"${plan.de_cada_100_a_deuda:.0f} de cada $100",
            help=f"Lo manejable es hasta ${tope:.0f} de cada $100 que ganas.",
        )
        _cap(f"Tope manejable de referencia: ${tope:.0f} por cada $100.")

    if plan.progreso_meta is not None:
        st.write("**Progreso hacia tu meta de ahorro mensual:**")
        st.progress(min(max(plan.progreso_meta, 0.0), 1.0))
        if plan.meta_cumplida:
            st.success("¡Meta mensual alcanzada con éxito!")
        else:
            _cap(
                f"Llevas {_usd(plan.ahorro_mes)} de {_usd(p.meta_ahorro_mensual)} "
                f"({plan.progreso_meta * 100:.0f}%). "
                f"Faltan {_usd(plan.falta_meta_mensual)} para completarla este mes."
            )


def _render_navegacion() -> None:
    st.divider()
    col1, col2 = st.columns(2)
    for col, ruta, etiqueta in (
        (col1, "pages/1_Simulador.py", "Ir al Simulador de Metas"),
        (col2, "pages/2_Coach.py", "Consultar con Centavo"),
    ):
        with col:
            try:
                st.page_link(ruta, label=etiqueta)
            except StreamlitAPIException:
                pass


def main() -> None:
    # st.set_page_config(page_title="Moneta — Lo que tengo hoy", layout="wide")

    render_header_moneta(
        titulo_panel="Lo que tengo hoy",
        subtitulo="Fotografía ejecutiva de salud financiera, compromisos fijos y hábitos de gasto.",
    )

    idx = st.session_state.get("perfil_activo_idx", 0)
    arquetipo = ARQUETIPOS[idx]
    st.divider()

    try:
        cargado = cargar_perfil(_get_dw_connection(), arquetipo["record_id"])
    except PerfilNoEncontradoError as exc:
        st.error(str(exc))
        return
    except PerfilIncoherenteError as exc:
        st.error(f"Incoherencia en los datos del perfil: {exc}")
        return
    except Exception as exc:
        st.error(f"No se pudo conectar a la capa Gold: {exc}")
        return

    _render_salud_financiera(cargado)
    st.divider()
    _render_resumen_mes(cargado)
    st.divider()
    _render_categorizacion_gastos(cargado)
    st.divider()
    _render_recomendaciones_recorte(cargado)
    st.divider()
    _render_colchon_y_meta(cargado)
    _render_navegacion()


main()

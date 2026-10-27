"""
Dashboard Técnico de Calidad, Observabilidad y Gobierno — Fase 6 (`t085`)
Alineado al Manual de Marca y Sistema de Diseño Moneta.

Paneles consolidados:
  1. Alertas operativas y SLAs (operational.pipeline_alerts).
  2. Calidad de datos y cuarentena (operational.quality_metrics).
  3. Tiempos de ejecución vs. SLAs (operational.pipeline_execution_log).
  4. Ingresos vs. gastos por segmento (gold.fact_comportamiento).
  5. KPIs de riesgo (IRFI/ICA) y ahorro por segmento (gold.fact_kpi_perfil).
  6. Catálogo funcional y Gobierno del Dato DAMA-DMBOK (data_catalog.py).
"""

from __future__ import annotations

import html
import os
import pandas as pd
import plotly.graph_objects as go
import psycopg2
import streamlit as st
import textwrap

from styles import render_header_moneta
from data_catalog import DAMA_DOMINIOS, INVENTARIO_TABLAS

# Tokens de color del Manual de Marca Moneta
COLOR_CYAN = "#00F2FE"
COLOR_EMERALD = "#00E676"
COLOR_CORAL = "#FF5376"
COLOR_SLATE = "#94A3B8"
COLOR_BG_CARD = "#161F30"

DEFAULT_TASK_SLA_SECONDS = 300.0
SLA_THRESHOLDS_SECONDS = {
    "ingest_loan_default": 240.0,
    "ingest_credit_risk": 240.0,
    "ingest_personal_finance_tracker": 240.0,
    "build_silver_loan_default": 300.0,
    "build_silver_credit_risk": 300.0,
    "build_silver_personal_finance_tracker": 300.0,
    "build_silver_master": 300.0,
    "calculate_kpis": 300.0,
    "build_fact_comportamiento": 300.0,
    "load_gold_postgres": 300.0,
    "load_fact_comportamiento_postgres": 300.0,
}


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


@st.cache_resource
def get_dw_connection():
    return psycopg2.connect(
        host=get_required_env("DW_POSTGRES_HOST"),
        dbname=get_required_env("DW_POSTGRES_DB"),
        user=get_required_env("DW_POSTGRES_USER"),
        password=get_required_env("DW_POSTGRES_PASSWORD"),
    )


def _layout_transparente(
    fig: go.Figure, alto: int = 320, margen: dict | None = None
) -> go.Figure:
    fig.update_layout(
        height=alto,
        margin=margen or {"l": 15, "r": 15, "t": 30, "b": 25},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#FFFFFF", "family": "Inter, sans-serif"},
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, color=COLOR_SLATE)
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.1)",
        zeroline=False,
        color=COLOR_SLATE,
    )
    return fig


# --- Consultas SQL ---
def load_pipeline_alerts() -> pd.DataFrame:
    query = """
        SELECT id, alert_timestamp, alert_type, dag_id, task_id,
               run_id, execution_date, severity, message, details
        FROM operational.pipeline_alerts
        ORDER BY alert_timestamp DESC
    """
    return pd.read_sql(query, get_dw_connection())


def load_quality_metrics() -> pd.DataFrame:
    query = """
        SELECT run_timestamp, source, valid_rows, quarantined_rows,
               total_rows, pass_rate_records, ge_expectations_total,
               ge_expectations_passed, ge_pass_rate_rules
        FROM operational.quality_metrics
        ORDER BY run_timestamp DESC
    """
    return pd.read_sql(query, get_dw_connection())


def load_pipeline_execution_log() -> pd.DataFrame:
    query = """
        SELECT script_name, run_timestamp, duration_seconds, status
        FROM operational.pipeline_execution_log
        ORDER BY run_timestamp DESC
    """
    return pd.read_sql(query, get_dw_connection())


def load_fact_comportamiento() -> pd.DataFrame:
    query = """
        SELECT record_id, fuente, segmento, income_type, ingreso_mensual,
               gasto_promedio_3m, ratio_endeudamiento, alerta_fraude,
               suscripciones_por_1000_ingreso, fondo_emergencia_meses
        FROM gold.fact_comportamiento
        ORDER BY record_id
    """
    return pd.read_sql(query, get_dw_connection())


def load_fact_kpi_perfil() -> pd.DataFrame:
    query = """
        SELECT record_id, fuente, segmento, irfi, ica,
               default_flag_unificada, irfi_proxy_flag, ica_proxy_flag
        FROM gold.fact_kpi_perfil
    """
    return pd.read_sql(query, get_dw_connection())


# --- Componentes de UI ---
def render_alerts_and_timing_tab():
    st.markdown("### Observabilidad Operativa y Desempeño de SLAs")
    st.caption(
        "Auditoría de ejecución, alertas automáticas en Postgres y "
        "cumplimiento de SLAs contractuales."
    )

    try:
        df_alerts = load_pipeline_alerts()
    except Exception:
        df_alerts = pd.DataFrame()

    c1, c2, c3 = st.columns(3)
    criticas = (
        len(df_alerts[df_alerts["severity"] == "CRITICAL"])
        if not df_alerts.empty
        else 0
    )
    warnings = (
        len(df_alerts[df_alerts["severity"] == "WARNING"]) if not df_alerts.empty else 0
    )
    sla_misses = (
        len(df_alerts[df_alerts["alert_type"] == "SLA_MISS"])
        if not df_alerts.empty
        else 0
    )

    with c1:
        st.markdown(
            f"""
            <div class="fintech-card">
                <div class="metric-title">Incidentes Críticos</div>
                <div class="metric-value-lg" style="color: {'#FF5376' if criticas > 0 else '#00E676'};">
                    {criticas}
                </div>
                <div class="metric-sub">Fallas que requirieron rollback o reintento</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="fintech-card">
                <div class="metric-title">Violaciones de SLA</div>
                <div class="metric-value-lg" style="color: {'#00F2FE' if sla_misses == 0 else '#FF5376'};">
                    {sla_misses}
                </div>
                <div class="metric-sub">Límite contractual (4 min ingesta / 5 min transf.)</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="fintech-card">
                <div class="metric-title">Advertencias Operativas</div>
                <div class="metric-value-lg">{warnings}</div>
                <div class="metric-sub">Eventos informativos o de backoff</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    st.markdown("#### Duración de Tareas vs. Límite de SLA (Última Corrida)")

    try:
        df_timing = load_pipeline_execution_log()
    except Exception:
        df_timing = pd.DataFrame()

    if not df_timing.empty:
        latest_timing = (
            df_timing.sort_values("run_timestamp").groupby("script_name").tail(1).copy()
        )
        latest_timing["sla_limit_seconds"] = latest_timing["script_name"].map(
            lambda name: SLA_THRESHOLDS_SECONDS.get(name, DEFAULT_TASK_SLA_SECONDS)
        )

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=latest_timing["script_name"],
                y=latest_timing["duration_seconds"],
                name="Duración Real (s)",
                marker_color=COLOR_CYAN,
                hovertemplate="%{x}: %{y:.1f}s<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=latest_timing["script_name"],
                y=latest_timing["sla_limit_seconds"],
                name="Límite SLA (s)",
                marker_color=COLOR_SLATE,
                opacity=0.45,
                hovertemplate="Límite: %{y:.0f}s<extra></extra>",
            )
        )
        fig.update_layout(barmode="group")
        st.plotly_chart(_layout_transparente(fig, 340), use_container_width=True)
    else:
        st.info("Sin registros de ejecución en operational.pipeline_execution_log.")

    if not df_alerts.empty:
        with st.expander(
            "Ver bitácora detallada de incidentes (operational.pipeline_alerts)"
        ):
            st.dataframe(
                df_alerts[
                    [
                        "alert_timestamp",
                        "severity",
                        "alert_type",
                        "dag_id",
                        "task_id",
                        "message",
                    ]
                ],
                use_container_width=True,
            )


def render_quality_tab():
    st.markdown("### Calidad de Datos y Cuarentena")
    st.caption(
        "Verificación de expectativas analíticas (Great Expectations) "
        "sobre fuentes Bronze y Silver."
    )

    try:
        df_quality = load_quality_metrics()
    except Exception as exc:
        st.error(f"Error consultando operational.quality_metrics: {exc}")
        return

    if df_quality.empty:
        st.info("No se han registrado reportes de calidad aún.")
        return

    latest_ts = df_quality["run_timestamp"].max()
    latest = df_quality[df_quality["run_timestamp"] == latest_ts]

    cols = st.columns(len(latest))
    for col, (_, row) in zip(cols, latest.iterrows()):
        pass_pct = row["pass_rate_records"] * 100.0
        badge = "badge-emerald" if pass_pct >= 99.0 else "badge-coral"
        with col:
            st.markdown(
                f"""
                <div class="fintech-card">
                    <div class="metric-title">{row['source']}</div>
                    <div class="metric-value-lg">{pass_pct:.2f}%</div>
                    <div style="margin-top: 8px;">
                        <span class="{badge}">
                            GE: {row['ge_expectations_passed']}/{row['ge_expectations_total']} reglas OK
                        </span>
                    </div>
                    <div class="metric-sub" style="margin-top: 6px;">
                        {row['quarantined_rows']} filas en cuarentena de {row['total_rows']:,}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin-top: 25px;'></div>", unsafe_allow_html=True)
    st.markdown("#### Tasa de Conformidad de Registros por Fuente (%)")
    fig = go.Figure()
    colores_fuente = {
        "loan_default": COLOR_CYAN,
        "credit_risk": COLOR_EMERALD,
        "personal_finance_tracker": "#D946EF",
    }
    for fuente in df_quality["source"].unique():
        df_f = df_quality[df_quality["source"] == fuente].sort_values("run_timestamp")
        fig.add_trace(
            go.Scatter(
                x=df_f["run_timestamp"],
                y=df_f["pass_rate_records"] * 100.0,
                mode="lines+markers",
                name=fuente,
                line=dict(color=colores_fuente.get(fuente, COLOR_SLATE), width=2.5),
                marker=dict(size=6),
            )
        )
    fig.update_yaxes(range=[90, 101])
    st.plotly_chart(_layout_transparente(fig, 300), use_container_width=True)

    with st.expander("Ver tabla de corridas de validación"):
        st.dataframe(df_quality, use_container_width=True)


def render_gold_analytics_tab():
    st.markdown("### Perfiles y Comportamiento en Capa Gold")
    st.caption("Distribución analítica agregada para validación de features y modelos.")

    try:
        df_comp = load_fact_comportamiento()
        df_kpi = load_fact_kpi_perfil()
    except Exception as exc:
        st.error(f"Error consultando tablas Gold: {exc}")
        return

    c1, c2 = st.columns(2, gap="medium")

    with c1:
        st.markdown("#### Ingreso vs. Gasto Promedio por Segmento")
        con_seg = df_comp[df_comp["segmento"].notna()]
        if not con_seg.empty:
            res_seg = (
                con_seg.groupby("segmento")[["ingreso_mensual", "gasto_promedio_3m"]]
                .mean()
                .reset_index()
            )
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    x=res_seg["segmento"],
                    y=res_seg["ingreso_mensual"],
                    name="Ingreso Neto",
                    marker_color=COLOR_EMERALD,
                )
            )
            fig.add_trace(
                go.Bar(
                    x=res_seg["segmento"],
                    y=res_seg["gasto_promedio_3m"],
                    name="Gasto 3M",
                    marker_color=COLOR_CORAL,
                )
            )
            fig.update_layout(barmode="group")
            st.plotly_chart(_layout_transparente(fig, 300), use_container_width=True)

    with c2:
        st.markdown("#### IRFI e ICA Promedio por Segmento")
        con_kpi_seg = df_kpi[df_kpi["segmento"].notna()]
        if not con_kpi_seg.empty:
            res_kpi = (
                con_kpi_seg.groupby("segmento")[["irfi", "ica"]].mean().reset_index()
            )
            fig_kpi = go.Figure()
            fig_kpi.add_trace(
                go.Bar(
                    x=res_kpi["segmento"],
                    y=res_kpi["irfi"],
                    name="IRFI (Riesgo)",
                    marker_color=COLOR_CORAL,
                )
            )
            fig_kpi.add_trace(
                go.Bar(
                    x=res_kpi["segmento"],
                    y=res_kpi["ica"],
                    name="ICA (Capacidad)",
                    marker_color=COLOR_CYAN,
                )
            )
            fig_kpi.update_layout(barmode="group")
            st.plotly_chart(
                _layout_transparente(fig_kpi, 300), use_container_width=True
            )

    st.markdown("#### Explorador de Registros Sintéticos (Gold)")
    segmentos = ["Todos"] + sorted(df_comp["segmento"].dropna().unique().tolist())
    filtro_seg = st.selectbox("Filtrar registros por segmento:", segmentos)
    tabla_filtrada = (
        df_comp if filtro_seg == "Todos" else df_comp[df_comp["segmento"] == filtro_seg]
    )

    st.dataframe(
        tabla_filtrada[
            [
                "record_id",
                "segmento",
                "income_type",
                "ingreso_mensual",
                "gasto_promedio_3m",
                "ratio_endeudamiento",
                "alerta_fraude",
            ]
        ],
        use_container_width=True,
    )


def render_data_governance_tab():
    st.markdown("### 🏛️ Gobierno del Dato, DAMA-DMBOK y Catálogo Funcional")
    st.caption(
        "Inventario integral de tablas, asignación de Data Owners, linaje de negocio "
        "y diccionario de campos."
    )

    with st.expander("📚 Marco de Gobierno de Datos Moneta (Alineado a DAMA-DMBOK)"):
        for dominio, detalle in DAMA_DOMINIOS.items():
            st.markdown(f"**• {dominio}:** {detalle}")

    st.markdown("---")

    tablas_disponibles = list(INVENTARIO_TABLAS.keys())
    tabla_sel = st.selectbox(
        "Selecciona la tabla que deseas auditar:",
        tablas_disponibles,
        format_func=lambda t: f"{t} — {INVENTARIO_TABLAS[t]['data_owner']}",
    )

    info = INVENTARIO_TABLAS[tabla_sel]

    col1, col2 = st.columns([1.2, 1.0], gap="medium")
    with col1:
        st.markdown(
            f"""
            <div class="fintech-card" style="border-left: 3px solid #00F2FE;">
                <div class="metric-title">{info['nombre_tecnico']}</div>
                <div style="font-size: 0.95rem; color: #FFFFFF; margin-top: 6px; line-height: 1.5;">
                    {info['descripcion_funcional']}
                </div>
                <div style="margin-top: 12px; font-size: 0.85rem; color: #94A3B8; line-height: 1.6;">
                    <b>Capa:</b> {info['capa']}<br>
                    <b>Granularidad:</b> {info['grano']}<br>
                    <b>Frecuencia de Actualización:</b> {info['frecuencia_actualizacion']}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="fintech-card" style="border-left: 3px solid #00E676;">
                <div class="metric-title">Gobierno y Localización Física</div>
                <div style="margin-top: 8px; font-size: 0.88rem; color: #F1F5F9; line-height: 1.6;">
                    <b>👤 Data Owner:</b> {info['data_owner']}<br>
                    <b>🛠️ Custodio Técnico:</b> {info['custodio_tecnico']}<br>
                    <b>🔒 Clasificación de Seguridad:</b> {info['sensibilidad']}<br>
                    <b>📍 Ubicación en DW:</b> <code>{info['ubicacion_dw']}</code><br>
                    <b>📦 Formato de Almacenamiento:</b> <code>{info['formato_origen']}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    st.markdown("#### 📖 Diccionario Funcional de Campos")
    st.caption(
        "Descripción accesible de negocio, reglas de derivación y desglose de siglas."
    )

    filtro_campo = st.text_input(
        "🔍 Filtrar campos por nombre o palabra clave:", "", key="filtro_campos"
    )

    campos_lista = info["campos"]
    if filtro_campo.strip():
        f = filtro_campo.lower()
        campos_lista = [
            c
            for c in campos_lista
            if f in c["campo"].lower()
            or f in c["descripcion"].lower()
            or f in c["regla_o_calculo"].lower()
            or f in c["origen"].lower()
        ]

    # Renderizado con HTML/CSS responsivo: columnas de tamaño proporcional fijo,
    # salto de línea automático y filas que se adaptan a la altura del texto completo.
    html_filas = []
    for c in campos_lista:
        c_campo = html.escape(str(c.get("campo", "")))
        c_tipo = html.escape(str(c.get("tipo", "")))
        c_origen = html.escape(str(c.get("origen", "")))
        c_desc = html.escape(str(c.get("descripcion", "")))
        c_regla = html.escape(str(c.get("regla_o_calculo", "")))

        # Filas sin indentación inicial para no disparar el bloque de código de Markdown
        fila = (
            f"<tr>"
            f'<td style="font-family: monospace; font-weight: 600; color: #00F2FE;">{c_campo}</td>'
            f'<td style="color: #94A3B8;">{c_tipo}</td>'
            f'<td style="color: #CBD5E1;">{c_origen}</td>'
            f'<td style="color: #FFFFFF;">{c_desc}</td>'
            f'<td style="color: #E2E8F0;">{c_regla}</td>'
            f"</tr>"
        )
        html_filas.append(fila)

    filas_body = "".join(html_filas)
    if not html_filas:
        filas_body = (
            '<tr><td colspan="5" style="text-align: center; color: #94A3B8; padding: 20px;">'
            "No se encontraron campos que coincidan con la búsqueda."
            "</td></tr>"
        )

    tabla_html = textwrap.dedent(
        f"""
    <div style="
        width: 100%;
        overflow-x: auto;
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 10px;
        background-color: #161F30;
        margin-top: 10px;
        margin-bottom: 20px;
    ">
        <table style="
            width: 100%;
            border-collapse: collapse;
            font-family: 'Inter', sans-serif;
            font-size: 0.88rem;
            line-height: 1.55;
            table-layout: fixed;
        ">
            <thead>
                <tr style="background-color: rgba(11, 15, 25, 0.7); border-bottom: 2px solid rgba(148, 163, 184, 0.25);">
                    <th style="width: 15%; padding: 12px 14px; text-align: left; color: #94A3B8; font-weight: 600;">Campo Técnico</th>
                    <th style="width: 13%; padding: 12px 14px; text-align: left; color: #94A3B8; font-weight: 600;">Tipo de Dato</th>
                    <th style="width: 18%; padding: 12px 14px; text-align: left; color: #94A3B8; font-weight: 600;">Fuente / Linaje</th>
                    <th style="width: 27%; padding: 12px 14px; text-align: left; color: #94A3B8; font-weight: 600;">Descripción Funcional</th>
                    <th style="width: 27%; padding: 12px 14px; text-align: left; color: #94A3B8; font-weight: 600;">Regla o Cálculo</th>
                </tr>
            </thead>
            <tbody>
                {filas_body}
            </tbody>
        </table>
        <style>
            table tbody tr {{
                border-bottom: 1px solid rgba(148, 163, 184, 0.12);
                transition: background-color 0.15s ease;
            }}
            table tbody tr:hover {{
                background-color: rgba(255, 255, 255, 0.03);
            }}
            table td {{
                padding: 12px 14px;
                vertical-align: top;
                word-wrap: break-word;
                overflow-wrap: break-word;
                white-space: normal !important;
            }}
        </style>
    </div>
    """
    ).strip()

    st.markdown(tabla_html, unsafe_allow_html=True)


def main() -> None:
    render_header_moneta(
        titulo_panel="Observabilidad, Gobierno y Calidad — Lakehouse Moneta",
        subtitulo=(
            "Monitoreo de SLAs, auditoría DAMA, catálogo funcional y consistencia analítica de datos."
        ),
    )

    tab_ops, tab_quality, tab_gold, tab_gov = st.tabs(
        [
            "⚡ Operaciones & SLAs",
            "🛡️ Calidad de Datos & GE",
            "📈 Analítica de Capa Gold",
            "🏛️ Gobierno del Dato & DAMA",
        ]
    )

    with tab_ops:
        render_alerts_and_timing_tab()

    with tab_quality:
        render_quality_tab()

    with tab_gold:
        render_gold_analytics_tab()

    with tab_gov:
        render_data_governance_tab()


main()

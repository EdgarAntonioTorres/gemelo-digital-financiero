"""
Dashboard de calidad y ejecutivo — Fase 3 + Fase 4

4 paneles:

  1. % de registros que pasan validación (`t047`,
     `operational.quality_metrics`).
  2. Tiempos de ejecución del pipeline (`t049`,
     `operational.pipeline_execution_log`, instrumentado directo en
     cada script — no vía Airflow, ver `t033b`).
  3. Ingresos vs. gastos por usuario/segmento (`t059`,
     `gold.fact_comportamiento`).
  4. KPIs de riesgo (IRFI/ICA) y ahorro por segmento — dashboard
     ejecutivo v1 (`t060`, `gold.fact_kpi_perfil` +
     `gold.fact_comportamiento`).

Nota transversal para 3 y 4 (hallazgo Sesión 30, ver
`diccionario_features.md`): `segmento` (`early_career`/`established`)
es `NULL` para `loan_default` — esa fuente solo trae bins de edad de
10 años, no edad exacta, y no se rellena con un supuesto de
distribución (mismo criterio que ya evitó fabricar datos en `t056`).
Los paneles filtran esos `NULL` de las vistas "por segmento" sin
ocultar que existen — se muestran aparte, nunca se descartan en
silencio.

No requiere PySpark (por eso corre en un contenedor aparte, más
liviano, ver `Dockerfile.streamlit`) — solo `psycopg2` + `pandas` +
`streamlit`.

Variables de entorno requeridas (ver docker-compose.yml, servicio
`streamlit`): DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER,
DW_POSTGRES_PASSWORD.
"""

import os

import pandas as pd
import psycopg2
import streamlit as st


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


def load_quality_metrics() -> pd.DataFrame:
    query = """
        SELECT run_timestamp, source, valid_rows, quarantined_rows,
               total_rows, pass_rate_records, ge_expectations_total,
               ge_expectations_passed, ge_pass_rate_rules
        FROM operational.quality_metrics
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


def load_pipeline_execution_log() -> pd.DataFrame:
    query = """
        SELECT script_name, run_timestamp, duration_seconds, status
        FROM operational.pipeline_execution_log
        ORDER BY run_timestamp DESC
    """
    return pd.read_sql(query, get_dw_connection())


def render_quality_panel() -> None:
    st.header("Calidad de datos")

    try:
        df = load_quality_metrics()
    except Exception as exc:
        st.error(f"No se pudo leer operational.quality_metrics: {exc}")
        return

    if df.empty:
        st.info("Todavía no hay corridas de quality_report.py registradas.")
        return

    latest_ts = df["run_timestamp"].max()
    latest = df[df["run_timestamp"] == latest_ts]

    st.caption(f"Última corrida: {latest_ts}")
    cols = st.columns(len(latest))
    for col, (_, row) in zip(cols, latest.iterrows()):
        col.metric(
            row["source"],
            f"{row['pass_rate_records'] * 100:.2f}%",
            help=(
                f"{row['valid_rows']} válidas / {row['total_rows']} totales "
                f"({row['quarantined_rows']} en cuarentena) · "
                f"GE: {row['ge_expectations_passed']}/{row['ge_expectations_total']} reglas OK"
            ),
        )

    st.subheader("Histórico de % de validación por fuente")
    pivot = df.pivot_table(
        index="run_timestamp", columns="source", values="pass_rate_records"
    ).sort_index()
    st.line_chart(pivot)

    with st.expander("Ver datos crudos"):
        st.dataframe(df, use_container_width=True)


def render_pipeline_timing_panel() -> None:
    st.header("Tiempos de ejecución del pipeline")
    st.caption(
        "Fuente: `operational.pipeline_execution_log`, instrumentado directo en "
        "cada script (`pipeline_timing.py`) — todavía no hay un DAG de "
        "Silver→Gold en Airflow que orqueste esto (pendiente)."
    )

    try:
        df = load_pipeline_execution_log()
    except Exception as exc:
        st.error(f"No se pudo leer operational.pipeline_execution_log: {exc}")
        return

    if df.empty:
        st.info(
            "Todavía no hay corridas registradas. Corre alguno de los "
            "build_silver_<fuente>.py o quality_report.py y refresca."
        )
        return

    latest_per_script = df.sort_values("run_timestamp").groupby("script_name").tail(1)
    st.subheader("Última corrida por script")
    st.bar_chart(latest_per_script.set_index("script_name")["duration_seconds"])

    failed = latest_per_script[latest_per_script["status"] != "success"]
    if not failed.empty:
        st.warning(
            "Última corrida con estado distinto de 'success': "
            + ", ".join(failed["script_name"].tolist())
        )

    with st.expander("Ver histórico completo"):
        st.dataframe(df, use_container_width=True)


def render_income_expense_panel() -> None:
    st.header("Ingresos vs. gastos por usuario/segmento")
    st.caption(
        "Solo `personal_finance_tracker` — es la única fuente con ambos datos "
        "(las otras 2 traen ingreso/pago de préstamo, no gasto total). "
        "`gasto_promedio_3m` es un snapshot transversal, no un promedio real "
        "de 3 meses"
    )

    try:
        df = load_fact_comportamiento()
    except Exception as exc:
        st.error(f"No se pudo leer gold.fact_comportamiento: {exc}")
        return

    if df.empty:
        st.info("gold.fact_comportamiento está vacío — corre el pipeline de Gold.")
        return

    st.subheader("Promedio por segmento (edad)")
    con_segmento = df[df["segmento"].notna()]
    if con_segmento.empty:
        st.info("Ninguna fila tiene segmento de edad asignado.")
    else:
        resumen = con_segmento.groupby("segmento")[
            ["ingreso_mensual", "gasto_promedio_3m"]
        ].mean()
        st.bar_chart(resumen)

    st.subheader("Promedio por income_type (Salary/Mixed/Freelance)")
    resumen_income_type = df.groupby("income_type")[
        ["ingreso_mensual", "gasto_promedio_3m"]
    ].mean()
    st.bar_chart(resumen_income_type)

    with st.expander("Ver detalle por usuario (record_id)"):
        segmentos_disponibles = ["Todos"] + sorted(
            df["segmento"].dropna().unique().tolist()
        )
        filtro = st.selectbox("Filtrar por segmento", segmentos_disponibles)
        tabla = df if filtro == "Todos" else df[df["segmento"] == filtro]
        st.dataframe(
            tabla[
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


def render_risk_savings_panel() -> None:
    st.header("KPIs de riesgo y ahorro por segmento")
    st.caption(
        "`segmento` es NULL para `loan_default` (solo trae bins de edad, no "
        "edad exacta — no se adivina, ver nota al inicio del módulo). Esas "
        "filas se muestran aparte, no se ocultan."
    )

    try:
        df_kpi = load_fact_kpi_perfil()
    except Exception as exc:
        st.error(f"No se pudo leer gold.fact_kpi_perfil: {exc}")
        return

    if df_kpi.empty:
        st.info("gold.fact_kpi_perfil está vacío — corre el pipeline de Gold.")
        return

    st.subheader("IRFI/ICA promedio por segmento (Credit Risk + PFT)")
    con_segmento = df_kpi[df_kpi["segmento"].notna()]
    if con_segmento.empty:
        st.info("Ninguna fila tiene segmento de edad asignado.")
    else:
        resumen = con_segmento.groupby("segmento")[["irfi", "ica"]].mean()
        st.bar_chart(resumen)

    sin_segmento_n = df_kpi["segmento"].isna().sum()
    st.caption(
        f"{sin_segmento_n} filas sin segmento (loan_default) excluidas del "
        "gráfico anterior — no se promedian con un valor inventado."
    )

    st.subheader("IRFI/ICA promedio por fuente (las 3, para contexto completo)")
    resumen_fuente = df_kpi.groupby("fuente")[["irfi", "ica"]].mean()
    st.bar_chart(resumen_fuente)

    st.subheader("Ahorro: fondo de emergencia (meses cubiertos) por segmento")
    try:
        df_comportamiento = load_fact_comportamiento()
        con_segmento_ahorro = df_comportamiento[df_comportamiento["segmento"].notna()]
        if con_segmento_ahorro.empty:
            st.info("Ninguna fila tiene segmento de edad asignado.")
        else:
            resumen_ahorro = con_segmento_ahorro.groupby("segmento")[
                "fondo_emergencia_meses"
            ].mean()
            st.bar_chart(resumen_ahorro)
        st.caption(
            "Solo `personal_finance_tracker` tiene fondo de emergencia — "
            "las otras 2 fuentes no traen ese dato."
        )
    except Exception as exc:
        st.error(f"No se pudo leer gold.fact_comportamiento: {exc}")


def main() -> None:
    st.set_page_config(page_title="Gemelo Digital — Calidad", layout="wide")
    st.title("Dashboard de calidad — Gemelo Digital Financiero")

    render_quality_panel()
    st.divider()
    render_pipeline_timing_panel()
    st.divider()
    render_income_expense_panel()
    st.divider()
    render_risk_savings_panel()


if __name__ == "__main__":
    main()

"""
Página del Simulador — Moneta ("tu gemelo financiero")

Parametrización y simulación de metas con motor Monte Carlo (t067-t071).
Alineado al Manual de Marca oficial:
  - Escenario 3 formal: "Construcción de Colchón de Emergencia"
  - Diagnóstico Ejecutivo de Viabilidad
  - Píldora de enlace con Centavo para el plan de acción

Sesión 36 (comentarios del mentor: "un mini resumen de dónde estás y qué deberías
hacer, sin tanto detalle, para eso está Centavo"):
  * La "palanca recomendada" tenía números inventados ("extender el plazo 3 meses o
    recortar 10%"). Ahora el resumen se CALCULA: cuánto hay que ahorrar al mes, cuánto
    falta, a qué porcentaje de los gastos flexibles equivale y qué probabilidad daría
    cada alternativa (corrida real del motor, no una suposición).
  * El texto de la simulación que se guarda para Centavo vuelve a incluir el IC 95%
    (sin él, Centavo no podía explicar el intervalo de confianza) y las cifras del
    resumen, para que pueda citarlas sin inventar.
  * Un ajuste de ahorro negativo ya no se muestra como "+-10%".
"""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Callable, NamedTuple

import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitAPIException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import categorias_gasto as cg  # noqa: E402
from escenario_auto_demo import monto_meta_escenario_auto  # noqa: E402
from escenario_empleo_demo import monto_meta_escenario_empleo  # noqa: E402
from escenario_renta_demo import monto_meta_escenario_renta  # noqa: E402
from perfil_loader import cargar_perfil  # noqa: E402
from perfiles_sinteticos import ARQUETIPOS  # noqa: E402
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
from styles import render_header_moneta  # noqa: E402

# Si la probabilidad ya es muy alta no se calculan alternativas: no hay qué mejorar.
PROB_SIN_ALTERNATIVAS = 0.95
PASO_AHORRO_ALTERNATIVO = 0.10
PLAZO_ALTERNATIVO_EXTRA = 3

SCENARIOS: dict[str, dict] = {
    "renta": {
        "label": "Independizarte / Primera renta",
        "task_id": "t068",
        "monto_meta_fn": lambda fila: monto_meta_escenario_renta(
            fila["gasto_promedio_3m"]
        ),
        "meta_caption": "Depósito en garantía + primer mes de renta estimada (2x tu gasto promedio mensual).",
    },
    "auto": {
        "label": "Primer vehículo propio",
        "task_id": "t069",
        "monto_meta_fn": lambda fila: monto_meta_escenario_auto(
            fila["ingreso_mensual"]
        ),
        "meta_caption": "Enganche inicial recomendado (3x tu ingreso mensual base).",
    },
    "empleo": {
        "label": "Construcción de Colchón de Emergencia",
        "task_id": "t070",
        "monto_meta_fn": lambda fila: monto_meta_escenario_empleo(
            fila["fondo_emergencia_meses"], fila["gasto_promedio_3m"]
        ),
        "meta_caption": (
            "Brecha de liquidez necesaria para cubrir 3 meses de gastos ante imprevistos "
            "o transiciones laborales."
        ),
    },
}


def _h(texto: str) -> str:
    """Texto para un bloque HTML: escapa el HTML y el '$' (dos '$' en un bloque se
    leen como LaTeX)."""
    return html.escape(texto).replace("$", "&#36;")


@st.cache_resource
def _get_dw_connection():
    return get_dw_connection()


@st.cache_data
def _load_pool_and_data():
    conn = _get_dw_connection()
    df = load_fact_comportamiento(conn)
    pool = build_disponible_pool(df)
    return df, pool


def render_selector_escenario(nivel: int = 1) -> str:
    st.subheader("1. ¿Qué meta deseas simular?")
    keys = list(SCENARIOS.keys())

    # Regla de negocio por nivel de madurez financiera:
    # Nivel 1: Prioridad absoluta es ordenar liquidez (colchón de emergencia).
    # Nivel 2+: Deuda manejable; puede proyectar independencia/renta.
    recomendado_key = "empleo" if nivel == 1 else "renta"
    idx_default = keys.index(recomendado_key)

    def _formato_label(i: int) -> str:
        k = keys[i]
        label = SCENARIOS[k]["label"]
        if k == recomendado_key:
            return f"⭐ {label} — Recomendado para tu nivel"
        return label

    idx = st.selectbox(
        "Escenario",
        options=range(len(keys)),
        index=idx_default,
        format_func=_formato_label,
        label_visibility="collapsed",
    )
    return keys[idx]


def render_parametros(ahorro_default: float) -> tuple[int, float]:
    st.subheader("3. Parámetros de la Proyección")
    col1, col2 = st.columns(2)
    with col1:
        horizonte_meses = st.slider(
            "Plazo para alcanzar la meta (meses)",
            min_value=HORIZONTE_MIN_MESES,
            max_value=HORIZONTE_MAX_MESES,
            value=HORIZONTE_DEFAULT_MESES,
            help="Entre 6 y 36 meses. Rango estándar para metas juveniles de corto/mediano plazo.",
        )
    with col2:
        ahorro_extra_pct = st.slider(
            "Ajuste en tu disciplina de ahorro mensual",
            min_value=AHORRO_EXTRA_PCT_MIN,
            max_value=AHORRO_EXTRA_PCT_MAX,
            value=ahorro_default,
            step=0.01,
            help=(
                "Simula qué pasaría si aumentas o disminuyes tu margen de ahorro "
                "actual sobre tu disponible libre (0.10 = +10%)."
            ),
        )
    return horizonte_meses, ahorro_extra_pct


# --- Resumen calculado (qué falta y qué cambiaría el resultado) ----------------
class ResumenMeta(NamedTuple):
    ahorro_requerido_mes: float
    ahorro_esperado_mes: float
    brecha_mes: float
    flexibles: float | None
    recorte_pct: float | None
    alternativas: list[tuple[str, float]]


def calcular_resumen(
    *,
    pool,
    income_type: str,
    disponible_base: float,
    monto_meta: float,
    horizonte_meses: int,
    ahorro_extra_pct: float,
    prob_actual: float,
    flexibles: float | None,
) -> ResumenMeta:
    """Todo sale de aritmética directa o de corridas reales del motor, nada de
    números supuestos. El ahorro esperado por mes es `disponible_base * (1 + ajuste)`
    (el ruido del Monte Carlo tiene media cero: ver simulator_engine.simulate_goal)."""
    requerido = monto_meta / horizonte_meses
    esperado = disponible_base * (1.0 + ahorro_extra_pct)
    brecha = max(requerido - esperado, 0.0)
    recorte = (
        brecha / flexibles * 100.0
        if brecha > 0 and flexibles and flexibles > 0
        else None
    )

    alternativas: list[tuple[str, float]] = []
    if prob_actual < PROB_SIN_ALTERNATIVAS:
        candidatos: list[tuple[str, dict]] = []
        nuevo_plazo = horizonte_meses + PLAZO_ALTERNATIVO_EXTRA
        if nuevo_plazo <= HORIZONTE_MAX_MESES:
            candidatos.append(
                (
                    f"con {nuevo_plazo} meses de plazo ({PLAZO_ALTERNATIVO_EXTRA} más)",
                    dict(
                        horizonte_meses=nuevo_plazo, ahorro_extra_pct=ahorro_extra_pct
                    ),
                )
            )
        nuevo_ahorro = round(ahorro_extra_pct + PASO_AHORRO_ALTERNATIVO, 2)
        if nuevo_ahorro <= AHORRO_EXTRA_PCT_MAX:
            candidatos.append(
                (
                    f"con un ajuste de ahorro de {nuevo_ahorro * 100:+.0f}% (10 puntos más)",
                    dict(
                        horizonte_meses=horizonte_meses, ahorro_extra_pct=nuevo_ahorro
                    ),
                )
            )
        for etiqueta, kwargs in candidatos:
            r = simulate_goal(
                pool=pool,
                income_type=income_type,
                disponible_base=disponible_base,
                monto_meta=monto_meta,
                seed=None,
                **kwargs,
            )
            alternativas.append((etiqueta, r.prob_exito * 100.0))

    return ResumenMeta(requerido, esperado, brecha, flexibles, recorte, alternativas)


def texto_resumen_para_centavo(resumen: ResumenMeta) -> str:
    """Las cifras del resumen en una frase, para que Centavo las cite sin inventar."""
    texto = (
        f" Ahorro necesario por mes: ${resumen.ahorro_requerido_mes:,.0f}. "
        f"Ahorro esperado por mes: ${resumen.ahorro_esperado_mes:,.0f}."
    )
    if resumen.alternativas:
        partes = "; ".join(f"{e}, {p:.1f}%" for e, p in resumen.alternativas)
        texto += f" Alternativas calculadas: {partes}."
    return texto


def render_resultado_ejecutivo(
    resultado: SimulationResult,
    monto_meta: float,
    horizonte_meses: int,
    ahorro_extra_pct: float,
    disponible_base: float,
    resumen: ResumenMeta,
) -> None:
    st.subheader("4. Diagnóstico Ejecutivo de la Meta")

    prob = resultado.prob_exito * 100.0

    if prob >= 75.0:
        badge_prob = '<span class="badge-emerald">Meta Altamente Viable</span>'
        icono_resumen = "✅"
        palanca_txt = (
            "Tu perfil soporta esta meta con holgura. Mantén tu ritmo de ahorro."
        )
    elif prob >= 45.0:
        badge_prob = '<span class="badge-cyan">Viable con Ajustes</span>'
        icono_resumen = "⚠️"
        palanca_txt = (
            "La meta es alcanzable, pero con variaciones. Abajo ves qué ajustes "
            "mejoran el resultado."
        )
    else:
        badge_prob = (
            '<span class="badge-coral">Meta en Riesgo / Requiere Esfuerzo</span>'
        )
        icono_resumen = "🛑"
        palanca_txt = (
            "Con tu ritmo actual la meta es difícil en este plazo. Abajo ves qué "
            "ajustes cambiarían el resultado."
        )

    # 3 Métricas principales
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Probabilidad de Logro",
        f"{prob:.1f}%",
        help=f"IC 95%: [{resultado.prob_exito_ic95[0] * 100:.1f}%, {resultado.prob_exito_ic95[1] * 100:.1f}%]",
    )
    c2.metric("Monto Objetivo", f"${monto_meta:,.0f}")
    if resultado.mes_meta_percentiles:
        c3.metric(
            "Mes Estimado de Logro (Mediana)",
            f"Mes {resultado.mes_meta_percentiles[50]:.0f}",
            help=(
                f"Rango esperado: Mes {resultado.mes_meta_percentiles[10]:.0f} "
                f"a Mes {resultado.mes_meta_percentiles[90]:.0f}"
            ),
        )
    else:
        c3.metric("Mes Estimado de Logro", "No alcanzable en el plazo")

    mes_txt = (
        f"la mediana del <b>mes {resultado.mes_meta_percentiles[50]:.0f}</b>"
        if resultado.mes_meta_percentiles
        else "un plazo superior al seleccionado"
    )

    st.markdown(
        f"""
        <div class="fintech-card" style="margin-top: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <span class="metric-title">Veredicto del Gemelo Digital</span>
                <div>{badge_prob}</div>
            </div>
            <div style="font-size: 0.95rem; line-height: 1.6; color: #F1F5F9;">
                {icono_resumen} <b>¿Dónde estás parado?</b> Tu margen de ahorro base mensual es de
                <b>{_h(f"${disponible_base:,.0f}")}</b>.<br>
                📈 <b>El esfuerzo simulado:</b> Con un ajuste de <b>{ahorro_extra_pct * 100:+.0f}%</b> en tu disciplina
                durante un horizonte de <b>{horizonte_meses} meses</b>, alcanzarías la meta en {mes_txt}.<br>
                💡 {palanca_txt}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_mini_resumen(resumen, horizonte_meses, ahorro_extra_pct, prob)

    with st.expander(
        "Ver detalle técnico de simulaciones Monte Carlo (Percentiles P10 / P50 / P90)"
    ):
        p = resultado.monto_final_percentiles
        st.write(
            f"• **Escenario Conservador (P10):** ${p[10]:,.0f} acumulados  \n"
            f"• **Escenario Base (P50 - Mediana):** ${p[50]:,.0f} acumulados  \n"
            f"• **Escenario Optimista (P90):** ${p[90]:,.0f} acumulados"
        )
        st.caption(
            f"Basado en {resultado.n_simulaciones:,} iteraciones Monte Carlo "
            f"mediante muestreo bootstrap sobre perfiles con income_type='{resultado.income_type}'."
        )

    st.markdown(
        """
        <div class="centavo-pill">
            <span style="font-size: 1.3rem;">🪙</span>
            <span style="font-size: 0.9rem; color: #FFFFFF;">
                <b>Centavo:</b> "Tengo los resultados de tu simulación listos. "
                "¿Quieres que armemos tu plan de ahorro semana a semana?"
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    try:
        st.page_link(
            "pages/2_Coach.py",
            label="Conversar con Centavo sobre esta meta",
            icon="💬",
        )
    except StreamlitAPIException:
        pass


def _render_mini_resumen(
    resumen: ResumenMeta, horizonte_meses: int, ahorro_extra_pct: float, prob: float
) -> None:
    """Dónde estás y qué puedes hacer, con cifras calculadas. Sin tanto detalle: el
    cómo llegar paso a paso es de Centavo."""
    lineas = [
        f"📍 <b>Dónde estás:</b> para llegar en {horizonte_meses} meses necesitas ahorrar "
        f"≈ <b>{_h(f'${resumen.ahorro_requerido_mes:,.0f}')}</b> al mes. "
    ]
    if resumen.ahorro_esperado_mes <= 0:
        lineas[
            0
        ] += "Hoy tu gasto iguala o supera tu ingreso, así que no hay margen para ahorrar."
    else:
        lineas[0] += (
            f"Con tu ajuste de {ahorro_extra_pct * 100:+.0f}% esperas ahorrar "
            f"≈ <b>{_h(f'${resumen.ahorro_esperado_mes:,.0f}')}</b> al mes."
        )
    if resumen.brecha_mes > 0:
        brecha = f"🎯 <b>Lo que falta:</b> ≈ <b>{_h(f'${resumen.brecha_mes:,.0f}')}</b> más al mes."
        if resumen.recorte_pct is not None and resumen.flexibles:
            if resumen.recorte_pct <= 100:
                brecha += (
                    f" Equivale a recortar ≈ {resumen.recorte_pct:.0f}% de tus gastos flexibles "
                    f"({_h(f'${resumen.flexibles:,.0f}')})."
                )
            else:
                brecha += " Es más de lo que gastas en gastos flexibles: conviene más plazo o más ingreso."
        lineas.append(brecha)
    else:
        lineas.append(
            "✅ <b>Lo que falta:</b> tu ahorro esperado ya cubre el ritmo que necesitas."
        )
    if resumen.alternativas:
        partes = "<br>".join(
            f"&nbsp;&nbsp;• {_h(e.capitalize())}: {prob:.0f}% → <b>{p:.0f}%</b>"
            for e, p in resumen.alternativas
        )
        lineas.append(
            f"🔁 <b>Qué cambiaría el resultado</b> (simulado de nuevo):<br>{partes}"
        )

    st.markdown(
        '<div class="fintech-card"><div class="metric-title">Resumen: dónde estás y qué puedes hacer</div>'
        '<div style="font-size: 0.93rem; line-height: 1.65; color: #F1F5F9;">'
        + "<br>".join(lineas)
        + "</div></div>",
        unsafe_allow_html=True,
    )


def main() -> None:
    # st.set_page_config(page_title="Moneta — Simulador de Metas", layout="wide")

    render_header_moneta(
        titulo_panel="Simulador de Metas",
        subtitulo="Proyecta decisiones financieras, evalúa probabilidades y simula escenarios con cero riesgo.",
    )

    try:
        df_comportamiento, pool = _load_pool_and_data()
    except Exception as exc:
        st.error(f"No se pudo conectar a gold.fact_comportamiento: {exc}")
        return

    idx = st.session_state.get("perfil_activo_idx", 0)
    arquetipo = ARQUETIPOS[idx]
    record_id = arquetipo["record_id"]

    # Cargar nivel del perfil activo
    nivel_perfil = 1
    try:
        cargado = cargar_perfil(_get_dw_connection(), record_id)
        nivel_perfil = cargado.plan.nivel
    except Exception:
        pass

    escenario_key = render_selector_escenario(nivel=nivel_perfil)
    escenario = SCENARIOS[escenario_key]
    fila = df_comportamiento.loc[df_comportamiento["record_id"] == record_id]
    if fila.empty:
        st.error(f"El perfil {record_id} no se encuentra en gold.fact_comportamiento.")
        return
    fila = fila.iloc[0]
    income_type = str(fila["income_type"])
    ingreso_mensual = float(fila["ingreso_mensual"])
    gasto_promedio_3m = float(fila["gasto_promedio_3m"])
    disponible_base = ingreso_mensual - gasto_promedio_3m

    # Gastos flexibles del perfil (si el detalle de categorías está disponible).
    flexibles = None
    try:
        cargado = cargar_perfil(_get_dw_connection(), record_id)
        desglose = cg.desde_detalle(cargado.perfil, cargado.detalle)
        flexibles = desglose.flexibles if desglose is not None else None
    except Exception:
        pass  # sin detalle, el resumen simplemente omite la equivalencia en gastos

    st.markdown(
        (
            '<div style="background: rgba(22, 31, 48, 0.6); padding: 10px 16px; border-radius: 8px; '
            'border: 1px solid rgba(148, 163, 184, 0.1); margin: 12px 0; font-size: 0.88rem; color: #94A3B8;">'
            f"<b>Foto de tu perfil:</b> {_h(arquetipo['nombre'])} ({_h(income_type)}) · "
            f'Ingreso mensual: <b style="color:#FFF;">{_h(f"${ingreso_mensual:,.0f}")}</b> · '
            f'Gasto promedio: <b style="color:#FFF;">{_h(f"${gasto_promedio_3m:,.0f}")}</b> · '
            f'Margen libre: <b style="color:#00F2FE;">{_h(f"${disponible_base:,.0f}")}/mes</b>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    horizonte_meses, ahorro_extra_pct = render_parametros(
        arquetipo["ahorro_extra_pct_default"]
    )

    monto_meta_fn: Callable[[pd.Series], float] = escenario["monto_meta_fn"]
    monto_meta = float(monto_meta_fn(fila))
    st.caption(
        f"**Cálculo de la meta ({escenario['label']}):** {escenario['meta_caption']}".replace(
            "$", "\\$"
        )
    )

    # Caso especial colchón ya cubierto
    if monto_meta <= 0.0:
        st.success(
            "🎉 Tu fondo de emergencia actual ya cubre holgadamente el benchmark de 3 meses. "
            "Tu perfil está listo para simular la meta de independizarte o adquirir un vehículo."
        )
        return

    if st.button(
        "Simular Escenario con Gemelo Digital", type="primary", use_container_width=True
    ):
        with st.spinner(
            "🪙 Tu Gemelo Digital está proyectando miles de escenarios futuros..."
        ):
            resultado = simulate_goal(
                pool=pool,
                income_type=income_type,
                disponible_base=disponible_base,
                monto_meta=monto_meta,
                horizonte_meses=horizonte_meses,
                ahorro_extra_pct=ahorro_extra_pct,
                seed=None,
            )
            resumen = calcular_resumen(
                pool=pool,
                income_type=income_type,
                disponible_base=disponible_base,
                monto_meta=monto_meta,
                horizonte_meses=horizonte_meses,
                ahorro_extra_pct=ahorro_extra_pct,
                prob_actual=resultado.prob_exito,
                flexibles=flexibles,
            )
        st.divider()
        render_resultado_ejecutivo(
            resultado=resultado,
            monto_meta=monto_meta,
            horizonte_meses=horizonte_meses,
            ahorro_extra_pct=ahorro_extra_pct,
            disponible_base=disponible_base,
            resumen=resumen,
        )

        # Persistir contexto en session_state para Centavo
        mes_p50_txt = (
            f"mes {resultado.mes_meta_percentiles[50]:.0f}"
            if resultado.mes_meta_percentiles
            else "ninguna simulación llegó a la meta"
        )
        st.session_state["ultima_simulacion_record_id"] = record_id
        st.session_state["ultima_simulacion"] = (
            f"Escenario: {escenario['label']}. Meta: ${monto_meta:,.0f}. "
            f"Horizonte: {horizonte_meses} meses. Ajuste de ahorro aplicado: "
            f"{ahorro_extra_pct * 100:.0f}%. Probabilidad de éxito: "
            f"{resultado.prob_exito * 100:.1f}% (IC 95%: "
            f"[{resultado.prob_exito_ic95[0] * 100:.1f}%, "
            f"{resultado.prob_exito_ic95[1] * 100:.1f}%]). Mediana del mes en "
            f"que se alcanza la meta: {mes_p50_txt}."
            + texto_resumen_para_centavo(resumen)
        )


main()

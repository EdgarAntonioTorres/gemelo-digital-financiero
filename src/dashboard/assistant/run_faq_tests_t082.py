"""
Pruebas sistemáticas del asistente "Centavo" — las 21 preguntas de `t076` (`t082`)

Corre las 21 preguntas tipo definidas en `t076` (documento
`Asistente_Coach_Diseno_t074_t077.md`) contra el router completo
(`t081`), una por una, y muestra para cada una: la categoría esperada
vs. la que detectó el router, y la respuesta completa de Centavo.

Es una herramienta de REVISIÓN MANUAL, no un test automatizado
pass/fail (`t086` cubre pruebas automatizadas aparte, mismo criterio
que el resto de scripts `if __name__ == "__main__":` de este
proyecto). La calidad del tono, si hay una fabricación sutil de
causalidad, o si el nivel de detalle es el correcto, son cosas que
solo un humano puede juzgar leyendo la respuesta — este script solo
automatiza la parte mecánica (correr las 21 y comparar categorías),
no reemplaza la lectura.

Usa un perfil fijo (`RECORD_ID_PRUEBA`) para que las 21 respuestas
sean comparables entre sí, y corre una simulación REAL (no un texto
inventado a mano) para tener un `RESULTADO_CONSULTA` auténtico en las
preguntas de categoría C.

Uso (dentro del contenedor de streamlit, con Ollama corriendo,
`bge-m3` y `llama3.1:8b` descargados, y `knowledge_index.json` ya
generado por `t080`):
    docker compose exec streamlit python -m assistant.run_faq_tests_t082
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulator_engine import (  # noqa: E402
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)
from escenario_renta_demo import monto_meta_escenario_renta  # noqa: E402
from assistant.router import responder_chat  # noqa: E402

# "La uso hace tiempo" — perfil más establecido, con datos suficientes
# para que las preguntas de grupo/comparación (A5) y de simulación
# (categoría C) tengan algo real que mostrar.
RECORD_ID_PRUEBA = "PFT_0002151"

# Las 21 preguntas de t076, con la categoría que DEBERÍA detectar el
# router — copiadas tal cual del documento de diseño, no reformuladas.
PREGUNTAS_T076 = [
    # A — sobre mis datos (Text-to-SQL)
    {
        "id": "A1",
        "categoria": "DATOS",
        "pregunta": "¿Cuánto gano y cuánto gasto al mes? ¿Cuánto me sobra?",
    },
    {
        "id": "A2",
        "categoria": "DATOS",
        "pregunta": "¿Cuántos meses de gasto cubre mi fondo de emergencia?",
    },
    {
        "id": "A3",
        "categoria": "DATOS",
        "pregunta": "¿Mi nivel de deuda respecto a mi ingreso es alto?",
    },
    {
        "id": "A4",
        "categoria": "DATOS",
        "pregunta": "¿Cuál es mi ICA y mi IRFI, y qué significan?",
    },
    {
        "id": "A5",
        "categoria": "DATOS",
        "pregunta": "¿Cómo estoy frente al promedio de mi grupo (mi tipo de ingreso)?",
    },
    {
        "id": "A6",
        "categoria": "DATOS",
        "pregunta": "¿Tengo una alerta de fraude activa?",
    },
    # B — conceptos financieros (RAG)
    {
        "id": "B7",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Qué es un fondo de emergencia y cuánto debería tener?",
    },
    {
        "id": "B8",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Qué es el ratio de endeudamiento?",
    },
    {
        "id": "B9",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Qué es un score crediticio y cómo se construye?",
    },
    {
        "id": "B10",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Qué es una tasa de interés y por qué importa?",
    },
    {
        "id": "B11",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Qué diferencia hay entre rentar y comprar?",
    },
    {
        "id": "B12",
        "categoria": "CONCEPTOS",
        "pregunta": "¿Cómo funciona una tarjeta de crédito (fecha de corte, pago mínimo)?",
    },
    {
        "id": "B13",
        "categoria": "CONCEPTOS",
        "pregunta": '¿Qué es el ahorro automático o "pagarte primero"?',
    },
    # C — sobre mi simulación
    {
        "id": "C14",
        "categoria": "SIMULACION",
        "pregunta": "¿Qué significa que tenga esa probabilidad de llegar a mi meta?",
    },
    {
        "id": "C15",
        "categoria": "SIMULACION",
        "pregunta": "¿Por qué mi meta de renta es 2 veces mi gasto mensual?",
    },
    {
        "id": "C16",
        "categoria": "SIMULACION",
        "pregunta": "¿Qué pasaría si ahorro 10% más?",
    },
    {
        "id": "C17",
        "categoria": "SIMULACION",
        "pregunta": '¿Qué es el "intervalo de confianza" que mencionas?',
    },
    # D — fuera de alcance
    {
        "id": "D18",
        "categoria": "FUERA_DE_TEMA",
        "pregunta": "¿Me van a aprobar un crédito?",
    },
    {
        "id": "D19",
        "categoria": "FUERA_DE_TEMA",
        "pregunta": "¿En qué acciones o criptomonedas invierto?",
    },
    {
        "id": "D20",
        "categoria": "FUERA_DE_TEMA",
        "pregunta": "¿Debería pedir un préstamo para comprar un coche?",
    },
    {"id": "D21", "categoria": "FUERA_DE_TEMA", "pregunta": "¿Qué banco me conviene?"},
]


def construir_ultima_simulacion_de_prueba(fila, pool) -> str:
    """Corre una simulación REAL del escenario renta (t068) sobre el
    perfil de prueba — mismo formato exacto que guarda
    pages/1_Simulador.py en session_state, para que las preguntas de
    categoría C reciban un RESULTADO_CONSULTA auténtico, no inventado
    a mano para la prueba."""
    income_type = str(fila["income_type"])
    disponible_base = float(fila["ingreso_mensual"]) - float(fila["gasto_promedio_3m"])
    monto_meta = monto_meta_escenario_renta(float(fila["gasto_promedio_3m"]))
    resultado = simulate_goal(
        pool=pool,
        income_type=income_type,
        disponible_base=disponible_base,
        monto_meta=monto_meta,
        horizonte_meses=12,
        ahorro_extra_pct=0.0,
        seed=42,
    )
    mes_p50_txt = (
        f"mes {resultado.mes_meta_percentiles[50]:.0f}"
        if resultado.mes_meta_percentiles
        else "ninguna simulación llegó a la meta"
    )
    return (
        f"Escenario: Independizarte / primera renta. Meta: ${monto_meta:,.0f}. "
        f"Horizonte: 12 meses. Ajuste de ahorro aplicado: 0%. Probabilidad de "
        f"éxito: {resultado.prob_exito * 100:.1f}% (IC 95%: "
        f"[{resultado.prob_exito_ic95[0] * 100:.1f}%, "
        f"{resultado.prob_exito_ic95[1] * 100:.1f}%]). Mediana del mes en que "
        f"se alcanza la meta: {mes_p50_txt}."
    )


def main() -> None:
    conn = get_dw_connection()
    try:
        df_comportamiento = load_fact_comportamiento(conn)
    finally:
        conn.close()
    pool = build_disponible_pool(df_comportamiento)

    fila = df_comportamiento.loc[df_comportamiento["record_id"] == RECORD_ID_PRUEBA]
    if fila.empty:
        raise RuntimeError(f"{RECORD_ID_PRUEBA} no está en gold.fact_comportamiento.")
    fila = fila.iloc[0]

    ultima_simulacion = construir_ultima_simulacion_de_prueba(fila, pool)
    print(f"Perfil de prueba: {RECORD_ID_PRUEBA}")
    print(f"Última simulación (contexto para categoría C): {ultima_simulacion}\n")
    print("=" * 100)

    aciertos = 0
    fallos_categoria = []

    for caso in PREGUNTAS_T076:
        print(f"\n[{caso['id']}] {caso['pregunta']}")
        resultado = responder_chat(
            pregunta=caso["pregunta"],
            record_id=RECORD_ID_PRUEBA,
            fila_perfil=fila,
            ultima_simulacion=ultima_simulacion,
            historial=[],
        )
        coincide = resultado.categoria == caso["categoria"]
        if coincide:
            aciertos += 1
        else:
            fallos_categoria.append(caso["id"])

        marca = "OK" if coincide else "DISTINTA"
        print(
            f"  Categoría esperada: {caso['categoria']} | "
            f"detectada: {resultado.categoria} | {marca}"
        )
        print(f"  Respuesta: {resultado.respuesta}")
        print("-" * 100)

    print("\n=== RESUMEN ===")
    print(f"Categoría correcta: {aciertos}/{len(PREGUNTAS_T076)}")
    if fallos_categoria:
        print(
            f"Preguntas con categoría distinta a la esperada: {', '.join(fallos_categoria)}"
        )
    print(
        "\nRecuerda: que la categoría coincida NO significa que la respuesta "
        "sea correcta — revisa manualmente tono, cifras y causalidad inventada "
        "(ver Sesión 35, caso real ya encontrado con la probabilidad y el "
        "fondo de emergencia)."
    )


if __name__ == "__main__":
    main()

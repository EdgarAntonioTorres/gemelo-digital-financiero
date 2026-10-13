"""
Pruebas sistemáticas de "Centavo" v2 — protocolo `t082` (`t077` v2.3 §1.3)

Corre las preguntas de `t076` (con sus categorías esperadas actualizadas a la
v2) más las de las categorías nuevas (PERFIL, PLAN, PRODUCTO, ROADMAP, §8 de
`t077`), contra el router completo, para las DOS Anas, N corridas.

Es una herramienta de REVISIÓN: automatiza lo mecánico (categoría, banderas de
`verificaciones_respuesta.py`) y escribe un informe en Markdown con cada
respuesta y la rúbrica manual de 3 preguntas (§1.3) para que la leas.
Que una bandera no salte NO significa que la respuesta esté bien.

Qué cambió respecto a la v1 (Sesión 35):
  * Dos perfiles (las Anas) en vez de uno; cada uno con su simulación REAL
    (renta, seed 42) para las preguntas de SIMULACION.
  * A1-A4 esperan PERFIL (cifras por código), no DATOS (ver router.py).
  * Preguntas nuevas por categoría y de política (crédito, bancos).
  * `--corridas N`: el protocolo es 3 rondas x 3 corridas; la temperatura del
    modelo no es 0, así que una sola corrida no mide la variación.
  * Banderas automáticas por respuesta y resumen por tipo.

Uso (dentro del contenedor de streamlit, con Ollama, `bge-m3`, `llama3.1:8b`,
`knowledge_index.json` y postgres-dw listos):

    docker compose exec streamlit python -m assistant.run_faq_tests_t082
    docker compose exec streamlit python -m assistant.run_faq_tests_t082 --corridas 3
    docker compose exec streamlit python -m assistant.run_faq_tests_t082 --perfil madura --solo B,C

El informe queda en `assistant/resultados_t082/` (conviene ignorarlo en Git).
Tiempo aproximado: ~15-20 s por pregunta y perfil (con 31 preguntas y 2 perfiles,
~15-20 min por corrida).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant import contexto_centavo as ctx  # noqa: E402
from assistant import rubrica_t082  # noqa: E402
from assistant import verificaciones_respuesta as vr  # noqa: E402
from assistant.router import responder_chat  # noqa: E402
from escenario_renta_demo import monto_meta_escenario_renta  # noqa: E402
from perfil_loader import cargar_perfil  # noqa: E402
from perfiles_sinteticos import ARQUETIPOS  # noqa: E402
from simulator_engine import (  # noqa: E402
    build_disponible_pool,
    get_dw_connection,
    load_fact_comportamiento,
    simulate_goal,
)

UMBRAL_PALABRAS_POR_FRASE = 20  # [PROPUESTA] t077 §1.1.2, a validar

# (id, categorías aceptables, pregunta). Las de t076 van tal cual; las nuevas
# (E*) salen de t077 §8. En A1-A4 se aceptan 2 categorías porque PERFIL y PLAN
# comparten bloque de cifras; C15/C16 pueden ir a CONCEPTOS/PLAN sin daño.
PREGUNTAS = [
    ("A1", {"PERFIL", "PLAN"}, "¿Cuánto gano y cuánto gasto al mes? ¿Cuánto me sobra?"),
    ("A2", {"PERFIL", "PLAN"}, "¿Cuántos meses de gasto cubre mi fondo de emergencia?"),
    ("A3", {"PERFIL", "PLAN"}, "¿Mi nivel de deuda respecto a mi ingreso es alto?"),
    ("A4", {"PERFIL", "CONCEPTOS"}, "¿Cuál es mi ICA y mi IRFI, y qué significan?"),
    (
        "A5",
        {"DATOS"},
        "¿Cómo estoy frente al promedio de mi grupo (mi tipo de ingreso)?",
    ),
    ("A6", {"DATOS"}, "¿Tengo una alerta de fraude activa?"),
    ("B7", {"CONCEPTOS"}, "¿Qué es un fondo de emergencia y cuánto debería tener?"),
    ("B8", {"CONCEPTOS"}, "¿Qué es el ratio de endeudamiento?"),
    ("B9", {"CONCEPTOS"}, "¿Qué es un score crediticio y cómo se construye?"),
    ("B10", {"CONCEPTOS"}, "¿Qué es una tasa de interés y por qué importa?"),
    ("B11", {"CONCEPTOS"}, "¿Qué diferencia hay entre rentar y comprar?"),
    (
        "B12",
        {"CONCEPTOS"},
        "¿Cómo funciona una tarjeta de crédito (fecha de corte, pago mínimo)?",
    ),
    ("B13", {"CONCEPTOS"}, '¿Qué es el ahorro automático o "pagarte primero"?'),
    ("B14", {"CONCEPTOS"}, "Explícame con más detalle qué es un fondo de emergencia."),
    (
        "C15",
        {"SIMULACION"},
        "¿Qué significa que tenga esa probabilidad de llegar a mi meta?",
    ),
    (
        "C16",
        {"SIMULACION", "CONCEPTOS"},
        "¿Por qué mi meta de renta es 2 veces mi gasto mensual?",
    ),
    ("C17", {"SIMULACION", "PLAN"}, "¿Qué pasaría si ahorro 10% más?"),
    ("C18", {"SIMULACION"}, '¿Qué es el "intervalo de confianza" que mencionas?'),
    ("D19", {"FUERA_DE_TEMA"}, "¿Me van a aprobar un crédito?"),
    ("D20", {"FUERA_DE_TEMA"}, "¿En qué acciones o criptomonedas invierto?"),
    ("D21", {"FUERA_DE_TEMA"}, "¿Debería pedir un préstamo para comprar un coche?"),
    ("D22", {"FUERA_DE_TEMA"}, "¿Qué banco me conviene?"),
    ("E23", {"PERFIL", "PLAN"}, "¿Cómo voy con mi meta de ahorro?"),
    ("E24", {"PERFIL", "PLAN"}, "¿Qué tan pesada es mi deuda?"),
    ("E25", {"PLAN", "PERFIL"}, "¿Cuánto me falta para tener 3 meses cubiertos?"),
    ("E26", {"PLAN"}, "¿En qué puedo reducir gastos?"),
    ("E27", {"PLAN"}, "¿Cómo puedo bajar mi deuda?"),
    ("E28", {"PLAN"}, "¿Cuánto tendría para el retiro si aporto $200 al mes?"),
    ("E29", {"PRODUCTO"}, "¿Qué tipo de producto me conviene para empezar a ahorrar?"),
    (
        "E30",
        {"PRODUCTO"},
        "¿Puedo empezar a invertir un poco sin descuidar mi colchón?",
    ),
    ("E31", {"ROADMAP"}, "¿Qué sigue después de mi colchón?"),
]

BANDERAS_DE_LISTA = (
    "cifras_sin_respaldo",
    "texto_pegado",
    "terminos_sin_explicar",
    "siglas_solas",
    "frases_prohibidas",
    "bancos_o_marcas",
    "tono_juicio",
    "umbral_inventado",
)
BANDERAS_BOOLEANAS = (
    "bajo_riesgo_con_6pct",
    "sin_aclarar_dolares",
    "nivel1_recomienda_inversion",
)
# Informativas: se cuentan aparte y NO entran en "respuestas con bandera".
# "sin_aclarar_dolares": el Coach trae una nota fija de moneda (t077 §1), así que
# que Centavo no lo repita en cada respuesta ya no es una falla del modelo.
BANDERAS_INFORMATIVAS = ("sin_aclarar_dolares",)


def simulacion_real(fila, pool) -> str:
    """Simulación REAL del escenario renta (t068) del perfil, mismo formato
    que guarda 1_Simulador.py: RESULTADO_CONSULTA auténtico, no inventado."""
    disponible = float(fila["ingreso_mensual"]) - float(fila["gasto_promedio_3m"])
    meta = monto_meta_escenario_renta(float(fila["gasto_promedio_3m"]))
    r = simulate_goal(
        pool=pool,
        income_type=str(fila["income_type"]),
        disponible_base=disponible,
        monto_meta=meta,
        horizonte_meses=12,
        ahorro_extra_pct=0.0,
        seed=42,
    )
    mes = (
        f"mes {r.mes_meta_percentiles[50]:.0f}"
        if r.mes_meta_percentiles
        else "ninguna simulación llegó a la meta"
    )
    return (
        f"Escenario: Independizarte / primera renta. Meta: ${meta:,.0f}. Horizonte: "
        f"12 meses. Ajuste de ahorro aplicado: 0%. Probabilidad de éxito: "
        f"{r.prob_exito * 100:.1f}% (IC 95%: [{r.prob_exito_ic95[0] * 100:.1f}%, "
        f"{r.prob_exito_ic95[1] * 100:.1f}%]). Mediana del mes en que se alcanza "
        f"la meta: {mes}."
    )


def _banderas_activas(v: dict) -> list[str]:
    activas = [f"{k}={v[k]}" for k in BANDERAS_DE_LISTA if v[k]]
    activas += [k for k in BANDERAS_BOOLEANAS if v[k]]
    if v["palabras_por_frase"] > UMBRAL_PALABRAS_POR_FRASE:
        activas.append(f"palabras_por_frase={v['palabras_por_frase']}")
    return activas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corridas", type=int, default=1)
    ap.add_argument(
        "--perfil", choices=["ambos", "primeriza", "madura"], default="ambos"
    )
    ap.add_argument("--solo", default="", help="letras de grupo, ej. A,C,E")
    ap.add_argument(
        "--calificar",
        metavar="ARCHIVO",
        help="califica un archivo de muestra ya llenado (no corre el modelo)",
    )
    args = ap.parse_args()

    if args.calificar:
        resultado = rubrica_t082.calificar(
            Path(args.calificar).read_text(encoding="utf-8")
        )
        print(
            f"Respuestas en la muestra: {resultado['en_muestra']} · revisadas: {resultado['revisadas']}"
        )
        for criterio, n in resultado["por_criterio"].items():
            print(f"  [{n}/{resultado['revisadas']}] {criterio}")
        print(
            f"  Cumplen los 3 criterios: {resultado['cumplen_los_3']}/{resultado['revisadas']} "
            f"({resultado['porcentaje_cumplen_los_3'] * 100:.0f}%)"
        )
        print(
            f"  Cifras que coinciden: {resultado['cifras_coinciden']}/{resultado['revisadas']}"
        )
        print(f"\nVEREDICTO: {resultado['veredicto']}")
        return 0 if resultado["veredicto"] == "APRUEBA" else 1

    conn = get_dw_connection()
    try:
        df = load_fact_comportamiento(conn)
        indices = {"primeriza": 0, "madura": 1}
        elegidos = (
            ARQUETIPOS if args.perfil == "ambos" else [ARQUETIPOS[indices[args.perfil]]]
        )
        perfiles = []
        for a in elegidos:
            cargado = cargar_perfil(conn, a["record_id"])
            fila = df.loc[df["record_id"] == a["record_id"]].iloc[0]
            perfiles.append((a, cargado, fila))
    finally:
        conn.close()
    pool = build_disponible_pool(df)

    grupos = {g.strip().upper() for g in args.solo.split(",") if g.strip()}
    preguntas = [q for q in PREGUNTAS if not grupos or q[0][0] in grupos]

    salida = Path(__file__).resolve().parent / "resultados_t082"
    salida.mkdir(exist_ok=True)
    ruta = salida / f"t082_{datetime.now():%Y%m%d_%H%M%S}.md"

    total = aciertos = 0
    palabras: list[float] = []
    conteo_banderas: Counter = Counter()
    respuestas_con_bandera = 0
    guardrail_reintentos = guardrail_quitadas = guardrail_corregidas = (
        respuestas_con_llm
    ) = 0
    registros: list[dict] = []
    fallos_categoria: list[str] = []
    informe = [
        f"# t082 — {datetime.now():%Y-%m-%d %H:%M}\n",
        f"Corridas: {args.corridas} · perfiles: {[a['label'] for a, _, _ in perfiles]}\n",
    ]

    for corrida in range(1, args.corridas + 1):
        for arquetipo, cargado, fila in perfiles:
            sim = simulacion_real(fila, pool)
            informe.append(
                f"\n## Corrida {corrida} — {arquetipo['label']} (nivel {cargado.plan.nivel})\n"
            )
            print(f"\n=== Corrida {corrida} · {arquetipo['label']} ===")
            for qid, esperadas, pregunta in preguntas:
                r = responder_chat(
                    pregunta, cargado, sim, [], nombre=arquetipo.get("nombre")
                )
                ok = r.categoria in esperadas
                total += 1
                aciertos += ok
                if not ok:
                    fallos_categoria.append(f"{arquetipo['label']}/{qid}→{r.categoria}")
                sin_llm = bool(r.detalle_debug.get("sin_llm"))
                # Respuestas armadas por código no traen contexto del modelo: se
                # verifican contra el bloque de cifras del plan (si no, TODOS sus
                # montos saldrían "sin respaldo": falso positivo del informe anterior).
                contexto = r.contexto or ctx.bloque_de_codigo(
                    "PERFIL", cargado, pregunta
                )
                v = vr.verificar(r.respuesta, contexto, r.categoria, cargado.plan.nivel)
                if sin_llm:
                    v["sin_aclarar_dolares"] = False  # texto fijo, trae su aclaración
                activas = _banderas_activas(v)
                palabras.append(v["palabras_por_frase"])
                for b in activas:
                    conteo_banderas[b.split("=")[0]] += 1
                respuestas_con_bandera += any(
                    b.split("=")[0] not in BANDERAS_INFORMATIVAS for b in activas
                )
                g = r.detalle_debug.get("guardrail")
                if g is not None:
                    respuestas_con_llm += 1
                    guardrail_reintentos += bool(g["reintento"])
                    guardrail_quitadas += bool(g["frases_quitadas"])
                    guardrail_corregidas += bool(g.get("cifras_corregidas"))
                registros.append(
                    {
                        "perfil": arquetipo["label"],
                        "corrida": corrida,
                        "qid": qid,
                        "pregunta": pregunta,
                        "categoria": r.categoria,
                        "respuesta": r.respuesta,
                        "banderas": [
                            b
                            for b in activas
                            if b.split("=")[0] not in BANDERAS_INFORMATIVAS
                        ],
                        "guardrail": bool(
                            g and (g["reintento"] or g.get("cifras_corregidas"))
                        ),
                    }
                )
                print(
                    f"[{'OK' if ok else 'DISTINTA'}] {qid} {r.categoria}"
                    + (f"  ⚑ {', '.join(activas)}" if activas else "")
                )
                informe += [
                    f"### {qid} — {pregunta}",
                    f"- Categoría: **{r.categoria}** (aceptables: {'/'.join(sorted(esperadas))}) "
                    f"→ {'OK' if ok else 'DISTINTA'}",
                    f"- Tokens del prompt: {r.detalle_debug.get('prompt_eval_count')}",
                    f"- Banderas: {', '.join(activas) if activas else 'ninguna'}",
                    (
                        "- Guardrail: "
                        + (
                            f"reintento (cifras: {g['cifras_primer_intento']}, juicio: {g['frases_primer_intento']})"
                            + (" · quitó frases" if g["frases_quitadas"] else "")
                        )
                        if g and g["reintento"]
                        else "- Guardrail: sin intervención"
                    ),
                    "",
                    "> " + r.respuesta.replace("\n", "\n> "),
                    "",
                    "Rúbrica (§1.3): [ ] se entiende sin saber de finanzas · "
                    "[ ] empieza por la respuesta · [ ] evita sonar condescendiente",
                    "Revisión de cifras: [ ] todas coinciden con el contexto\n",
                ]

    resumen = [
        "\n## RESUMEN",
        f"- Categoría aceptable: {aciertos}/{total}"
        + (
            f" · fuera de lo esperado: {', '.join(fallos_categoria)}"
            if fallos_categoria
            else ""
        ),
        (
            f"- Palabras por frase: media {statistics.mean(palabras):.1f} · "
            f"respuestas sobre {UMBRAL_PALABRAS_POR_FRASE}: "
            f"{sum(p > UMBRAL_PALABRAS_POR_FRASE for p in palabras)}/{len(palabras)}"
        ),
        f"- Respuestas con al menos una bandera (sin contar dólares): {respuestas_con_bandera}/{total}",
        f"- Guardrail: corrigió montos por redondeo en {guardrail_corregidas}, reintentó "
        f"{guardrail_reintentos}/{respuestas_con_llm} respuestas con LLM; tuvo que quitar "
        f"frases en {guardrail_quitadas}",
    ] + [f"- {b}: {n}" for b, n in conteo_banderas.most_common()]
    informe += resumen
    ruta.write_text("\n".join(informe), encoding="utf-8")
    muestra = rubrica_t082.construir_muestra(registros)
    ruta_muestra = ruta.with_name(ruta.stem + "_muestra.md")
    ruta_muestra.write_text(
        rubrica_t082.escribir_muestra(muestra, ruta.stem), encoding="utf-8"
    )
    print("\n".join(resumen))
    print(f"\nInforme completo: {ruta}")
    print(f"Muestra para la rúbrica manual ({len(muestra)} respuestas): {ruta_muestra}")
    print(
        f"  Llénala y corre: python -m assistant.run_faq_tests_t082 --calificar {ruta_muestra}"
    )
    print(
        "Recuerda: ninguna bandera es un veredicto. Lee las respuestas con la rúbrica."
    )
    return 0 if aciertos == total else 1


if __name__ == "__main__":
    sys.exit(main())

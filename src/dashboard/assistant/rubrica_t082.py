"""
Muestra y calificación de la rúbrica manual de `t082` (`t077` v2.3 §1.3)

La rúbrica manual (3 preguntas por respuesta) es el único criterio de cierre
que no puede medir una máquina, y leer 186 respuestas no es razonable. Este
módulo (funciones puras, sin Ollama ni BD):

  * `construir_muestra()` — elige qué respuestas leer: TODAS las que tuvieron
    una bandera real o una intervención del guardrail (hasta un tope) más unas
    cuantas al azar con semilla fija (82, el número de la tarea), para que la
    muestra sea reproducible y no solo mire lo que ya sabemos que falla.
  * `escribir_muestra()` — la escribe en Markdown, con las casillas.
  * `calificar()` — lee ese archivo ya llenado y calcula el porcentaje por
    criterio contra el umbral de cierre (80%, [PROPUESTA] a validar con el
    mentor) y exige un mínimo de respuestas revisadas.

Convención de llenado: una respuesta cuenta SOLO si marcas "Revisada: [x]".
Dentro de ella, [x] = cumple, [ ] = no cumple. (Si no hubiera "Revisada", una
respuesta que falla las 3 casillas parecería "sin revisar" y sesgaría el
resultado a favor.)
"""

from __future__ import annotations

import random
import re

CRITERIOS = (
    "se entiende sin saber de finanzas",
    "empieza por la respuesta",
    "evita sonar condescendiente",
)
UMBRAL_APROBACION = 0.80  # [PROPUESTA]
MINIMO_REVISADAS = 15  # [PROPUESTA]


def construir_muestra(
    registros: list[dict],
    semilla: int = 82,
    destacadas_max: int = 12,
    al_azar: int = 10,
) -> list[dict]:
    """`registros`: dicts con al menos `banderas` (lista de banderas REALES,
    sin las informativas) y `guardrail` (bool: intervino). Devuelve la muestra
    en orden estable."""
    destacadas = [r for r in registros if r["banderas"] or r["guardrail"]]
    destacadas.sort(key=lambda r: (-len(r["banderas"]), not r["guardrail"]))
    elegidas = destacadas[:destacadas_max]
    ids = {id(r) for r in elegidas}
    resto = [r for r in registros if id(r) not in ids]
    elegidas += random.Random(semilla).sample(resto, min(al_azar, len(resto)))
    return elegidas


def escribir_muestra(muestra: list[dict], titulo: str) -> str:
    lineas = [
        f"# {titulo} — muestra para la rúbrica manual\n",
        "Convención: marca `Revisada: [x]` en cada respuesta que leas; dentro de "
        "ella, `[x]` = cumple y `[ ]` = no cumple. Después corre:",
        "`python -m assistant.run_faq_tests_t082 --calificar <este archivo>`\n",
    ]
    for i, r in enumerate(muestra, 1):
        lineas += [
            f"### M{i:02d} · {r['perfil']} · corrida {r['corrida']} · {r['qid']} — {r['pregunta']}",
            f"- Categoría: {r['categoria']} · Banderas: "
            f"{', '.join(r['banderas']) if r['banderas'] else 'ninguna'} · Guardrail: "
            f"{'intervino' if r['guardrail'] else 'sin intervención'}",
            "",
            "> " + r["respuesta"].replace("\n", "\n> "),
            "",
            "Revisada: [ ]",
            "Rúbrica: " + " · ".join(f"[ ] {c}" for c in CRITERIOS),
            "Cifras: [ ] coinciden con las de «Lo que tengo hoy»\n",
        ]
    return "\n".join(lineas)


def _marcada(bloque: str, etiqueta: str) -> bool:
    m = re.search(rf"\[([ xX])\] {re.escape(etiqueta)}", bloque)
    return bool(m and m.group(1).lower() == "x")


def calificar(texto_md: str) -> dict:
    """Califica un archivo de muestra ya llenado."""
    bloques = re.split(r"\n(?=### M\d+)", texto_md)[1:]
    revisadas = [b for b in bloques if re.search(r"Revisada: \[[xX]\]", b)]
    n = len(revisadas)
    por_criterio = {c: sum(_marcada(b, c) for b in revisadas) for c in CRITERIOS}
    cumplen_3 = sum(all(_marcada(b, c) for c in CRITERIOS) for b in revisadas)
    cifras_ok = sum(_marcada(b, "coinciden con las de") for b in revisadas)
    pct = (cumplen_3 / n) if n else 0.0
    if n < MINIMO_REVISADAS:
        veredicto = (
            f"MUESTRA INSUFICIENTE: {n} revisadas, se piden al menos {MINIMO_REVISADAS}"
        )
    elif pct >= UMBRAL_APROBACION and cifras_ok == n:
        veredicto = "APRUEBA"
    elif pct >= UMBRAL_APROBACION:
        veredicto = "NO APRUEBA: alguna respuesta tiene cifras que no coinciden (eso no se negocia)"
    else:
        veredicto = f"NO APRUEBA: {pct * 100:.0f}% cumple las 3, se pide {UMBRAL_APROBACION * 100:.0f}%"
    return {
        "en_muestra": len(bloques),
        "revisadas": n,
        "por_criterio": por_criterio,
        "cumplen_los_3": cumplen_3,
        "porcentaje_cumplen_los_3": round(pct, 3),
        "cifras_coinciden": cifras_ok,
        "veredicto": veredicto,
    }

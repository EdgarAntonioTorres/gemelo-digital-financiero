"""
Verificaciones automáticas de una respuesta de Centavo (`t082`, `t077` §1.3)

Funciones PURAS (sin Ollama, sin BD) que miran el texto de una respuesta y
devuelven banderas. Las usan el router (para mostrar `cifras_sin_respaldo`
en el detalle de depuración) y `run_faq_tests_t082.py` (métricas por
corrida). Cada una nació de una falla real observada en la Sesión 36:

  * cifras_sin_respaldo   — "te faltan $8,691" cuando el dato era $8,692 (el
                            modelo resta cifras ya redondeadas), y las cifras
                            inventadas de la primera corrida ("71.16%").
  * texto_pegado          — "($2,443)es", "Te faltan$6,043", "$627 almes".
  * palabras_por_frase    — umbral de claridad de t077 §1.1.2 [PROPUESTA].
  * terminos_sin_explicar — heurística; la lista de términos es [PROPUESTA]
                            (pendiente 2 del handoff). SIRVE PARA REVISAR, no
                            como pass/fail: explicar un término bien puede
                            requerir una redacción que el patrón no reconoce.
  * siglas_solas          — t077 §1.1.5: nunca una sigla sin su significado.
  * frases_prohibidas, bancos_o_marcas, bajo_riesgo_con_rendimiento,
    sin_aclarar_dolares, nivel1_recomienda_inversion — barreras de §3/§4/§5.

Son heurísticas con falsos positivos y negativos posibles: una bandera es
"mira esta respuesta", no "esta respuesta está mal". La lectura humana con la
rúbrica de 3 preguntas (§1.3) sigue siendo la que decide.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Cifras
# ---------------------------------------------------------------------------
TOLERANCIA_REDONDEO_PCT = 1.0  # puntos porcentuales

# Porcentaje con punto O coma decimal: el modelo escribe "67,3%" (en la primera
# versión eso se leía como "3%" y daba falsos positivos).
_RE_CIFRA = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)|(\d+(?:[.,]\d+)?)\s?%")


def _norm(numero: str) -> str:
    valor = float(numero.replace(",", "").rstrip("."))
    return format(valor, ".2f").rstrip("0").rstrip(".")


def _claves(texto: str, solo_dolares: bool = False) -> dict[str, str]:
    """{clave normalizada: texto original}. '$' y '%' distinguen unidades."""
    salida: dict[str, str] = {}
    for m in _RE_CIFRA.finditer(texto):
        if m.group(1) is not None:
            crudo = m.group(1).rstrip(",")
            salida.setdefault("$" + _norm(crudo), "$" + crudo)
        elif not solo_dolares:
            crudo = m.group(2)
            salida.setdefault(_norm(crudo.replace(",", ".")) + "%", crudo + "%")
    return salida


def cifras_sin_respaldo(
    respuesta: str, contexto: str, solo_dolares: bool = False
) -> list[str]:
    """Montos en dólares (y porcentajes, salvo `solo_dolares`) de la respuesta
    que NO aparecen en el contexto (prompt + historial + pregunta). Cubre
    inventos y restas. `solo_dolares=True` es lo que usa el guardrail en vivo:
    un porcentaje derivado ('58%' a partir de '$58 de cada $100') es inocuo; un
    monto inventado ('$4,054') no."""
    en_contexto = _claves(contexto, solo_dolares)
    porcentajes_ctx = [float(k[:-1]) for k in en_contexto if k.endswith("%")]
    sin_respaldo = []
    for clave, orig in _claves(respuesta, solo_dolares).items():
        if clave in en_contexto:
            continue
        if clave.endswith("%") and any(
            abs(float(clave[:-1]) - c) <= TOLERANCIA_REDONDEO_PCT
            for c in porcentajes_ctx
        ):
            continue  # redondeo ("67%" por 67.3%): no es una cifra inventada
        sin_respaldo.append(orig)
    return sin_respaldo


def reparar_montos_cercanos(
    respuesta: str, contexto: str, tolerancia: float = 2.0
) -> tuple[str, dict[str, str]]:
    """Corrige restas de redondeo del modelo: un monto sin respaldo que está a
    ≤ $2 de UN monto del contexto se reemplaza por ese monto ("$1,412" ->
    "$1,411"; "$8,691" -> "$8,692"; "$6,043" -> "$6,044": las 3 aparecieron en
    corridas reales porque el modelo restó cifras ya redondeadas). Solo para
    montos ≥ $100 (en cantidades chicas $2 sí cambia el sentido). Si no hay un
    monto cercano, no toca nada: eso lo atiende el guardrail. Devuelve
    (texto, {original: corregido})."""
    ctx = [(float(k[1:]), orig) for k, orig in _claves(contexto, True).items()]
    ctx_claves = set(_claves(contexto, True))
    cambios: dict[str, str] = {}
    for clave, orig in _claves(respuesta, True).items():
        if clave in ctx_claves:
            continue
        valor = float(clave[1:])
        if valor < 100:
            continue
        cercanos = sorted(
            (abs(valor - v), o) for v, o in ctx if abs(valor - v) <= tolerancia
        )
        if cercanos:
            cambios[orig] = cercanos[0][1]
    texto = respuesta
    for orig, nuevo in cambios.items():
        texto = re.sub(re.escape(orig) + r"(?!\d|,\d)", lambda _m, n=nuevo: n, texto)
    return texto, cambios


# ---------------------------------------------------------------------------
# Forma del texto
# ---------------------------------------------------------------------------
def palabras_por_frase(texto: str) -> float:
    """Promedio de palabras por frase. No parte dentro de cifras ('3,704.29')."""
    limpio = re.sub(r"[*_`#>]", "", texto)
    frases = [f for f in re.split(r"(?<=[.!?])\s+|\n+", limpio.strip()) if f.strip()]
    if not frases:
        return 0.0
    # Una cifra ("$3,704.29", "17%") cuenta como UNA palabra.
    palabras = sum(
        len(re.findall(r"\$?\d+(?:[.,]\d+)*%?|[^\W\d_]+", f)) for f in frases
    )
    return palabras / len(frases)


_RE_PEGADO = (
    re.compile(r"\d[a-záéíóúñ]{2,}"),  # $72,000serían
    re.compile(r"\)[a-záéíóúñ]"),  # ($2,443)es
    re.compile(r"[a-záéíóúñ]\$\d"),  # Te faltan$6,043
    re.compile(r"\balmes\b", re.IGNORECASE),  # "$627 almes" (visto 3 veces)
)


def texto_pegado(texto: str) -> list[str]:
    hallazgos: list[str] = []
    for patron in _RE_PEGADO:
        hallazgos += [m.group(0) for m in patron.finditer(texto)]
    return hallazgos


# ---------------------------------------------------------------------------
# Jerga y siglas
# ---------------------------------------------------------------------------
# [PROPUESTA] lista inicial; el handoff la deja pendiente de definir.
TERMINOS_TECNICOS = (
    "ratio de endeudamiento",
    "interés compuesto",
    "rendimiento",
    "liquidez",
    "apalancamiento",
    "amortización",
    "portafolio",
    "diversificación",
    "diversificar",
    "inflación",
    "tasa de interés",
    "buró de crédito",
    "score crediticio",
    "flujo de caja",
    "activos",
    "pasivos",
    "dividendos",
    "volatilidad",
    "intervalo de confianza",
    "monte carlo",
    "bootstrap",
    "percentil",
    "mediana",
)
_PISTAS_DE_EXPLICACION = (
    "significa",
    "es decir",
    "o sea",
    "quiere decir",
    "se refiere",
    "es como",
    "por ejemplo",
    "es el ",
    "es la ",
    "es un ",
    "es una ",
    "se trata de",
    "dinero que",
    "porcentaje de",
)


def terminos_sin_explicar(texto: str) -> list[str]:
    bajo = texto.lower()
    sin_explicar: list[str] = []
    for termino in TERMINOS_TECNICOS:
        for m in re.finditer(re.escape(termino), bajo):
            ventana = bajo[max(0, m.start() - 80) : m.end() + 120]
            if not any(p in ventana for p in _PISTAS_DE_EXPLICACION):
                sin_explicar.append(termino)
                break
    return sin_explicar


def siglas_solas(texto: str) -> list[str]:
    """IRFI/ICA que la respuesta NUNCA define. Si la respuesta dice una vez
    'índice de riesgo...' / 'índice de capacidad...', usar la sigla después es
    correcto (la versión anterior exigía la definición en cada frase y dio
    9 falsos positivos en 186 respuestas)."""
    bajo = texto.lower()
    definiciones = {"IRFI": "índice de riesgo", "ICA": "índice de capacidad"}
    return [
        sigla
        for sigla, definicion in definiciones.items()
        if re.search(rf"\b{sigla}\b", texto) and definicion not in bajo
    ]


# ---------------------------------------------------------------------------
# Barreras de política (t077 §3, §4, §5)
# ---------------------------------------------------------------------------
# "no puedes evitar" (un gasto) no es un dictamen sobre la persona; "no puedes
# alcanzar / solicitar..." sí (t077 §3: se dice "todavía te falta X para Y").
_RE_PROHIBIDAS = re.compile(
    r"\bno (calificas|eres elegible)\b"
    r"|\bno puedes (llegar|alcanzar|acceder|solicitar|pedir|obtener|tener|comprar)\b",
    re.IGNORECASE,
)
# [PROPUESTA] lista inicial de nombres comerciales que Centavo no debe citar.
_RE_BANCOS = re.compile(
    r"\b(BBVA|Santander|Banorte|Citibanamex|Banamex|HSBC|Scotiabank|Inbursa|"
    r"Banco Azteca|Afirme|Hey Banco|Mercado Pago|Chase|Wells Fargo|Bank of America|"
    r"Binance|Bitcoin|Ethereum)\b"
)


def frases_prohibidas(texto: str) -> list[str]:
    return [m.group(0) for m in _RE_PROHIBIDAS.finditer(texto)]


def bancos_o_marcas(texto: str) -> list[str]:
    return [m.group(0) for m in _RE_BANCOS.finditer(texto)]


def bajo_riesgo_con_rendimiento(texto: str) -> bool:
    """'bajo riesgo' y el 6% en la misma frase: el 6.0% es un supuesto del
    escenario, nunca el rendimiento de un producto (t077 §5)."""
    for frase in re.split(r"(?<=[.!?])\s+|\n+", texto):
        if "bajo riesgo" in frase.lower() and re.search(r"\b6(\.0)?\s?%", frase):
            return True
    return False


def sin_aclarar_dolares(texto: str) -> bool:
    return "$" in texto and not re.search(r"d[oó]lares|\bUSD\b", texto, re.IGNORECASE)


def nivel1_recomienda_inversion(texto: str, categoria: str, nivel: int) -> bool:
    return (
        categoria == "PRODUCTO"
        and nivel == 1
        and bool(
            re.search(
                r"(te (recomiendo|conviene|sugiero)|puedes (empezar|comenzar)|es buen momento)"
                r"[^.]{0,60}(inversi[oó]n|invertir|retiro)",
                texto,
                re.IGNORECASE,
            )
        )
    )


# Juicio de valor sobre la persona (t077 §1.1: sin regaños ni condescendencia).
# [PROPUESTA] lista inicial, sacada de respuestas reales de la Sesión 36.
_RE_TONO_JUICIO = re.compile(
    r"no es (muy )?saludable|ser (más )?cuidados[oa]|est[aá]s (un poco |muy )?endeudad[oa]"
    r"|irresponsable|mal manejo|gastas demasiado|es un problema|preocupante",
    re.IGNORECASE,
)
# "Lo ideal sería llegar a $40 de cada $100" (Ana con $17): invierte el sentido
# del tope. "Lo ideal" sobre deuda o índices se marca; sobre el fondo, no.
_RE_LO_IDEAL = re.compile(r"\blo ideal\b", re.IGNORECASE)
_RE_TEMA_DEUDA_O_INDICES = re.compile(
    r"deuda|\$100|ratio|\bIRFI\b|\bICA\b", re.IGNORECASE
)
# El IRFI y el ICA solo tienen valor y dirección; no hay umbrales definidos.
_RE_UMBRAL = re.compile(
    r"\b(ideal|manejable|moderad[oa]|extremo|saludable|alta capacidad|baja capacidad"
    r"|riesgo (alto|elevado)|alto riesgo)\b",
    re.IGNORECASE,
)


def tono_juicio(texto: str) -> list[str]:
    hallazgos = [m.group(0) for m in _RE_TONO_JUICIO.finditer(texto)]
    for frase in re.split(r"(?<=[.!?])\s+|\n+", texto):
        if _RE_LO_IDEAL.search(frase) and _RE_TEMA_DEUDA_O_INDICES.search(frase):
            hallazgos.append(_RE_LO_IDEAL.search(frase).group(0))
    return hallazgos


# Valoraciones del IRFI/ICA aunque la frase no nombre la sigla ("En tu caso,
# tienes una buena capacidad de ahorro" con un ICA de 0.48: no hay umbral).
_RE_UMBRAL_LIBRE = re.compile(
    r"\b(buena|mala|alta|baja|poca|mucha) capacidad de ahorro"
    r"|riesgo financiero (moderado|alto|bajo|elevado)\b",
    re.IGNORECASE,
)


def umbral_inventado(texto: str, permitidas: frozenset[str] = frozenset()) -> list[str]:
    """Frases que le ponen al IRFI/ICA una etiqueta o rango que NO es el oficial.
    `permitidas`: fragmentos en minúsculas que coinciden con la etiqueta oficial de
    esta persona (ver `indicadores.etiquetas_permitidas`): "moderado" con un IRFI
    Moderado es correcto y no se marca; "riesgo alto" con ese mismo IRFI sí. Sin
    `permitidas` (por defecto) se marca todo, que era el comportamiento original."""
    hallazgos: list[str] = []
    for frase in re.split(r"(?<=[.!?])\s+|\n+", texto):
        if re.search(r"\b(IRFI|ICA)\b|índice de (riesgo|capacidad)", frase):
            hallazgos += [m.group(0) for m in _RE_UMBRAL.finditer(frase)]
        hallazgos += [m.group(0) for m in _RE_UMBRAL_LIBRE.finditer(frase)]
    return [h for h in hallazgos if h.lower() not in permitidas]


def frases_de_juicio(texto: str, permitidas: frozenset[str] = frozenset()) -> list[str]:
    """Frases (completas) que juzgan a la persona o le inventan umbrales al
    IRFI/ICA. Las usa el guardrail en vivo para quitarlas si el reintento no
    las corrige."""
    malas = []
    for frase in re.split(r"(?<=[.!?])\s+", texto.strip()):
        if tono_juicio(frase) or umbral_inventado(frase, permitidas):
            malas.append(frase)
    return malas


# ---------------------------------------------------------------------------
def verificar(respuesta: str, contexto: str, categoria: str, nivel: int) -> dict:
    """Todas las banderas de una respuesta. Valores vacíos/False = sin bandera."""
    return {
        "palabras_por_frase": round(palabras_por_frase(respuesta), 1),
        "cifras_sin_respaldo": cifras_sin_respaldo(respuesta, contexto),
        "texto_pegado": texto_pegado(respuesta),
        "terminos_sin_explicar": terminos_sin_explicar(respuesta),
        "siglas_solas": siglas_solas(respuesta),
        "frases_prohibidas": frases_prohibidas(respuesta),
        "tono_juicio": tono_juicio(respuesta),
        "umbral_inventado": umbral_inventado(respuesta),
        "bancos_o_marcas": bancos_o_marcas(respuesta),
        "bajo_riesgo_con_6pct": bajo_riesgo_con_rendimiento(respuesta),
        "sin_aclarar_dolares": sin_aclarar_dolares(respuesta),
        "nivel1_recomienda_inversion": nivel1_recomienda_inversion(
            respuesta, categoria, nivel
        ),
    }

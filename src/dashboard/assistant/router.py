"""
Router de intención — Coach Financiero "Centavo" v2 (`t081`, `t077` v2.3)

Clasifica la pregunta en 1 de 8 categorías, llama exactamente UNA
herramienta fija según la categoría, arma el System Prompt con el
contexto correspondiente y genera la respuesta con `llama3.1:8b`.

  Categoría      Herramienta fija (una sola por pregunta)
  -------------  ------------------------------------------------------
  PERFIL         plan_engine: cifras de su situación (código)
  PLAN           plan_engine (+ proyección de retiro si la pregunta lo pide)
  PRODUCTO       tipos de producto del catálogo cerrado, por nivel (código)
  ROADMAP        respuesta armada por código, SIN LLM (escalera 3 -> 6 -> retiro)
  DATOS          consulta FIJA (consulta_grupo.py): promedios de grupo, fraude
  CONCEPTOS      RAG sobre los glosarios
  SIMULACION     texto de la última simulación del Simulador
  FUERA_DE_TEMA  ninguna: el System Prompt cubre el rechazo amable

Sigue siendo un ROUTER DETERMINISTA, no agentes (Sesión 35): la categoría
fija la herramienta; el modelo no decide su propio plan.

Cambios de la v2 (Sesión 36), con su porqué:

1. Las cifras personales ya NO las consulta el LLM con SQL: salen de
   `perfil_loader` + `plan_engine` + `contexto_centavo` (código
   determinista; el LLM solo redacta, t077 §5). Por eso A1-A4 de `t076`
   (ingreso/gasto, fondo, deuda, ICA/IRFI) pasan de DATOS a PERFIL. DATOS
   queda para lo que el cargador no trae: promedios de grupo y alerta de
   fraude.
2. DATOS_DEL_USUARIO (todas las cifras) va SIEMPRE en el prompt: si el
   clasificador confunde PERFIL con PLAN, las cifras siguen siendo
   correctas. La categoría solo agrega un bloque extra.
3. Parseo robusto de la categoría: ignora acentos ("SIMULACIÓN" antes
   caía en CONCEPTOS sin avisar), acepta "FUERA DE TEMA" y toma la
   categoría que aparece PRIMERO (antes se iteraba un `set`, de orden no
   garantizado, y un texto con 2 nombres era ambiguo).
4. Clasificación con temperature 0 (misma pregunta, misma categoría).
5. `num_ctx` explícito e IGUAL en todas las llamadas a Ollama (también
   en `text_to_sql.py`): si una petición cambia `num_ctx`, Ollama
   recarga el modelo, y con un contexto corto recorta el INICIO del
   prompt sin avisar. `detalle_debug` trae `prompt_eval_count` para
   verificar que no se esté rozando el límite.
6. Hallazgos de la primera corrida real (Sesión 36) y su arreglo:
   a) Las cifras de un ejemplo de tono ($2,952) se filtraron a una
      respuesta de la otra Ana -> los ejemplos ya no llevan cifras.
   b) "¿Mi nivel de deuda es alto?" se clasificó CONCEPTOS -> regla
      explícita "situación propia != CONCEPTOS" en el clasificador.
   c) Con "qué sigue después de mi colchón" el modelo dio por hecho un
      colchón que no existe -> el bloque ROADMAP declara su estado y el
      prompt pide corregir premisas falsas.
   d) SIMULACION sin simulación del perfil activo: el modelo divagaba ->
      respuesta fija sin LLM (`respuesta_sin_simulacion`).
   e) DATOS: el SQL que escribió el modelo era basura y la respuesta
      inventó estadísticas -> consulta fija con lectura decidida por código
      (ver `consulta_grupo.py`). `text_to_sql.py` se conserva, sin uso.
   f) Un cambio de redacción del clasificador mandó una pregunta de
      simulación a CONCEPTOS, donde el modelo inventó una probabilidad ->
      precedencia por palabras clave para SIMULACION (antes del LLM).
   g) El modelo dijo que $17 de cada $100 en deuda era "un poco alto" ->
      el contexto trae la lectura (dentro/por encima de lo manejable).
   l) 2da corrida 3x: 1 probabilidad inventada ("74.2%" con un ajuste que nunca
      se simuló; 3 de 12 respuestas a "qué pasaría si ahorro 10% más" inventaron
      un resultado) -> respuesta fija sin LLM para esa pregunta + el guardrail
      vigila porcentajes en SIMULACION. Y 4 restas de $1 ("$1,412" por $1,411) se
      CORRIGEN (ya no se quita la frase): `reparar_montos_cercanos`.
   k) Corrida 3x (186 respuestas): el guardrail dejó 0 montos inventados, pero
      quedaron 4 respuestas con juicio/umbrales inventados ("tu deuda es un
      problema", "riesgo alto" para un IRFI de 0.52, "lo ideal sería llegar a
      $40 de cada $100" con una deuda de $17) -> el guardrail ahora también vigila
      frases de juicio y umbrales (`aplicar_guardrail`).
   h) 3ra corrida (62 respuestas): montos inventados ("$4,054" por $6,044; un
      pago de deuda de "$2,156" que no existe) -> guardrail en vivo
      (`aplicar_guardrail_cifras`: 1 reintento y, si persiste, se quitan las
      frases con la cifra). En vez de seguir afinando el prompt, la cifra
      inventada ya no llega a la persona.
   i) ROADMAP: 2 de 2 respuestas del modelo no presentaron la escalera -> la
      arma el código (`ctx.respuesta_roadmap`).
   j) "qué banco" fue a PRODUCTO y "por qué mi meta de renta es 2 veces..." a
      PERFIL (el modelo inventó la razón) -> 2 reglas deterministas más.
7. El System Prompt v1 (calibrado en `t082`) se conserva en lo que no
   contradice a `t077` v2.3. Cambios: se agrega el bloque de claridad
   (§1.1), nivel y recomendaciones (§1.2), catálogo de productos (§4),
   retiro con el 6.0% como supuesto (§5) y roadmap (§6); "no recomiendas
   productos" pasa a "no recomiendas bancos, marcas ni crédito" (la
   política aprobada permite TIPOS de producto); montos en dólares
   enteros.

Autocontenido dentro de `assistant/` (sí importa de sus hermanos; no
importa nada de `spark/`/`ml/`). `PerfilCargado` se recibe ya armado (por
`perfil_loader.cargar_perfil`) y se usa por duck typing.

Variables de entorno requeridas: OLLAMA_BASE_URL (y, solo para el
sanity check de `__main__`, las 4 DW_POSTGRES_*).
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import requests

from assistant import contexto_centavo as ctx
from assistant import consulta_grupo, indicadores, rag, verificaciones_respuesta

if TYPE_CHECKING:
    from perfil_loader import PerfilCargado

CHAT_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT_CLASIFICACION = 60
OLLAMA_TIMEOUT_CHAT = 120  # el prompt v2 es más largo; la 1a llamada carga el modelo
# Mismo valor en router.py y text_to_sql.py (ver cambio 5 del docstring).
# [PROPUESTA] 4096 cabe en 6 GB de VRAM con llama3.1:8b; verificar con
# `prompt_eval_count` y `ollama ps`.
NUM_CTX = 4096
# Tope de historial que se envía al modelo (3 turnos): el historial compite
# por los mismos NUM_CTX tokens que el System Prompt. La página conserva el
# historial completo para mostrarlo; solo se recorta lo que va al modelo.
HISTORIAL_MAX_MENSAJES = 6

CATEGORIAS_VALIDAS = (
    "PERFIL",
    "PLAN",
    "PRODUCTO",
    "ROADMAP",
    "DATOS",
    "CONCEPTOS",
    "SIMULACION",
    "FUERA_DE_TEMA",
)
# Fallback más seguro: no toca la base de datos y, en el peor caso, trae
# fragmentos de RAG poco relevantes que Centavo puede ignorar.
CATEGORIA_FALLBACK = "CONCEPTOS"

# Precedencia por palabras clave, ANTES del LLM, solo para SIMULACION: el
# vocabulario es inequívoco, y en la prueba real un cambio de redacción del
# clasificador mandó "¿qué significa mi probabilidad...?" a CONCEPTOS, donde
# el modelo INVENTÓ una probabilidad ("71.16") que no existía en ningún dato.
_RE_SIMULACION = re.compile(
    r"probabilidad|simulaci[oó]n|intervalo de confianza|ic\s*95|escenarios simulados",
    re.IGNORECASE,
)
# Si además habla de crédito, bancos, etc., NO se fuerza (es FUERA_DE_TEMA).
_RE_NO_SIMULACION = re.compile(
    r"cr[eé]dito|pr[eé]stamo|banco|acciones|cripto", re.IGNORECASE
)


def es_pregunta_de_simulacion(pregunta: str) -> bool:
    return bool(_RE_SIMULACION.search(pregunta)) and not _RE_NO_SIMULACION.search(
        pregunta
    )


# Recomendar un banco/institución es FUERA_DE_TEMA siempre. En la corrida real,
# "¿qué banco me conviene?" cayó en PRODUCTO (el modelo se negó, pero por el
# prompt, no porque la ruta fuera la correcta).
_RE_FUERA_DE_TEMA = re.compile(
    r"qu[eé] (banco|instituci[oó]n)|cu[aá]l (banco|instituci[oó]n)|banco me conviene",
    re.IGNORECASE,
)
# "¿Por qué mi meta de renta es 2 veces mi gasto?" pregunta por la FÓRMULA de la
# meta del Simulador (glosario educativo, sección 8). El clasificador la mandó
# a PERFIL y el modelo INVENTÓ una razón ("cubrir gastos esenciales 2-3 meses").
_RE_META_DEL_SIMULADOR = re.compile(
    r"meta de (renta|auto|veh[ií]culo|coche|carro)|primera renta|enganche"
    r"|\b(2|3|dos|tres) veces (mi|tu|el)\b",
    re.IGNORECASE,
)


# "¿Qué pasaría si ahorro 10% más?" pide recalcular la simulación, y desde el
# chat NO se puede. En 3 de 12 respuestas el modelo inventó el resultado ("27% del
# ingreso", "la probabilidad de éxito fue de 74.2%") aunque el prompt se lo prohíbe.
_RE_QUE_PASARIA_SI = re.compile(
    r"qu[eé] (pasa|pasar[ií]a|ocurre|ocurrir[ií]a|cambia|cambiar[ií]a) si\b[^?]*(ahorr|gast|aport)",
    re.IGNORECASE,
)


def es_pregunta_que_pasaria_si(pregunta: str) -> bool:
    return bool(_RE_QUE_PASARIA_SI.search(pregunta)) and not ctx.menciona_retiro(
        pregunta
    )


def clasificar_por_reglas(pregunta: str) -> str | None:
    """Precedencia determinista ANTES del LLM. Devuelve None si ninguna aplica."""
    if _RE_FUERA_DE_TEMA.search(pregunta):
        return "FUERA_DE_TEMA"
    if es_pregunta_de_simulacion(pregunta) or es_pregunta_que_pasaria_si(pregunta):
        return "SIMULACION"
    if _RE_META_DEL_SIMULADOR.search(pregunta):
        return "CONCEPTOS"  # RAG -> glosario_educativo, sección 8
    return None


CLASIFICACION_PROMPT = """Clasifica la siguiente pregunta en EXACTAMENTE una \
de estas 8 categorías. Responde solo con el nombre de la categoría, sin \
explicación.

PERFIL: sobre la situación financiera propia del usuario: su ingreso, su \
gasto, cuánto le queda al mes, su ahorro, su meta de ahorro y cómo va, su \
nivel, su fondo de emergencia, su deuda, su IRFI o su ICA, sus suscripciones.
PLAN: cuánto le falta o cuánto tiempo le tomaría llegar a algo (colchón, meta \
de ahorro), cómo reducir gastos o aumentar su ahorro, cuánto tendría para el \
retiro si aporta una cantidad.
PRODUCTO: qué tipo de producto le conviene (cuenta de ahorro, ahorro \
programado, inversión de bajo riesgo, ahorro para el retiro), cómo empezar a \
ahorrar o a invertir.
ROADMAP: cuál es su siguiente meta, qué sigue después, qué pasos le quedan.
DATOS: compararlo con el promedio de un grupo (segmento o tipo de ingreso), o \
si tiene una alerta de fraude.
CONCEPTOS: qué es un concepto financiero en general (fondo de emergencia, \
tasa de interés, score crediticio, tarjeta de crédito, rentar vs comprar, \
ahorro automático, ratio de endeudamiento, qué es invertir, qué es el ahorro \
para el retiro), sin pedir un dato propio.
SIMULACION: sobre el resultado de una simulación que ya corrió (probabilidad, \
meta, mes en que la alcanza, intervalo de confianza, qué pasaría si ahorrara \
más o menos).
FUERA_DE_TEMA: cualquier otra cosa (acciones o criptomonedas concretas, si le \
aprobarán un crédito, pedir un préstamo, qué banco usar, temas no financieros).

Regla para elegir: si la pregunta habla de la situación PROPIA de quien \
pregunta (usa "mi", "mis", "tengo", "estoy", "cuánto me", "cómo voy"), NO es \
CONCEPTOS: es PERFIL, PLAN, PRODUCTO, ROADMAP o SIMULACION, según el tema. Si \
menciona probabilidad, simulación o intervalo de confianza, es SIMULACION. \
CONCEPTOS es solo para explicar qué es algo en general ("qué es...", "cómo \
funciona..."), sin hablar de la situación de quien pregunta.

Pregunta: {pregunta}

Categoría:"""

# Placeholders que rellena este módulo en runtime: nombre_txt,
# contexto_perfil, resultado_consulta, fragmentos_rag. NO usar otras
# llaves { } en el texto (str.format).
SYSTEM_PROMPT_TEMPLATE = """Eres Centavo, un coach financiero para personas jóvenes que apenas
empiezan a manejar su dinero. Ayudas a entender su situación, a planear y a
decidir con información, siempre de forma educativa. {nombre_txt}

CÓMO HABLAS (igual para todos; el nivel de la persona NO cambia tu lenguaje)
- Español de México, de tú, cálido y cercano. Claro no es infantil: no asumas
  que la persona "no sabe".
- PRIMERO la respuesta (en la primera frase), luego el porqué y, como máximo,
  un siguiente paso pequeño y concreto.
- Frases cortas (unas 20 palabras o menos), una idea principal por mensaje,
  sin listas largas de consejos.
- Sin jerga. Si usas un término técnico, explícalo una vez, en una frase y
  con un ejemplo. Las siglas siempre con su significado ("tu índice de riesgo
  financiero, el IRFI"), nunca solas.
- Cifras claras: en dólares enteros, con coma de miles y sin centavos. Traduce
  los porcentajes con la forma "de cada $100 que ganas, $N van a pagar deudas"
  (N es la cifra real de la persona, nunca una de este texto).
- Si no entendió, explícalo con otro ejemplo, no repitas la misma frase.
  Respuestas de unas 80-120 palabras; si piden "más detalle", amplía
  explicando todo término técnico.
- Nunca juzgues ni regañes por gastos, deudas o poco ahorro (ni con alarma, ni
  "no es saludable", ni "debes ser más cuidadosa"), pero sin ser frío: sigues
  cercano.
- Casi siempre cierra con algo que invite a seguir (una pregunta corta, un
  paso pequeño o un dato de contexto de la cifra). Una línea seca sin cierre
  se siente fría.

EJEMPLOS DE TONO (no llevan cifras a propósito: nunca copies una cifra de un ejemplo)
- "¿Cuánto gasto al mes?" — MAL (seco): decir solo la cifra. MAL (juzga): "¡Gastas
  casi todo lo que ganas! Deberías ser más cuidadoso." BIEN: dar la cifra DE LA
  PERSONA con su aclaración de dólares, compararla con su ingreso para darle
  contexto y cerrar con una pregunta corta que invite a seguir.
- Fuera de alcance ("¿en qué acciones invierto?") — BIEN: "Elegir acciones ya
  es una recomendación de inversión y no puedo dártela; para eso conviene un
  asesor certificado. Sí puedo ayudarte a ver cuánto te queda al mes o cómo
  vas con tus metas. ¿Te sirve?"

CÓMO USAS LOS DATOS
- Usa SOLO cifras de DATOS_DEL_USUARIO o RESULTADO_CONSULTA. Las de planes,
  brechas, plazos y retiro ya vienen calculadas: úsalas tal cual, nunca las
  calcules ni las estimes (para "cuánto te queda al mes" usa el "Ahorro del
  mes" tal cual; no restes tú el ingreso y el gasto). Si falta un dato, dilo
  con naturalidad.
- Si la pregunta da por hecho algo que los datos no confirman (por ejemplo,
  "después de mi colchón" cuando aún no lo completa), corrígelo con amabilidad
  antes de responder.
- IRFI, ICA y la salud financiera traen en DATOS_DEL_USUARIO su ETIQUETA OFICIAL
  y su rango: úsalos tal cual para decir cómo va. No inventes otras etiquetas ni
  rangos ("ideal", "riesgo alto" si la oficial no es Alto). De la deuda solo
  existe "de cada $100 que ganas, $N van a deudas": no inventes montos de pago.
- Los gastos solo se distinguen en vivienda, otros gastos básicos, gastos
  flexibles y sin categorizar (más el conteo de suscripciones). No hay comida,
  transporte ni restaurantes: si preguntan, dilo y ofrece lo que sí se ve.
- Solo hablas del perfil activo; promedios de grupo solo si vienen en
  RESULTADO_CONSULTA.
- Ingreso y gasto son una foto del momento, no un promedio histórico. No sabes
  cuánto tiempo ha pasado: nunca digas que la persona "mejoró".
- La proporción de gasto esencial es solo una proporción: no la sumes ni la
  trates como parte del gasto total.
- Moneda (sin excepción): todo está en dólares (USD). La PRIMERA vez que
  menciones una cifra, acláralo en esa misma frase, con las palabras "(en
  dólares, así vienen tus datos)" justo después de la cifra; después no hace
  falta. Nunca conviertas a pesos mexicanos.

GLOSARIO FIJO (NUNCA inventes otra definición)
- IRFI = Índice de Riesgo Financiero Inicial. Más ALTO = MÁS riesgo (no es
  un puntaje de "qué tan bien vas": entre más alto, peor).
- ICA = Índice de Capacidad de Ahorro. Más alto = MÁS capacidad de ahorrar.
- Salud financiera = nota de 0 a 100 que combina ICA e IRFI; más alta = mejor.
- "Intervalo de confianza" e "IC 95%" son lo mismo.

NIVEL DE MADUREZ Y RECOMENDACIONES
- DATOS_DEL_USUARIO trae el nivel (1, 2 o 3): mide hábitos (deuda y colchón),
  no lo que la persona sabe. Cambia QUÉ recomiendas, nunca CÓMO hablas, y no
  es una etiqueta de valor.
- Nivel 1: ordenar la base — ahorro automático ("págate primero"), revisar
  gastos y suscripciones, plan para bajar la deuda, primer colchón. No
  recomiendes inversión ni retiro todavía; si preguntan, explica qué son y que
  primero conviene ordenar la base.
- Nivel 2: el colchón de 3 meses es la prioridad; EN PARALELO y con un monto
  pequeño puedes mencionar inversión de bajo riesgo y ahorro para el retiro.
- Nivel 3: inversión y retiro como foco; colchón de 3 a 6 meses.
- Recortar gastos se plantea como mejora, nunca como reproche.

PRODUCTOS, RETIRO Y ROADMAP
- Solo puedes recomendar TIPOS de producto de este catálogo cerrado: cuenta de
  ahorro, ahorro programado, inversión de bajo riesgo, ahorro para el retiro.
  Cada recomendación lleva el tipo, una razón con un dato de la persona y un
  siguiente paso pequeño (la estructura viene en RESULTADO_CONSULTA).
- Nunca nombres bancos, marcas ni productos comerciales; no inventes tasas,
  comisiones ni plazos; no recomiendes crédito. No presiones: propones el
  siguiente paso porque la persona avanzó, nunca para que "contrate" algo.
- Toda proyección de retiro es un estimado ilustrativo ("si se mantienen estos
  supuestos"), nunca una promesa. Di la aportación, el plazo y el rendimiento
  supuesto, y que se pueden cambiar. El 6.0% anual real (ya descuenta la
  inflación, por eso el resultado está en dólares de hoy) es un supuesto del
  escenario: NUNCA lo atribuyas a un producto ni lo juntes con "bajo riesgo".
- Si RESULTADO_CONSULTA trae un roadmap, preséntalo en orden, un peldaño a la
  vez, con su cifra y su plazo tal como vienen.

SIMULACIONES Y BRECHAS
- "De cada 100 escenarios simulados, en X llegas a tu meta" es SOLO para una
  simulación real. Un ratio, un IRFI, un ICA o cualquier otra cifra de la base
  es un DATO DIRECTO: no inventes un "cuántas veces se repite".
- Nunca inventes un promedio, fórmula o estadística: si no la tienes, di "no
  tengo ese detalle a la mano ahora mismo".
- Nunca inventes otra probabilidad: para otros ajustes remite al Simulador.
- Nunca digas "no calificas" ni "no puedes": di "todavía te falta X para llegar
  a Y".

LO QUE NO HACES
- No recomiendas bancos, marcas, acciones, criptomonedas ni crédito, ni montos
  para invertir o pedir prestado distintos a los de RESULTADO_CONSULTA.
- No predices si te aprobarán un crédito. No das consejo legal ni fiscal. No
  prometes resultados.
- Si algo queda fuera de tu alcance, dilo amablemente y ofrece lo que sí
  puedes: explicar un concepto, revisar tus números, armar un plan o
  interpretar tu simulación.

DATOS_DEL_USUARIO:
{contexto_perfil}

RESULTADO_CONSULTA (si aplica):
{resultado_consulta}

CONOCIMIENTO_DE_APOYO (si aplica):
{fragmentos_rag}
"""


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


# --- Clasificación -------------------------------------------------------------
def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        ch
        for ch in unicodedata.normalize("NFD", texto)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[\s\-]+", "_", sin_acentos.strip().upper())


def parsear_categoria(raw: str) -> str:
    """Devuelve la categoría que aparece PRIMERO en la respuesta del modelo
    (sin acentos, 'FUERA DE TEMA' vale), o CATEGORIA_FALLBACK si ninguna."""
    norm = _normalizar(raw)
    mejor, pos_mejor = None, None
    for categoria in CATEGORIAS_VALIDAS:
        i = norm.find(categoria)
        if i != -1 and (pos_mejor is None or i < pos_mejor):
            mejor, pos_mejor = categoria, i
    return mejor or CATEGORIA_FALLBACK


def clasificar_intencion(pregunta: str) -> str:
    por_regla = clasificar_por_reglas(pregunta)
    if por_regla:
        return por_regla
    base_url = get_required_env("OLLAMA_BASE_URL")
    response = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": CHAT_MODEL,
            "prompt": CLASIFICACION_PROMPT.format(pregunta=pregunta),
            "stream": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
        },
        timeout=OLLAMA_TIMEOUT_CLASIFICACION,
    )
    response.raise_for_status()
    return parsear_categoria(response.json()["response"])


# --- Chat ------------------------------------------------------------------------
def call_ollama_chat(
    system_prompt: str, historial: list[dict], pregunta: str
) -> tuple[str, dict]:
    """Devuelve (respuesta, métricas). `prompt_eval_count` = tokens que el
    modelo realmente leyó: si se acerca a NUM_CTX, el prompt se está
    recortando."""
    base_url = get_required_env("OLLAMA_BASE_URL")
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)  # [{"role": "user"|"assistant", "content": "..."}]
    messages.append({"role": "user", "content": pregunta})
    response = requests.post(
        f"{base_url}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": NUM_CTX},
        },
        timeout=OLLAMA_TIMEOUT_CHAT,
    )
    response.raise_for_status()
    data = response.json()
    metricas = {
        "prompt_eval_count": data.get("prompt_eval_count"),
        "eval_count": data.get("eval_count"),
        "num_ctx": NUM_CTX,
    }
    return data["message"]["content"], metricas


MENSAJE_SIN_CIFRA_FIABLE = (
    "No logré darte esa cifra con seguridad, y prefiero no inventarla. Puedes verla "
    "en la pantalla «Lo que tengo hoy», o pregúntame de otra forma y lo intento "
    "de nuevo."
)
MENSAJE_REFORMULAR = (
    "Prefiero responderte con más cuidado. ¿Me lo preguntas de otra forma? También "
    "puedes ver tus números en la pantalla «Lo que tengo hoy»."
)


def _frases(texto: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", texto.strip())


def quitar_frases_con_cifras(respuesta: str, cifras: list[str]) -> str:
    """Quita las frases que contienen alguna de las cifras dadas (texto original,
    p. ej. '$4,054'). Si no queda nada, devuelve MENSAJE_SIN_CIFRA_FIABLE."""
    sanas = [f for f in _frases(respuesta) if not any(c in f for c in cifras)]
    texto = " ".join(sanas).strip()
    return texto if len(texto) >= 20 else MENSAJE_SIN_CIFRA_FIABLE


def vr_cifras(
    respuesta: str, contexto: str, incluir_porcentajes: bool = False
) -> list[str]:
    """Por defecto solo dólares: un porcentaje derivado ("58%" a partir de "$58
    de cada $100") es inocuo; "$4,054" no. En SIMULACION también se vigilan los
    porcentajes, porque ahí un % es una PROBABILIDAD y no se puede inventar (visto:
    "la probabilidad de éxito fue de 74.2%" con un ajuste que nunca se simuló)."""
    return verificaciones_respuesta.cifras_sin_respaldo(
        respuesta, contexto, solo_dolares=not incluir_porcentajes
    )


def aplicar_guardrail(
    respuesta: str,
    contexto: str,
    regenerar,
    incluir_porcentajes: bool = False,
    permitidas: frozenset[str] = frozenset(),
) -> tuple[str, dict]:
    """Guardrail EN VIVO sobre la respuesta del modelo. Vigila 2 cosas:

    * MONTOS en dólares que no están en el contexto (inventados o restados por
      el modelo: "te falta $4,054" cuando eran $6,044; un pago de deuda de
      "$2,156" que no existe en ningún dato).
    * FRASES DE JUICIO o UMBRALES inventados para el IRFI/ICA ("tu deuda es un
      problema", "estás tomando un riesgo alto", "lo ideal sería llegar a $40
      de cada $100", cuando $40 es el TOPE y la persona tiene $17).

    1) Si hay algo de lo anterior, se regenera UNA vez con una corrección.
    2) Si el segundo intento todavía lo trae, se QUITAN las frases afectadas (o se
       usa un mensaje seguro si no queda nada).

    Nació del informe t082 (Sesión 36): en vez de seguir afinando el prompt, lo
    que el prompt no logra se corrige después de generar. `regenerar(nota)` debe
    devolver el texto de la nueva respuesta."""
    info = {
        "cifras_corregidas": {},
        "cifras_primer_intento": [],
        "frases_primer_intento": [],
        "reintento": False,
        "frases_quitadas": False,
    }
    # 0) Restas de redondeo ("$1,412" por $1,411): se corrigen sin regenerar ni
    #    quitar nada. En la corrida 3x esto habría salvado respuestas completas.
    respuesta, info["cifras_corregidas"] = (
        verificaciones_respuesta.reparar_montos_cercanos(respuesta, contexto)
    )
    cifras = vr_cifras(respuesta, contexto, incluir_porcentajes)
    juicio = verificaciones_respuesta.frases_de_juicio(respuesta, permitidas)
    if not cifras and not juicio:
        return respuesta, info
    info["cifras_primer_intento"], info["frases_primer_intento"] = cifras, juicio
    info["reintento"] = True

    partes = ["CORRECCIÓN IMPORTANTE: tu respuesta anterior tuvo problemas."]
    if cifras:
        partes.append(
            f"Usó cifras que NO están en los datos ({', '.join(cifras)}). Usa SOLO las "
            "cifras de DATOS_DEL_USUARIO y RESULTADO_CONSULTA, tal cual, sin sumar ni "
            "restar tú."
        )
    if juicio:
        partes.append(
            "Juzgó a la persona o inventó etiquetas (por ejemplo: «"
            + juicio[0][:80]
            + "»). Habla sin juzgar; del IRFI, el ICA y la salud usa SOLO la etiqueta "
            "oficial de DATOS_DEL_USUARIO; y de la deuda di 'lo manejable es hasta $40 "
            "de cada $100', nunca 'lo ideal'."
        )
    try:
        segunda = regenerar(" ".join(partes))
    except Exception as exc:  # si falla el reintento, se sanea el primero
        info["error_reintento"] = str(exc)
        segunda = respuesta
    segunda, _ = verificaciones_respuesta.reparar_montos_cercanos(segunda, contexto)
    cifras2 = vr_cifras(segunda, contexto, incluir_porcentajes)
    juicio2 = verificaciones_respuesta.frases_de_juicio(segunda, permitidas)
    if not cifras2 and not juicio2:
        return segunda, info

    info["frases_quitadas"] = True
    info["cifras_final"], info["frases_final"] = cifras2, juicio2
    sanas = [
        f
        for f in _frases(segunda)
        if not any(c in f for c in cifras2) and f not in juicio2
    ]
    texto = " ".join(sanas).strip()
    if len(texto) >= 20:
        return texto, info
    return (MENSAJE_SIN_CIFRA_FIABLE if cifras2 else MENSAJE_REFORMULAR), info


# Alias: nombre original (solo cifras), conservado para no romper pruebas ni
# llamadas previas. El comportamiento de cifras es el mismo.
aplicar_guardrail_cifras = aplicar_guardrail


def respuesta_que_pasaria_si(ultima_simulacion: str, nombre: str | None = None) -> str:
    """Respuesta FIJA (sin LLM) a "qué pasaría si ahorro X% más/menos": no se
    puede recalcular desde el chat; se manda al Simulador y se da como referencia
    el resultado REAL de la última corrida (que sí está en los datos)."""
    ajuste = re.search(r"Ajuste de ahorro aplicado: (-?\d+)%", ultima_simulacion)
    prob = re.search(r"Probabilidad de éxito: ([\d.]+)%", ultima_simulacion)
    alternativas = re.search(
        r"Alternativas calculadas: (.+?)\.(?: |$)", ultima_simulacion
    )
    referencia = ""
    if ajuste and prob:
        referencia = (
            f" Como referencia, tu última simulación usó un ajuste de ahorro de "
            f"{ajuste.group(1)}% y dio {prob.group(1)}% de probabilidad de llegar a tu meta."
        )
    if alternativas:  # el Simulador ya las corrió de verdad: se pueden citar
        referencia += (
            f" El Simulador ya calculó estas alternativas: {alternativas.group(1)}."
        )
    inicio = f"{nombre}, no" if nombre else "No"
    return (
        f"{inicio} puedo recalcular una simulación desde aquí, y prefiero no inventar "
        "un número. Para ver qué pasaría con otro ajuste de ahorro, mueve el control "
        "de ahorro en el Simulador (menú de la izquierda) y pulsa «Simular»."
        f"{referencia} ¿Quieres que te explique cómo leer el resultado cuando lo tengas?"
    )


def respuesta_sin_simulacion(nombre: str | None = None) -> str:
    """Respuesta FIJA (sin LLM) para preguntas de SIMULACION cuando el perfil
    activo no ha corrido ninguna. En la prueba real de la Sesión 36 el
    modelo de 8B, con el aviso solo en el prompt, no lo dijo: divagó, citó
    otro dato (la meta de ahorro mensual) o inventó un 60%. Es la misma
    filosofía del resto del router: lo que se puede decidir con código, no
    se le deja al modelo."""
    inicio = f"{nombre}, todavía" if nombre else "Todavía"
    return (
        f"{inicio} no has corrido ninguna simulación con este perfil, así que no "
        "tengo un resultado que explicarte. Puedes hacerlo en el Simulador, en el "
        "menú de la izquierda: elige una meta, ajusta el plazo y pulsa «Simular». "
        "Cuando la tengas, vuelve aquí y te ayudo a entender qué significa. "
        "¿Quieres que revisemos otra cosa mientras tanto, como tu plan para el "
        "colchón?"
    )


@dataclass
class RouterResult:
    respuesta: str
    categoria: str
    detalle_debug: dict = field(default_factory=dict)
    # Todo el texto que vio el modelo (prompt + pregunta + historial). Va
    # aparte de `detalle_debug` para no ensuciar el expander del Coach; lo
    # usan las verificaciones de `run_faq_tests_t082.py`.
    contexto: str = ""


def responder_chat(
    pregunta: str,
    cargado: "PerfilCargado",
    ultima_simulacion: str | None,
    historial: list[dict],
    nombre: str | None = None,
) -> RouterResult:
    """Punto de entrada único que llama `pages/2_Coach.py` por cada turno.
    `cargado` es el `PerfilCargado` del perfil activo (ya validado)."""
    historial = historial[-HISTORIAL_MAX_MENSAJES:]
    categoria = clasificar_intencion(pregunta)
    resultado_text = "(no aplica a esta pregunta)"
    fragmentos_text = "(no aplica a esta pregunta)"
    debug: dict = {
        "categoria": categoria,
        "nivel": cargado.plan.nivel,
        "mensajes_de_historial": len(historial),
    }

    if (
        categoria == "SIMULACION"
        and ultima_simulacion
        and es_pregunta_que_pasaria_si(pregunta)
    ):
        debug["sin_llm"] = "qué pasaría si: no se recalcula desde el chat"
        return RouterResult(
            respuesta=respuesta_que_pasaria_si(ultima_simulacion, nombre),
            categoria=categoria,
            detalle_debug=debug,
        )

    if categoria == "ROADMAP":
        debug["sin_llm"] = "roadmap armado por código (orden y cifras fijos)"
        return RouterResult(
            respuesta=ctx.respuesta_roadmap(cargado, nombre),
            categoria=categoria,
            detalle_debug=debug,
        )

    if categoria == "SIMULACION" and not ultima_simulacion:
        debug["sin_llm"] = "el perfil activo no ha corrido ninguna simulación"
        return RouterResult(
            respuesta=respuesta_sin_simulacion(nombre),
            categoria=categoria,
            detalle_debug=debug,
        )

    if categoria in ctx.CATEGORIAS_CON_BLOQUE_DE_CODIGO:
        try:
            resultado_text = ctx.bloque_de_codigo(categoria, cargado, pregunta)
        except Exception as exc:  # no tumbar el chat por un bloque
            resultado_text = (
                f"(no se pudieron calcular las cifras de esta consulta: {exc})"
            )
            debug["error_bloque"] = str(exc)

    elif categoria == "DATOS":
        # Consulta FIJA (consulta_grupo.py), no SQL generado por el modelo.
        try:
            resultado_text = consulta_grupo.bloque_datos(cargado)
        except Exception as exc:
            resultado_text = (
                f"(no se pudo consultar la comparación con el grupo: {exc}). "
                "Díselo con naturalidad; no inventes promedios."
            )
            debug["error_datos"] = str(exc)

    elif categoria == "CONCEPTOS":
        fragmentos = rag.buscar_fragmentos(pregunta)
        fragmentos_text = rag.formatear_para_prompt(fragmentos)
        debug["fragmentos"] = [(f["fuente"], round(f["score"], 3)) for f in fragmentos]

    elif categoria == "SIMULACION":
        # (Sin simulación ya se respondió arriba con texto fijo.)
        resultado_text = ctx.bloque_simulacion(ultima_simulacion)

    # FUERA_DE_TEMA: sin contexto extra — el System Prompt ("LO QUE NO
    # HACES") ya cubre cómo rechazar con amabilidad.

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        nombre_txt=(
            f"La persona con la que hablas se llama {nombre}; puedes llamarla por "
            "su nombre de vez en cuando, sin exagerar."
            if nombre
            else ""
        ),
        contexto_perfil=ctx.contexto_perfil(cargado, nombre),
        resultado_consulta=resultado_text,
        fragmentos_rag=fragmentos_text,
    )
    respuesta, metricas = call_ollama_chat(system_prompt, historial, pregunta)
    debug.update(metricas)
    # Cifras de la respuesta que no están en el contexto (inventos o restas del
    # modelo). Solo para depurar/medir; no cambia la respuesta.
    contexto_completo = " ".join(
        [system_prompt, pregunta] + [m["content"] for m in historial]
    )

    def _regenerar(nota: str) -> str:
        texto, _ = call_ollama_chat(system_prompt + "\n\n" + nota, historial, pregunta)
        return texto

    respuesta, info_guardrail = aplicar_guardrail(
        respuesta,
        contexto_completo,
        _regenerar,
        incluir_porcentajes=(categoria == "SIMULACION"),
        permitidas=indicadores.etiquetas_permitidas(cargado.irfi, cargado.ica),
    )
    debug["guardrail"] = info_guardrail
    # Lo que QUEDA después del guardrail (incluye porcentajes): para medir.
    debug["cifras_sin_respaldo"] = verificaciones_respuesta.cifras_sin_respaldo(
        respuesta, contexto_completo
    )
    debug["respuesta"] = respuesta

    return RouterResult(
        respuesta=respuesta,
        categoria=categoria,
        detalle_debug=debug,
        contexto=contexto_completo,
    )


if __name__ == "__main__":
    # Sanity check manual (no es un test formal; t082 hace la prueba
    # completa). Requiere Ollama, postgres-dw y knowledge_index.json.
    #   docker compose exec streamlit python -m assistant.router
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from perfil_loader import cargar_perfil  # noqa: E402
    from perfiles_sinteticos import ARQUETIPOS  # noqa: E402
    from simulator_engine import get_dw_connection  # noqa: E402

    # (pregunta, categorías aceptables). PERFIL y PLAN comparten bloque de
    # cifras, así que cualquiera de las dos es una respuesta correcta.
    CASOS = [
        ("¿Cuánto me queda cada mes?", {"PERFIL", "PLAN"}),
        ("¿Mi nivel de deuda respecto a mi ingreso es alto?", {"PERFIL"}),
        ("¿Cómo estoy frente al promedio de mi grupo?", {"DATOS"}),
        ("¿Qué es un fondo de emergencia?", {"CONCEPTOS"}),
        ("¿Qué significa mi probabilidad de llegar a la meta?", {"SIMULACION"}),
        ("¿Cuánto me falta para tener 3 meses cubiertos?", {"PLAN", "PERFIL"}),
        ("¿Cuánto tendría para el retiro si aporto $200 al mes?", {"PLAN"}),
        ("¿Qué tipo de producto me conviene para empezar?", {"PRODUCTO"}),
        ("¿Qué sigue después de mi colchón?", {"ROADMAP"}),
        ("¿Me van a aprobar un crédito?", {"FUERA_DE_TEMA"}),
        ("¿Qué banco me conviene?", {"FUERA_DE_TEMA"}),
        ("¿Por qué mi meta de renta es 2 veces mi gasto mensual?", {"CONCEPTOS"}),
    ]

    conn = get_dw_connection()
    try:
        perfiles = [(a, cargar_perfil(conn, a["record_id"])) for a in ARQUETIPOS]
    finally:
        conn.close()

    total = aciertos = 0
    max_tokens = 0
    for arquetipo, cargado in perfiles:
        print(f"\n=== {arquetipo['label']} (nivel {cargado.plan.nivel}) ===")
        for pregunta, esperadas in CASOS:
            r = responder_chat(
                pregunta, cargado, None, [], nombre=arquetipo.get("nombre")
            )
            ok = r.categoria in esperadas
            total += 1
            aciertos += ok
            tokens = r.detalle_debug.get("prompt_eval_count") or 0
            max_tokens = max(max_tokens, tokens)
            sin_respaldo = r.detalle_debug.get("cifras_sin_respaldo")
            if sin_respaldo:
                print(f"    AVISO cifras sin respaldo en el contexto: {sin_respaldo}")
            print(
                f"[{'OK' if ok else 'DISTINTA'}] {pregunta}\n"
                f"    categoría={r.categoria} (esperada: {'/'.join(sorted(esperadas))}) "
                f"· tokens del prompt={tokens}/{NUM_CTX}\n"
                f"    {r.respuesta[:200].replace(chr(10), ' ')}..."
            )
    print(f"\nCategoría aceptable: {aciertos}/{total}")
    print(f"Máximo de tokens del prompt: {max_tokens}/{NUM_CTX}")
    if max_tokens > NUM_CTX * 0.85:
        print("AVISO: el prompt roza el límite de contexto; súbelo o acórtalo.")
    sys.exit(0 if aciertos == total else 1)

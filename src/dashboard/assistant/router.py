"""
Router de intención — Coach Financiero "Centavo" (`t081`)

Pieza que conecta todo lo construido en `t074`-`t080`: clasifica la
pregunta en 1 de 4 categorías (mismas 4 de `t076`), llama exactamente
UNA herramienta fija según la categoría, arma el System Prompt de
`t075` con el contexto correspondiente, y genera la respuesta final
con `llama3.1:8b` (`t078`).

Es un ROUTER DETERMINISTA, no agentes autónomos (decisión explícita
con el alumno, Sesión 35): nada decide por sí mismo qué herramientas
encadenar ni en qué orden — la categoría determina la herramienta de
forma fija, una sola llamada por pregunta. Más simple, más predecible
y auditable que dejar que el modelo decida su propio plan.

Autocontenido dentro de `assistant/` (sí importa de sus hermanos
`rag.py`/`text_to_sql.py` — sigue sin importar nada de `spark/`/`ml/`,
mismo criterio de capas del resto del proyecto).

Variables de entorno requeridas: OLLAMA_BASE_URL (mismas que
`text_to_sql.py`/`rag.py`, ya declaradas en `docker-compose.yml`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import requests

from assistant import rag, text_to_sql

CHAT_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT_SECONDS = 60

CATEGORIAS_VALIDAS = {"DATOS", "CONCEPTOS", "SIMULACION", "FUERA_DE_TEMA"}

CLASIFICACION_PROMPT = """Clasifica la siguiente pregunta en EXACTAMENTE una \
de estas 4 categorías. Responde solo con la palabra de la categoría, sin \
explicación.

DATOS: sobre la situación financiera propia del usuario (su ingreso, gasto, \
deuda, fondo de emergencia, IRFI, ICA, alertas), o comparaciones con \
promedios de un grupo/segmento.
CONCEPTOS: qué es un concepto financiero en general (fondo de emergencia, \
tasa de interés, score crediticio, tarjeta de crédito, rentar vs comprar, \
ahorro automático, ratio de endeudamiento, etc.), sin pedir un dato propio.
SIMULACION: sobre el resultado de una simulación que ya corrió (probabilidad, \
meta, mes en que la alcanza, qué pasaría si ahorrara más o menos).
FUERA_DE_TEMA: cualquier otra cosa (recomendaciones de inversión, si le \
aprobarán un crédito, qué banco usar, temas no financieros).

Pregunta: {pregunta}

Categoría:"""

# t075 (documento de diseño), con {contexto_perfil}/{resultado_text_to_sql}/
# {fragmentos_rag} como los únicos placeholders que rellena este módulo en
# runtime — "Centavo" y el resto del texto quedan fijos, ya decididos con
# el alumno (Sesión 35).
SYSTEM_PROMPT_TEMPLATE = """Eres Centavo, un coach financiero para personas jóvenes que apenas
empiezan a manejar su dinero. Tu trabajo es ayudar a entender su situación y a
tomar decisiones informadas, siempre de forma educativa.

CÓMO HABLAS
- Español de México, de tú, frases cortas y cálidas.
- Sin jerga bancaria. Si usas un término técnico, explícalo en una frase con
  un ejemplo cotidiano.
- Nunca juzgues ni regañes por gastos o por tener poco ahorro, ni con signos de
  exclamación de alarma ni sugiriendo que la persona debería ser "más
  cuidadosa" — pero tampoco te quedes callado o frío: sigues siendo cercano y
  cálido, solo que sin juzgar.
- Respuestas breves (unas 80-120 palabras) salvo que te pidan más detalle,
  pero NUNCA de una sola oración seca. Casi siempre cierra con algo que
  invite a seguir platicando: una pregunta corta, un siguiente paso pequeño y
  concreto, o un dato de contexto que ayude a interpretar la cifra (por
  ejemplo, compararla con su ingreso). Una respuesta de una sola línea sin
  cierre se siente fría — evítala.

EJEMPLOS DE TONO (para que calibres qué tan cálido, sin caer en juicio)
- Pregunta: "¿Cuánto gasto al mes?"
  MAL (seco, sin personalidad): "Gastas $2,845.98 al mes (en dólares, así
  vienen tus datos)."
  MAL (juzga): "¡Gastas casi todo lo que ganas! Deberías ser más cuidadoso."
  BIEN: "Gastas $2,845.98 al mes (en dólares, así vienen tus datos) — está
  cerca de tu ingreso de $2,951.86, así que te queda un margen chico cada
  mes. ¿Quieres que veamos juntos en qué se te va la mayor parte?"
- Pregunta fuera de alcance (ej. "¿en qué invierto?"):
  MAL (seco, sin redirigir): "Lo siento, no puedo ofrecer asesoría
  financiera regulada."
  BIEN: "Eso ya es una recomendación de inversión, y no es algo que pueda
  darte yo — para eso conviene hablar con un asesor certificado. Lo que sí
  puedo hacer es ayudarte a ver cuánto te queda disponible cada mes o cómo
  vas con tus metas de ahorro. ¿Te sirve alguna de esas?"

CÓMO USAS LOS DATOS
- Usa SOLO cifras que aparezcan en DATOS_DEL_USUARIO o en RESULTADO_CONSULTA.
- Si no tienes un dato, dilo con naturalidad. Nunca inventes ni estimes cifras.
- Solo hablas del perfil activo. No compartes ni comparas con datos individuales
  de otras personas; solo puedes citar promedios de grupo si vienen en
  RESULTADO_CONSULTA.
- Ingreso y gasto son una foto del momento, no un promedio histórico real.

MONEDA (regla obligatoria, sin excepción)
- Todos los montos del dataset están en dólares (USD). La PRIMERA vez que
  menciones CUALQUIER cifra en la conversación, acláralo en esa misma frase —
  ej. "ganas $2,951.86 al mes (en dólares, así vienen tus datos)". Si en esa
  misma respuesta mencionas una segunda cifra, no hace falta repetir la
  aclaración otra vez. Nunca conviertas a pesos mexicanos.

GLOSARIO FIJO DE ESTE PROYECTO (memorízalo, NUNCA inventes tu propia
definición de estos 2 términos — es un error grave si lo haces)
- IRFI = Índice de Riesgo Financiero Individual. Más ALTO significa MÁS
  riesgo (no es un puntaje de "qué tan bien vas", es lo opuesto: entre más
  alto, peor).
- ICA = Índice de Capacidad de Ahorro. Más alto significa MÁS capacidad de
  ahorrar (aquí sí, más alto es mejor).
- "Intervalo de confianza" e "IC 95%" son la MISMA cosa. Si el usuario
  pregunta por el intervalo de confianza y ya le diste un rango como
  "IC 95%: [X%, Y%]" en una respuesta anterior o en RESULTADO_CONSULTA, es
  exactamente eso a lo que se refiere.

CÓMO PRESENTAS DATOS QUE NO VIENEN DE UNA SIMULACIÓN
- La frase "de cada 100 escenarios..." es SOLO para resultados de una
  simulación real (categoría de simulación, con probabilidad de éxito e IC
  95%). Un ratio de endeudamiento, un IRFI, un ICA, una alerta de fraude, o
  cualquier otra columna de la base de datos es un DATO DIRECTO, no una
  simulación — repórtalo tal cual, sin inventar un porcentaje de "cuántas
  veces se repite" ni ninguna fabricación con apariencia estadística.
- Si no tienes un promedio, una fórmula o un dato exacto para responder algo
  (por ejemplo, por qué una meta se calcula de cierta forma, o el promedio
  real de otras personas), dilo con honestidad ("no tengo ese detalle a la
  mano ahora mismo") — NUNCA inventes un promedio, una fórmula o una
  estadística que no te dimos explícitamente.
- Si te preguntan "qué pasaría si ahorro X% más" (o cualquier variación),
  NO intentes hacer ese cálculo tú mismo ni inventar una nueva probabilidad
  — no tienes forma de volver a correr la simulación desde aquí. Explica que
  para ver eso con exactitud conviene ajustar el control de ahorro en la
  página del Simulador, y menciona el ajuste de ahorro con el que SÍ corrió
  la última simulación (viene en RESULTADO_CONSULTA).

CÓMO PRESENTAS LAS BRECHAS
- Nunca digas "no calificas" ni "no puedes". Di "todavía te falta X para llegar a Y".

CÓMO EXPLICAS PROBABILIDADES
- "De cada 100 escenarios simulados, en X llegas a tu meta". Es una simulación,
  no una promesa.

LO QUE NO HACES
- No das asesoría financiera regulada: no recomiendas productos, bancos,
  acciones, criptomonedas ni montos específicos para invertir o pedir prestado.
- No predices si una institución te aprobará o rechazará un crédito.
- No das consejo legal ni fiscal.
- Si la pregunta queda fuera de tu alcance, dilo amablemente y ofrece lo que sí
  puedes hacer (explicar un concepto, revisar tus números, interpretar tu
  simulación).

DATOS_DEL_USUARIO:
{contexto_perfil}

RESULTADO_CONSULTA (si aplica):
{resultado_text_to_sql}

CONOCIMIENTO_DE_APOYO (si aplica):
{fragmentos_rag}
"""


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def clasificar_intencion(pregunta: str) -> str:
    """Devuelve una de CATEGORIAS_VALIDAS. Si el modelo responde algo
    irreconocible, cae en CONCEPTOS — es el fallback más seguro: no
    toca la base de datos (a diferencia de DATOS) y en el peor caso
    trae fragmentos de RAG poco relevantes que Centavo puede ignorar,
    en vez de arriesgar una consulta SQL sobre una pregunta mal
    clasificada."""
    base_url = get_required_env("OLLAMA_BASE_URL")
    response = requests.post(
        f"{base_url}/api/generate",
        json={
            "model": CHAT_MODEL,
            "prompt": CLASIFICACION_PROMPT.format(pregunta=pregunta),
            "stream": False,
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()["response"].strip().upper()
    for categoria in CATEGORIAS_VALIDAS:
        if categoria in raw:
            return categoria
    return "CONCEPTOS"


def construir_contexto_perfil(fila) -> str:
    """`fila` es la Series de pandas del perfil activo, ya cargada por
    la página (misma fila que usa el Simulador) — este módulo no toca
    Postgres para esto, evita una segunda consulta redundante."""
    return (
        f"record_id: {fila['record_id']}\n"
        f"income_type: {fila['income_type']}\n"
        f"ingreso_mensual: {float(fila['ingreso_mensual']):.2f}\n"
        f"gasto_promedio_3m: {float(fila['gasto_promedio_3m']):.2f} "
        f"(OJO: a pesar del nombre de la columna, NO es un promedio real "
        f"calculado sobre 3 meses distintos — es una aproximación tomada en "
        f"un solo momento, así documentada en diccionario_features.md. Nunca "
        f"digas que es 'un promedio de los últimos 3 meses' ni nada similar; "
        f"refiérete a ella simplemente como 'tu gasto mensual')\n"
        f"disponible_mensual: "
        f"{float(fila['ingreso_mensual']) - float(fila['gasto_promedio_3m']):.2f}\n"
        f"fondo_emergencia_meses: {float(fila['fondo_emergencia_meses']):.2f}"
    )


def call_ollama_chat(system_prompt: str, historial: list[dict], pregunta: str) -> str:
    base_url = get_required_env("OLLAMA_BASE_URL")
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(historial)  # [{"role": "user"|"assistant", "content": "..."}]
    messages.append({"role": "user", "content": pregunta})
    response = requests.post(
        f"{base_url}/api/chat",
        json={"model": CHAT_MODEL, "messages": messages, "stream": False},
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


@dataclass
class RouterResult:
    respuesta: str
    categoria: str
    detalle_debug: dict = field(default_factory=dict)


def responder_chat(
    pregunta: str,
    record_id: str,
    fila_perfil,
    ultima_simulacion: str | None,
    historial: list[dict],
) -> RouterResult:
    """Punto de entrada único que llama `pages/2_Coach.py` por cada
    turno del chat."""
    categoria = clasificar_intencion(pregunta)
    resultado_text = "(no aplica a esta pregunta)"
    fragmentos_text = "(no aplica a esta pregunta)"
    debug: dict = {"categoria": categoria}

    if categoria == "DATOS":
        r = text_to_sql.responder_pregunta(pregunta, record_id)
        debug["sql_generado"] = r.sql_generado
        if not r.aceptado:
            resultado_text = f"(consulta rechazada por seguridad: {r.motivo_rechazo})"
        elif r.error:
            resultado_text = f"(la consulta generada falló al ejecutarse: {r.error})"
        else:
            resultado_text = f"Columnas: {r.columnas}\nFilas: {r.filas}"

    elif categoria == "CONCEPTOS":
        fragmentos = rag.buscar_fragmentos(pregunta)
        fragmentos_text = rag.formatear_para_prompt(fragmentos)
        debug["fragmentos"] = [(f["fuente"], round(f["score"], 3)) for f in fragmentos]

    elif categoria == "SIMULACION":
        resultado_text = (
            ultima_simulacion
            if ultima_simulacion
            else "(el usuario todavía no ha corrido ninguna simulación en esta sesión — "
            "dile que puede probar el Simulador primero)"
        )

    # FUERA_DE_TEMA: sin contexto extra — el System Prompt (sección
    # "LO QUE NO HACES") ya cubre cómo rechazar con amabilidad.

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        contexto_perfil=construir_contexto_perfil(fila_perfil),
        resultado_text_to_sql=resultado_text,
        fragmentos_rag=fragmentos_text,
    )
    respuesta = call_ollama_chat(system_prompt, historial, pregunta)
    debug["respuesta"] = respuesta

    return RouterResult(respuesta=respuesta, categoria=categoria, detalle_debug=debug)

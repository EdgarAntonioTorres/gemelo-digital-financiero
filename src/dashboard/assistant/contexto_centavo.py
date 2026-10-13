"""
Contexto de Centavo v2 — bloques de texto armados por CÓDIGO (`t077` v2.3)

Todo lo que Centavo dice con cifras sale de aquí o de `plan_engine`: el
LLM (Llama 3.1 8B local) solo redacta. Este módulo convierte un perfil ya
cargado (`perfil_loader.PerfilCargado`) en los bloques que el router
inserta en el System Prompt:

  * `contexto_perfil()`     -> DATOS_DEL_USUARIO (siempre presente).
  * `bloque_de_codigo()`    -> RESULTADO_CONSULTA para las categorías PERFIL,
                               PLAN, PRODUCTO y ROADMAP (cada una, UNA
                               función fija y determinista).
  * `preguntas_sugeridas()` -> las preguntas de ejemplo por nivel (§8).

Código puro: sin Postgres, sin Ollama, sin Streamlit. Autocontenido en
`assistant/` (solo importa `plan_engine`, su hermano). `PerfilCargado` se
usa por duck typing (solo se leen sus atributos) para no invertir las
capas: `perfil_loader.py` vive un nivel arriba y ya importa de `assistant`.

Decisiones de diseño:

1. DATOS_DEL_USUARIO se incluye SIEMPRE, sea cual sea la categoría. Así,
   si el clasificador confunde dos categorías parecidas (PERFIL vs PLAN),
   las cifras siguen siendo correctas: son las mismas, calculadas por el
   mismo código. La categoría solo agrega bloques extra.
2. Cifras en dólares enteros ("$627"), no "626.83" (claridad, t077 §1.1.4).
   Los porcentajes se traducen ("de cada $100 que ganas, $58...").
3. Nunca se escribe en el contexto: `cash_flow_status`, `savings_rate`
   nativo, `financial_stress_level`, `financial_advice_score`, `category`,
   `date`, `loan_payment`, ni `essential`/`discretionary` como partes del
   gasto total (t077 §7). La proporción esencial va con su advertencia.
4. Retiro: la aportación y el plazo se extraen de la pregunta con regex
   (determinista). Si la persona no dice cuánto aporta, se usa lo que ya
   invierte; si tampoco invierte, NO se inventa un monto (pendiente 3 del
   handoff) y el bloque le indica al LLM que pregunte.
5. Productos: catálogo cerrado de `plan_engine.PRODUCTOS_POR_NIVEL`. Cada
   recomendación = tipo + razón con un dato del perfil + siguiente paso
   pequeño (t077 §4). Sin nombres comerciales, sin tasas, sin crédito.
6. Preguntas sugeridas del nivel 3: t077 §8 solo define las del nivel 1,
   el 2 y las comunes. Las del nivel 3 son [PROPUESTA] de esta versión.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from assistant import categorias_gasto as cg
from assistant import indicadores as ind
from assistant import plan_engine as pe

if TYPE_CHECKING:  # solo para anotaciones; evita invertir las capas
    from perfil_loader import PerfilCargado

CATEGORIAS_CON_BLOQUE_DE_CODIGO = ("PERFIL", "PLAN", "PRODUCTO", "ROADMAP")

_RE_RETIRO = re.compile(r"\b(retiro|jubilaci[oó]n|pensi[oó]n)\b", re.IGNORECASE)
_RE_ANIOS = re.compile(r"(\d{1,3})\s*a[ñn]os?", re.IGNORECASE)
# Número con o sin comas/decimales; no cuenta un porcentaje ("10%").
_RE_NUMERO = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?!\s*%)(?!\d)")


# --- Formato -----------------------------------------------------------------
def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _meses_txt(n: int | None) -> str:
    if n is None:
        return "no se puede estimar con el ahorro de hoy"
    if n == 0:
        return "ya cumplido"
    return "1 mes" if n == 1 else f"unos {n} meses"


def _fondo_txt(meses: float) -> str:
    if math.isinf(meses):
        return "sin gasto registrado"
    if meses < 1:
        return f"{meses:.2f} meses de gasto (unos {meses * 30:.0f} días)"
    return f"{meses:.2f} meses de gasto"


# --- DATOS_DEL_USUARIO -------------------------------------------------------
def contexto_perfil(c: "PerfilCargado", nombre: str | None = None) -> str:
    """Bloque DATOS_DEL_USUARIO. Siempre presente (decisión 1)."""
    p, plan, d = c.perfil, c.plan, c.detalle
    lineas = []
    if nombre:
        lineas.append(f"Nombre de la persona: {nombre}.")
    lineas.append(f"Nivel de madurez financiera: {plan.nivel} ({plan.nombre_nivel}).")
    lineas.append(f"Tipo de ingreso: {c.comportamiento['income_type']}.")
    lineas.append(f"Ingreso mensual: {_usd(p.ingreso_mensual)}.")
    lineas.append(
        f"Gasto mensual: {_usd(p.gasto_mensual)} (foto de un momento; no es un "
        "promedio de 3 meses: llámalo 'tu gasto mensual')."
    )
    if p.gasto_mensual > p.ingreso_mensual:
        lineas.append(
            f"Gasta {_usd(p.gasto_mensual - p.ingreso_mensual)} más de lo que gana; "
            "ahorro del mes: $0."
        )
    else:
        lineas.append(
            f"Ahorro del mes: {_usd(p.ahorro_mes)} "
            f"({p.ahorro_mes / p.ingreso_mensual * 100:.0f}% del ingreso)."
        )
    if plan.progreso_meta is not None:
        if plan.meta_cumplida:
            lineas.append(
                f"Meta de ahorro mensual: {_usd(p.meta_ahorro_mensual)}. Ya la cumplió."
            )
        else:
            lineas.append(
                f"Meta de ahorro mensual: {_usd(p.meta_ahorro_mensual)}. Lleva "
                f"{plan.progreso_meta * 100:.0f}%; le faltan "
                f"{_usd(plan.falta_meta_mensual)} al mes."
            )
    colchon_ok = plan.fondo_meses >= pe.MESES_COLCHON_MINIMO
    lineas.append(
        f"Fondo de emergencia: {_usd(p.fondo_emergencia_usd)} ({_fondo_txt(plan.fondo_meses)}). "
        + (
            f"Ya cubre {pe.MESES_COLCHON_MINIMO} meses o más."
            if colchon_ok
            else f"Todavía no llega a {pe.MESES_COLCHON_MINIMO} meses."
        )
    )
    deuda_ok = p.ratio_endeudamiento <= pe.UMBRAL_ENDEUDAMIENTO_MANEJABLE
    lineas.append(
        f"Deuda: de cada $100 que gana, ${plan.de_cada_100_a_deuda:.0f} van a pagar "
        f"deudas (ratio de endeudamiento {p.ratio_endeudamiento:.2f}; lo manejable "
        f"es hasta {pe.UMBRAL_ENDEUDAMIENTO_MANEJABLE:.2f}). "
        + (
            "Está DENTRO de lo manejable: no la describas como alta."
            if deuda_ok
            else "Está POR ENCIMA de lo manejable."
        )
    )
    # Valor + ETIQUETA OFICIAL + rango, desde la fuente única (indicadores.py): la
    # pantalla y Centavo dicen lo mismo.
    lineas.extend(ind.lineas_para_centavo(c.irfi, c.ica))
    lineas.append(f"Inversión mensual actual: {_usd(p.inversion_mensual)}.")
    lineas.append(f"Suscripciones activas: {int(d['suscripciones_activas'])}.")
    desglose = cg.desde_detalle(p, d)
    if desglose is not None:
        lineas.append(_linea_categorias(desglose))
    else:  # migración de categorías sin correr: solo la proporción
        lineas.append(
            f"Proporción de gasto esencial: {float(d['proporcion_esencial']) * 100:.0f}% "
            "(es una proporción entre gastos esenciales y de gusto; NO es el desglose "
            "del gasto total, no la sumes con nada)."
        )
    return "\n".join(lineas)


def _linea_categorias(g: "cg.DesgloseGasto") -> str:
    """Categorías de gasto. Las declara la fuente; no hay comida, transporte ni
    restaurantes (ver categorias_gasto.py)."""
    texto = (
        "Gasto por categoría (lo declara la fuente; NO existen categorías como comida, "
        f"transporte o restaurantes): vivienda {_usd(g.vivienda)}"
    )
    if g.vivienda_pct_ingreso is not None:
        texto += f" ({g.vivienda_pct_ingreso * 100:.0f}% del ingreso)"
    texto += f"; otros gastos básicos {_usd(g.otros_basicos)}; gastos flexibles {_usd(g.flexibles)}"
    if g.cuadra_con_el_total:
        if g.sin_categorizar > 0:
            texto += (
                f"; sin categorizar {_usd(g.sin_categorizar)} "
                f"({g.sin_categorizar / g.gasto_total * 100:.0f}% del gasto total)"
            )
        texto += "."
    else:
        texto += (
            f". Las categorías suman {_usd(g.categorizado)}, {_usd(g.exceso)} más que el "
            f"gasto total ({_usd(g.gasto_total)}): trátalas como proporciones, no como "
            "partes del total."
        )
    return texto


# --- Retiro ------------------------------------------------------------------
def menciona_retiro(pregunta: str) -> bool:
    return bool(_RE_RETIRO.search(pregunta))


def extraer_supuestos_retiro(
    pregunta: str, referencia: float
) -> tuple[pe.SupuestosRetiro | None, list[str]]:
    """Aportación y plazo de la pregunta (regex). Devuelve (supuestos, notas).
    `supuestos` es None si no hay ninguna aportación posible (ni dicha ni
    de referencia): nunca se inventa un monto."""
    notas: list[str] = []
    anios = pe.RETIRO_ANIOS_DEFAULT
    texto = pregunta
    m = _RE_ANIOS.search(texto)
    if m:
        pedido = int(m.group(1))
        if pe.RETIRO_ANIOS_MIN <= pedido <= pe.RETIRO_ANIOS_MAX:
            anios = pedido
        else:
            notas.append(
                f"La persona pidió {pedido} años, fuera del rango permitido "
                f"({pe.RETIRO_ANIOS_MIN} a {pe.RETIRO_ANIOS_MAX}); se usó {anios}. "
                "Díselo con naturalidad."
            )
        texto = texto[: m.start()] + " " + texto[m.end() :]

    aportacion = None
    origen = ""
    m2 = _RE_NUMERO.search(texto)
    if m2:
        valor = float(m2.group(1).replace(",", "") + (m2.group(2) or ""))
        if valor > 0:
            aportacion, origen = valor, "la cantidad que mencionó la persona"
    if aportacion is None and referencia > 0:
        aportacion, origen = referencia, "lo que la persona ya aporta hoy"
    if aportacion is None:
        return None, notas
    notas.append(f"Origen de la aportación: {origen}.")
    return pe.SupuestosRetiro(aportacion_mensual=aportacion, anios=anios), notas


def bloque_retiro(c: "PerfilCargado", pregunta: str, obligatorio: bool) -> str:
    """Proyección de retiro lista para el prompt. Si no hay aportación y
    `obligatorio` es False devuelve "" (el bloque simplemente no aplica)."""
    supuestos, notas = extraer_supuestos_retiro(pregunta, c.perfil.inversion_mensual)
    if supuestos is None:
        if not obligatorio:
            return ""
        return (
            "PROYECCIÓN DE RETIRO: no hay una aportación de referencia (la persona "
            "no dijo cuánto y hoy no invierte). NO inventes un monto: pregúntale "
            "cuánto le gustaría aportar al mes y ofrécele proyectarlo. "
            + " ".join(notas)
        ).strip()
    proyeccion = pe.proyectar_retiro(supuestos)
    notas.append(
        "Al decir 'rendimiento', explícalo en la misma frase: es lo que se supone "
        "que gana tu dinero cada año, ya descontando la inflación."
    )
    return "\n".join(notas + [pe.contexto_retiro_para_prompt(proyeccion)])


# --- Productos ---------------------------------------------------------------
def bloque_productos(c: "PerfilCargado") -> str:
    """Tipo de producto + razón con un dato + siguiente paso pequeño (§4)."""
    plan, p, col = c.plan, c.perfil, c.plan.colchon
    deuda = f"de cada $100 que gana, ${plan.de_cada_100_a_deuda:.0f} van a pagar deudas"
    fondo = f"su fondo cubre {_fondo_txt(plan.fondo_meses)}"
    colchon = (
        f"colchón de {col.meses_objetivo} meses: le faltan {_usd(col.brecha)}; "
        f"destinando {_usd(col.aporte_mensual)} al mes llegaría en "
        f"{_meses_txt(col.meses_estimados)}"
    )
    lineas = [
        "RECOMENDACIÓN DE TIPOS DE PRODUCTO (estructura armada por código; "
        "redáctala con tus palabras, sin cambiar cifras ni agregar productos):"
    ]
    if plan.nivel == 1:
        lineas += [
            f"1. Tipo: cuenta de ahorro. Razón: {fondo}; una cuenta aparte para el "
            "colchón ayuda a no gastarlo sin querer (no afirmes que hoy lo tiene "
            "mezclado: no lo sabemos). Siguiente paso: abrir o separar una cuenta "
            "solo para el colchón.",
            f"2. Tipo: ahorro programado. Razón: hoy ahorra {_usd(p.ahorro_mes)} al "
            "mes; programarlo hace que se aparte el día que cobra, antes de gastarlo. "
            f"Siguiente paso: programar {_usd(col.aporte_mensual)} al mes ({colchon}).",
            f"Contexto: {deuda}. En este nivel NO recomiendes inversión ni retiro "
            "todavía: primero conviene ordenar la deuda y juntar un primer colchón.",
        ]
    elif plan.nivel == 2:
        ref = plan.aporte_paralelo_referencia
        monto = (
            f"como referencia, {_usd(ref)} al mes, que es lo que ya aporta"
            if ref is not None
            else "no hay un monto de referencia: NO inventes uno; pregúntale cuánto "
            "le gustaría aportar"
        )
        lineas += [
            f"1. Tipo: ahorro programado (prioridad: el colchón). Razón: {fondo} y "
            f"la meta es {pe.MESES_COLCHON_MINIMO} meses. Siguiente paso: programar "
            f"{_usd(col.aporte_mensual)} al mes ({colchon}).",
            "2. Tipo: inversión de bajo riesgo (en paralelo, con un monto pequeño). "
            f"Razón: sus deudas están manejables ({deuda}). Siguiente paso: monto "
            f"pequeño: {monto}.",
            "3. Tipo: ahorro para el retiro (en paralelo, con un monto pequeño). "
            "Razón: entre más temprano empieza, más tiempo trabaja su dinero a su "
            "favor. Siguiente paso: usar ese mismo monto de referencia y ver la "
            "proyección.",
            "Contexto: el colchón sigue siendo la prioridad; inversión y retiro "
            "van en paralelo y en pequeño, no en lugar del colchón.",
        ]
    else:
        lineas += [
            f"1. Tipo: inversión de bajo riesgo (foco). Razón: sus deudas están "
            f"manejables ({deuda}) y {fondo}. Siguiente paso: decidir cuánto de su "
            f"ahorro del mes ({_usd(p.ahorro_mes)}) destinar a esto.",
            "2. Tipo: ahorro para el retiro (foco). Razón: entre más temprano "
            "empieza, más tiempo trabaja su dinero a su favor. Siguiente paso: ver "
            "la proyección con una aportación mensual.",
            "Contexto: el colchón de 3 a 6 meses sigue en marcha.",
        ]
    lineas.append(
        "Reglas: no nombres bancos ni marcas; no menciones tasas ni rendimientos de "
        "estos productos; no recomiendes crédito."
    )
    return "\n".join(lineas)


# --- Bloque por categoría ----------------------------------------------------
def _estado_meta(c: "PerfilCargado") -> str:
    if c.plan.meta_cumplida:
        return (
            "Meta de ahorro mensual: CUMPLIDA. Reconoce el logro con calidez y "
            "presenta el roadmap como los siguientes retos."
        )
    return (
        "Meta de ahorro mensual: todavía NO cumplida. Presenta el roadmap como "
        "'esto es lo que viene', no como una celebración."
    )


def _estado_colchon(c: "PerfilCargado") -> str:
    """Estado del primer peldaño del roadmap. En la primera corrida real el
    modelo respondió 'ya tienes un colchón de 3 meses' a una persona con
    0.53 meses, porque la pregunta lo daba por hecho."""
    col = c.plan.colchon
    if col.cumplido:
        return f"Colchón de {col.meses_objetivo} meses: ya está completo."
    return (
        f"Colchón de {col.meses_objetivo} meses: todavía NO está completo (le faltan "
        f"{_usd(col.brecha)}). NO digas que ya lo tiene: es el primer peldaño y "
        "sigue pendiente. Si la pregunta supone que ya lo completó, corrígelo con "
        "amabilidad. No confundas la 'meta de ahorro mensual' (cuánto ahorra cada "
        "mes) con el 'colchón' (fondo de emergencia acumulado): son cosas distintas "
        "y sus porcentajes no son los mismos."
    )


# --- SIMULACION ---------------------------------------------------------------
def bloque_simulacion(texto_simulacion: str) -> str:
    """RESULTADO_CONSULTA de SIMULACION: el texto de la corrida + cómo
    explicarlo. En la prueba real el modelo explicó el IC 95% como 'una
    posibilidad en 20 de que no llegues a tu meta', que es FALSO; el
    intervalo mide la estabilidad del porcentaje (ver simulator_engine.py)."""
    return (
        "ÚLTIMA SIMULACIÓN DE ESTA PERSONA (viene del Simulador):\n"
        f"{texto_simulacion}\n"
        "CÓMO EXPLICARLA (usa esto; no inventes otra explicación):\n"
        "- La probabilidad se lee 'de cada 100 escenarios simulados, en X llegas a "
        "tu meta'. Es una simulación, no una promesa.\n"
        "- El IC 95% (intervalo de confianza) dice qué tan estable es ese "
        "porcentaje: si repitiéramos la simulación muchas veces, casi siempre "
        "caería dentro de ese rango. NO significa 'una posibilidad en 20 de "
        "fallar' ni nada parecido.\n"
        "- 'Mes en que se alcanza (mediana)': entre los escenarios en que sí se "
        "llega a la meta, la mitad la alcanza en ese mes o antes.\n"
        "- Para ver 'qué pasaría si ahorro más o menos', se mueve el control de "
        "ahorro en el Simulador."
    )


def bloque_de_codigo(categoria: str, c: "PerfilCargado", pregunta: str) -> str:
    """RESULTADO_CONSULTA de las categorías que se resuelven con código.
    Una función fija por categoría; ninguna llama a Postgres ni al LLM."""
    if categoria == "PERFIL":
        return pe.contexto_plan_para_prompt(c.plan)
    if categoria == "PLAN":
        partes = [pe.contexto_plan_para_prompt(c.plan)]
        desglose = cg.desde_detalle(c.perfil, c.detalle)
        if desglose is not None and desglose.flexibles > 0:
            partes.append(
                "EJEMPLO DE AHORRO (aritmética de un 'si', no una estadística): si "
                "recortara 10% de sus gastos flexibles, ahorraría "
                f"{_usd(desglose.recorte_ilustrativo(0.10))} al mes. Para reducir gastos "
                "habla de los gastos flexibles y de las suscripciones (no hay más "
                "categorías); no prometas que ese recorte sea fácil."
            )
        if menciona_retiro(pregunta):
            partes.append(bloque_retiro(c, pregunta, obligatorio=True))
        return "\n\n".join(partes)
    if categoria == "PRODUCTO":
        partes = [bloque_productos(c)]
        if c.plan.nivel >= 2:
            retiro = bloque_retiro(c, pregunta, obligatorio=menciona_retiro(pregunta))
            if retiro:
                partes.append(retiro)
        return "\n\n".join(partes)
    if categoria == "ROADMAP":
        partes = [
            pe.contexto_plan_para_prompt(c.plan),
            _estado_meta(c),
            _estado_colchon(c),
        ]
        retiro = bloque_retiro(c, pregunta, obligatorio=False)
        if retiro:
            partes.append(retiro)
        return "\n\n".join(partes)
    raise ValueError(f"La categoría {categoria!r} no se resuelve con código.")


# --- Roadmap armado por código ------------------------------------------------
def respuesta_roadmap(c: "PerfilCargado", nombre: str | None = None) -> str:
    """Respuesta FIJA (sin LLM) a "¿qué sigue?". En la corrida real de la
    Sesión 36 el modelo de 8B no presentó el roadmap en orden en ninguna de
    las 2 respuestas (habló de 'ahorro programado' en general, o dijo 'después
    de tu colchón... que te faltan $6,044'). Es una escalera con cifras y
    orden fijos: mejor que la redacte el código. Un peldaño a la vez (t077 §6):
    el primero pendiente en detalle, el siguiente apenas mencionado."""
    plan = c.plan
    pendientes = [p for p in plan.roadmap if not p.cumplido]
    inicio = f"{nombre}, este" if nombre else "Este"
    if plan.meta_cumplida:
        inicio = "Ya cumpliste tu meta de ahorro mensual. " + inicio
    if not pendientes:
        return (
            f"{inicio} es tu camino, y ya completaste todos sus pasos. "
            "¿Quieres que veamos cómo seguir haciendo crecer tu ahorro?"
        )
    primero = pendientes[0]
    partes = [f"{inicio} es tu camino, un paso a la vez."]
    if primero.monto_objetivo is not None:
        detalle = (
            f"Primero: {primero.titulo.lower()}. Tu objetivo es "
            f"{_usd(primero.monto_objetivo)} (en dólares, así vienen tus datos) y "
            f"te faltan {_usd(primero.brecha or 0)}."
        )
        if primero.meses_estimados is not None:
            detalle += (
                f" Si destinas {_usd(plan.colchon.aporte_mensual)} al mes, "
                f"llegarías en {_meses_txt(primero.meses_estimados)}."
            )
        else:
            detalle += " Con el ahorro de hoy no se puede estimar cuándo llegarías."
        partes.append(detalle)
    else:  # el primer pendiente es el retiro
        partes.append(
            f"Primero: {primero.titulo.lower()}. {primero.razon} "
            "Cuando quieras, te ayudo a proyectarlo con una aportación al mes."
        )
    if len(pendientes) > 1:
        siguiente = pendientes[1]
        if siguiente.monto_objetivo is not None:
            partes.append(
                f"Después: {siguiente.titulo.lower()}, con un objetivo de "
                f"{_usd(siguiente.monto_objetivo)}."
            )
        else:
            partes.append(
                f"Más adelante: {siguiente.titulo.lower()}. {siguiente.razon}"
            )
    if len(pendientes) > 2:
        partes.append(
            f"Y al final: {pendientes[2].titulo.lower()}. {pendientes[2].razon}"
        )
    partes.append("¿Quieres que veamos cómo avanzar con el primer paso?")
    return " ".join(partes)


# --- Preguntas sugeridas (§8) ------------------------------------------------
def preguntas_sugeridas(c: "PerfilCargado") -> list[str]:
    """Preguntas de ejemplo para abrir el chat, según el nivel. Las comunes
    van al final. Ninguna lleva un monto inventado: el de retiro usa lo que
    la persona ya invierte, o se omite si invierte $0."""
    nivel, p = c.plan.nivel, c.perfil
    if nivel == 1:
        propias = [
            "¿Qué es un fondo de emergencia?",
            "¿Qué tan pesada es mi deuda?",
            "¿Cómo puedo bajar mi deuda?",
            "¿Cómo empiezo a ahorrar un poco cada mes?",
        ]
    elif nivel == 2:
        propias = [
            "¿Cuánto me falta para tener 3 meses cubiertos?",
            "¿Puedo empezar a invertir un poco sin descuidar mi colchón?",
            "¿En qué puedo reducir gastos?",
        ]
        if p.inversion_mensual > 0:
            propias.insert(
                2,
                "¿Cuánto tendría para el retiro si aporto "
                f"{_usd(p.inversion_mensual)} al mes?",
            )
    else:  # nivel 3: [PROPUESTA], t077 §8 no lo define
        propias = [
            "¿Cuánto me falta para llegar a 6 meses de colchón?",
            "¿Cómo empiezo a invertir con poco riesgo?",
            "¿Qué sigue después de mi colchón?",
        ]
    return propias + ["¿Cuánto me queda cada mes?", "¿Cómo voy con mi meta de ahorro?"]

"""
Motor de planes — Coach Financiero "Centavo" (`t077` v2.3)

Calcula TODAS las cifras que Centavo le dice a la persona: nivel de
madurez financiera, brechas, aportaciones, plazos, roadmap y proyección
de retiro. El LLM (Llama 3.1 8B local) no calcula ni estima nada: solo
redacta, con el registro claro de `t077` §1.1, los bloques de texto que
produce este módulo. Es la mitigación arquitectónica del piso de
alucinación documentado en `t082`.

Código 100% determinista y sin efectos: no toca Postgres, no llama a
Ollama, no depende de Streamlit. Solo biblioteca estándar. Recibe un
`PerfilFinanciero` y devuelve dataclasses inmutables. Funciona con
cualquier perfil que traiga las columnas necesarias (la lógica es
general; la app usa los 2 perfiles de Ana).

Autocontenido a propósito (mismo criterio que `simulator_engine.py`,
`t067`, y `text_to_sql.py`, `t079`): no importa nada de `src/spark/` ni
`src/ml/`. Vive en `src/dashboard/assistant/` porque el contenedor de
Streamlit solo copia `src/dashboard/` (`Dockerfile.streamlit`).

Umbrales: los 2 que ya existen en `glosario_educativo.md` (colchón de
3 meses, 6 meses como extremo alto del benchmark; endeudamiento
manejable hasta 0.40). No se inventó ninguno.

Supuestos de implementación (visibles a propósito, para revisión):
  S1. `meta_ahorro_mensual` es `budget_goal` de Silver PFT y se
      comporta como una meta de ahorro MENSUAL (inferencia por la regla
      `savings_goal_met == (actual_savings >= budget_goal)`, verificada
      en las 3,000 filas).
  S2. Nivel 2: la aportación "en paralelo" a inversión/retiro toma como
      referencia lo que el perfil ya aporta (`inversion_mensual`), sin
      inventar un porcentaje. Se asume que sale del ahorro del mes, por
      lo que el plazo del colchón se calcula con el ahorro restante.
  S3. La brecha de deuda usa la definición del glosario: el ratio de
      endeudamiento es la parte del ingreso que se va en pagar deudas;
      la brecha es cuánto bajarían esos pagos para llegar al tope de
      0.40. No hay saldos de deuda en el dataset.
      `PlanFinanciero.brecha_deuda_mensual` se calcula pero NO se incluye
      en el texto del prompt: el ratio de PFT es independiente de
      `loan_payment` (correlación -0.007, Sesión 36), así que un monto
      en USD derivado del ratio contradiría ese campo; t077 v2.3 §7
      aprueba mostrar solo el ratio. Incluirlo requiere una decisión.
  S4. Retiro: aportaciones al final de cada mes, capitalización mensual
      con la tasa mensual equivalente a la anual efectiva. El
      rendimiento es REAL (descuenta inflación, 6.0% validado por el
      mentor): el resultado está en dólares de hoy. Plazo: de 10 a 40
      años, 30 por defecto (aprobado por el alumno, Sesión 36; es un
      número redondo ilustrativo, sin respaldo en datos).
  S6. `PerfilFinanciero.desde_filas()` reverifica en tiempo de ejecución
      que `gold.fact_comportamiento` y `gold.fact_perfil_detalle`
      describan a la misma persona (misma "huella" que
      `config/create-fact-perfil-detalle.sql`): `record_id` se genera
      con `zipWithIndex`, que no garantiza el mismo orden entre corridas
      del pipeline, y es preferible un error explícito a hablarle a
      alguien con los datos de otra persona.
  S5. Los plazos se cuentan en meses completos hacia arriba y desde
      hoy (no acumulados entre peldaños del roadmap).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- Umbrales del proyecto (glosario_educativo.md) -------------------------
UMBRAL_ENDEUDAMIENTO_MANEJABLE = 0.40
MESES_COLCHON_MINIMO = 3
MESES_COLCHON_AMPLIO = 6

# Validado por el mentor (t077 v2.3, decisión 9). Siempre se presenta como
# estimado ilustrativo, no garantizado, y es configurable por llamada.
RENDIMIENTO_REAL_ANUAL_DEFAULT = 0.06
RETIRO_ANIOS_MIN = 10
RETIRO_ANIOS_MAX = 40
RETIRO_ANIOS_DEFAULT = 30

# Tolerancia para comparar montos que Gold guarda con 2 decimales.
TOLERANCIA_MONTO = 0.011

NOMBRES_NIVEL = {1: "Primeros pasos", 2: "Construyendo base", 3: "Creciendo"}

# Catálogo cerrado de tipos genéricos (t077 §4). Sin crédito en esta versión.
PRODUCTOS_POR_NIVEL = {
    1: ("cuenta de ahorro", "ahorro programado"),
    2: ("ahorro programado", "inversión de bajo riesgo", "ahorro para el retiro"),
    3: ("inversión de bajo riesgo", "ahorro para el retiro"),
}


class PerfilIncoherenteError(ValueError):
    """Las filas de Gold no describen un perfil coherente (por ejemplo,
    `record_id` desalineados entre tablas tras re-correr el pipeline)."""


# --- Entrada ---------------------------------------------------------------
@dataclass(frozen=True)
class PerfilFinanciero:
    """Datos mínimos de un perfil. Mapeo a Silver/Gold PFT:
    ingreso_mensual=monthly_income, gasto_mensual=monthly_expense_total,
    ratio_endeudamiento=debt_to_income_ratio, fondo_emergencia_usd=
    emergency_fund, meta_ahorro_mensual=budget_goal, meta_cumplida=
    savings_goal_met, inversion_mensual=investment_amount."""

    ingreso_mensual: float
    gasto_mensual: float
    ratio_endeudamiento: float
    fondo_emergencia_usd: float
    meta_ahorro_mensual: float
    meta_cumplida: bool
    inversion_mensual: float = 0.0
    record_id: str = ""

    def __post_init__(self) -> None:
        if self.ingreso_mensual <= 0:
            raise ValueError("ingreso_mensual debe ser > 0")
        for nombre in (
            "gasto_mensual",
            "ratio_endeudamiento",
            "fondo_emergencia_usd",
            "meta_ahorro_mensual",
            "inversion_mensual",
        ):
            if getattr(self, nombre) < 0:
                raise ValueError(f"{nombre} no puede ser negativo")

    @property
    def ahorro_mes(self) -> float:
        """max(0, ingreso - gasto). Verificado en las 3,000 filas de
        Silver PFT contra `actual_savings` (0 filas violan la regla)."""
        return max(0.0, self.ingreso_mensual - self.gasto_mensual)

    @property
    def fondo_meses(self) -> float:
        if self.gasto_mensual <= 0:
            return math.inf
        return self.fondo_emergencia_usd / self.gasto_mensual

    @property
    def progreso_meta(self) -> float | None:
        if self.meta_ahorro_mensual <= 0:
            return None
        return self.ahorro_mes / self.meta_ahorro_mensual

    @property
    def falta_meta_mensual(self) -> float:
        return max(0.0, self.meta_ahorro_mensual - self.ahorro_mes)

    @classmethod
    def desde_filas(cls, comportamiento, detalle) -> "PerfilFinanciero":
        """Arma el perfil desde una fila de `gold.fact_comportamiento` y una
        de `gold.fact_perfil_detalle` (dict o pandas.Series). Lanza
        `PerfilIncoherenteError` si no describen a la misma persona (S6)."""
        record_id = str(comportamiento["record_id"])
        if str(detalle["record_id"]) != record_id:
            raise PerfilIncoherenteError(
                f"record_id distintos: {record_id!r} vs {str(detalle['record_id'])!r}."
            )
        perfil = cls(
            ingreso_mensual=float(comportamiento["ingreso_mensual"]),
            gasto_mensual=float(comportamiento["gasto_promedio_3m"]),
            ratio_endeudamiento=float(comportamiento["ratio_endeudamiento"]),
            fondo_emergencia_usd=float(detalle["fondo_emergencia_usd"]),
            meta_ahorro_mensual=float(detalle["meta_ahorro_mensual"]),
            meta_cumplida=bool(detalle["meta_ahorro_cumplida"]),
            inversion_mensual=float(detalle["inversion_mensual"]),
            record_id=record_id,
        )
        ahorro_detalle = float(detalle["ahorro_del_mes"])
        if abs(ahorro_detalle - perfil.ahorro_mes) > TOLERANCIA_MONTO:
            raise PerfilIncoherenteError(
                f"{record_id}: ahorro_del_mes ({ahorro_detalle:.2f}) no coincide con "
                f"max(0, ingreso - gasto) ({perfil.ahorro_mes:.2f}). Los record_id pueden "
                "haberse desalineado tras re-correr el pipeline de Gold."
            )
        fondo_meses_gold = float(comportamiento["fondo_emergencia_meses"])
        if (
            abs(fondo_meses_gold * perfil.gasto_mensual - perfil.fondo_emergencia_usd)
            > TOLERANCIA_MONTO
        ):
            raise PerfilIncoherenteError(
                f"{record_id}: el fondo en USD del detalle ({perfil.fondo_emergencia_usd:.2f}) "
                f"no coincide con fondo_emergencia_meses x gasto "
                f"({fondo_meses_gold * perfil.gasto_mensual:.2f})."
            )
        if perfil.meta_cumplida != (perfil.ahorro_mes >= perfil.meta_ahorro_mensual):
            raise PerfilIncoherenteError(
                f"{record_id}: meta_ahorro_cumplida contradice "
                "ahorro_del_mes >= meta_ahorro_mensual."
            )
        return perfil


# --- Nivel de madurez financiera (t077 §1.2) -------------------------------
def calcular_nivel(ratio_endeudamiento: float, fondo_meses: float) -> int:
    """1 si el endeudamiento supera el tope manejable; 2 si es manejable
    pero el colchón no llega a 3 meses; 3 si además hay 3 meses o más.
    Mide hábitos, no conocimiento."""
    if ratio_endeudamiento > UMBRAL_ENDEUDAMIENTO_MANEJABLE:
        return 1
    if fondo_meses < MESES_COLCHON_MINIMO:
        return 2
    return 3


# --- Colchón ---------------------------------------------------------------
@dataclass(frozen=True)
class PlanColchon:
    meses_objetivo: int
    monto_objetivo: float
    brecha: float
    aporte_mensual: float
    meses_estimados: int | None  # None si no hay aporte para cerrar la brecha
    cumplido: bool


def plan_colchon(
    perfil: PerfilFinanciero,
    meses_objetivo: int = MESES_COLCHON_MINIMO,
    aporte_mensual: float | None = None,
) -> PlanColchon:
    aporte = perfil.ahorro_mes if aporte_mensual is None else aporte_mensual
    if aporte < 0:
        raise ValueError("aporte_mensual no puede ser negativo")
    monto = meses_objetivo * perfil.gasto_mensual
    brecha = max(0.0, monto - perfil.fondo_emergencia_usd)
    if brecha == 0.0:
        meses = 0
    elif aporte > 0:
        meses = math.ceil(round(brecha / aporte, 9))
    else:
        meses = None
    return PlanColchon(
        meses_objetivo=meses_objetivo,
        monto_objetivo=monto,
        brecha=brecha,
        aporte_mensual=aporte,
        meses_estimados=meses,
        cumplido=brecha == 0.0,
    )


# --- Retiro ----------------------------------------------------------------
@dataclass(frozen=True)
class SupuestosRetiro:
    aportacion_mensual: float
    anios: int = RETIRO_ANIOS_DEFAULT
    rendimiento_anual_real: float = RENDIMIENTO_REAL_ANUAL_DEFAULT
    saldo_inicial: float = 0.0


@dataclass(frozen=True)
class ProyeccionRetiro:
    supuestos: SupuestosRetiro
    saldo_final: float  # en dólares de hoy (rendimiento real)
    total_aportado: float
    rendimiento_estimado: float


def proyectar_retiro(s: SupuestosRetiro) -> ProyeccionRetiro:
    if s.aportacion_mensual < 0 or s.saldo_inicial < 0:
        raise ValueError("aportación y saldo inicial no pueden ser negativos")
    if not float(s.anios).is_integer() or not (
        RETIRO_ANIOS_MIN <= s.anios <= RETIRO_ANIOS_MAX
    ):
        raise ValueError(
            f"anios debe ser un entero entre {RETIRO_ANIOS_MIN} y {RETIRO_ANIOS_MAX} "
            f"(recibido: {s.anios})."
        )
    if s.rendimiento_anual_real <= -1:
        raise ValueError("rendimiento_anual_real debe ser > -1")
    n = 12 * s.anios
    i = (1 + s.rendimiento_anual_real) ** (1 / 12) - 1
    if abs(i) < 1e-12:
        saldo = s.saldo_inicial + s.aportacion_mensual * n
    else:
        factor = (1 + i) ** n
        saldo = s.saldo_inicial * factor + s.aportacion_mensual * (factor - 1) / i
    aportado = s.aportacion_mensual * n
    return ProyeccionRetiro(
        supuestos=s,
        saldo_final=saldo,
        total_aportado=aportado,
        rendimiento_estimado=saldo - s.saldo_inicial - aportado,
    )


# --- Roadmap (t077 §6) -----------------------------------------------------
@dataclass(frozen=True)
class PasoRoadmap:
    orden: int
    clave: str
    titulo: str
    monto_objetivo: float | None
    brecha: float | None
    meses_estimados: int | None
    cumplido: bool
    razon: str


def construir_roadmap(
    perfil: PerfilFinanciero, aporte_mensual: float | None = None
) -> tuple[PasoRoadmap, ...]:
    """Escalera: colchón de 3 meses -> colchón de 6 meses -> retiro. Los
    plazos se cuentan desde hoy, no acumulados entre peldaños."""
    c3 = plan_colchon(perfil, MESES_COLCHON_MINIMO, aporte_mensual)
    c6 = plan_colchon(perfil, MESES_COLCHON_AMPLIO, aporte_mensual)
    razon_colchon = (
        "Benchmark de la industria: entre 3 y 6 meses de gastos guardados "
        "(glosario educativo)."
    )
    return (
        PasoRoadmap(
            1,
            "colchon_3_meses",
            "Colchón de 3 meses de gastos",
            c3.monto_objetivo,
            c3.brecha,
            c3.meses_estimados,
            c3.cumplido,
            razon_colchon,
        ),
        PasoRoadmap(
            2,
            "colchon_6_meses",
            "Colchón de 6 meses de gastos",
            c6.monto_objetivo,
            c6.brecha,
            c6.meses_estimados,
            c6.cumplido,
            razon_colchon,
        ),
        PasoRoadmap(
            3,
            "retiro",
            "Ahorro para el retiro",
            None,
            None,
            None,
            False,
            "Entre más temprano empiezas, más tiempo trabaja tu " "dinero a tu favor.",
        ),
    )


# --- Plan completo ---------------------------------------------------------
@dataclass(frozen=True)
class PlanFinanciero:
    nivel: int
    nombre_nivel: str
    ahorro_mes: float
    meta_ahorro_mensual: float
    progreso_meta: float | None
    falta_meta_mensual: float
    meta_cumplida: bool
    fondo_meses: float
    de_cada_100_a_deuda: float
    brecha_deuda_mensual: float
    aporte_paralelo_referencia: float | None
    colchon: PlanColchon
    productos: tuple[str, ...]
    roadmap: tuple[PasoRoadmap, ...]


def generar_plan(perfil: PerfilFinanciero) -> PlanFinanciero:
    nivel = calcular_nivel(perfil.ratio_endeudamiento, perfil.fondo_meses)

    # S2: en el nivel 2 la referencia en paralelo es lo que ya aporta.
    paralelo = None
    if nivel == 2 and perfil.inversion_mensual > 0:
        paralelo = min(perfil.inversion_mensual, perfil.ahorro_mes)
    aporte_colchon = max(0.0, perfil.ahorro_mes - (paralelo or 0.0))

    brecha_deuda = max(
        0.0,
        (perfil.ratio_endeudamiento - UMBRAL_ENDEUDAMIENTO_MANEJABLE)
        * perfil.ingreso_mensual,
    )
    return PlanFinanciero(
        nivel=nivel,
        nombre_nivel=NOMBRES_NIVEL[nivel],
        ahorro_mes=perfil.ahorro_mes,
        meta_ahorro_mensual=perfil.meta_ahorro_mensual,
        progreso_meta=perfil.progreso_meta,
        falta_meta_mensual=perfil.falta_meta_mensual,
        meta_cumplida=perfil.meta_cumplida,
        fondo_meses=perfil.fondo_meses,
        de_cada_100_a_deuda=perfil.ratio_endeudamiento * 100,
        brecha_deuda_mensual=brecha_deuda,
        aporte_paralelo_referencia=paralelo,
        colchon=plan_colchon(perfil, MESES_COLCHON_MINIMO, aporte_colchon),
        productos=PRODUCTOS_POR_NIVEL[nivel],
        roadmap=construir_roadmap(perfil, aporte_colchon),
    )


# --- Bloques de texto para el System Prompt --------------------------------
def _usd(x: float) -> str:
    return f"${x:,.0f}"


def _meses_txt(n: int | None) -> str:
    if n is None:
        return "no se puede estimar con el ahorro actual"
    if n == 0:
        return "ya cumplido"
    return f"unos {n} meses" if n > 1 else "1 mes"


def contexto_plan_para_prompt(plan: PlanFinanciero) -> str:
    """Bloque que se inserta en el System Prompt. Cifras ya calculadas y
    redondeadas a dólares enteros (regla de claridad, t077 §1.1.4). El
    LLM debe usarlas tal cual y no calcular otras."""
    fondo = (
        "sin gasto registrado"
        if math.isinf(plan.fondo_meses)
        else f"{plan.fondo_meses:.2f} meses de gasto"
        + (f" (unos {plan.fondo_meses * 30:.0f} días)" if plan.fondo_meses < 1 else "")
    )
    lineas = [
        "CIFRAS CALCULADAS POR CÓDIGO (úsalas tal cual; no calcules otras):",
        f"- Nivel: {plan.nivel} ({plan.nombre_nivel}).",
        f"- Ahorro del mes: {_usd(plan.ahorro_mes)}.",
    ]
    if plan.progreso_meta is not None:
        if plan.meta_cumplida:
            lineas.append(
                f"- Meta de ahorro mensual: {_usd(plan.meta_ahorro_mensual)}. "
                "Ya la cumpliste."
            )
        else:
            lineas.append(
                f"- Meta de ahorro mensual: {_usd(plan.meta_ahorro_mensual)}. "
                f"Llevas {plan.progreso_meta * 100:.0f}%; te faltan "
                f"{_usd(plan.falta_meta_mensual)} al mes."
            )
    lineas.append(f"- Fondo de emergencia: {fondo}.")
    lineas.append(
        f"- Deuda: de cada $100 que ganas, ${plan.de_cada_100_a_deuda:.0f} van a "
        f"pagar deudas (lo manejable es hasta ${UMBRAL_ENDEUDAMIENTO_MANEJABLE * 100:.0f} "
        "de cada $100)."
    )
    c = plan.colchon
    if c.cumplido:
        lineas.append(f"- Colchón de {c.meses_objetivo} meses: ya cumplido.")
    else:
        lineas.append(
            f"- Colchón de {c.meses_objetivo} meses: objetivo {_usd(c.monto_objetivo)}, "
            f"te faltan {_usd(c.brecha)}. Destinando {_usd(c.aporte_mensual)} al mes "
            f"llegarías en {_meses_txt(c.meses_estimados)}."
        )
    if plan.aporte_paralelo_referencia is not None:
        lineas.append(
            f"- Aporte en paralelo a inversión/retiro (monto pequeño): como referencia, "
            f"{_usd(plan.aporte_paralelo_referencia)} al mes, que es lo que ya aportas."
        )
    lineas.append(
        "- Tipos de producto que puedes mencionar: " + ", ".join(plan.productos) + "."
    )
    lineas.append("- Roadmap:")
    for p in plan.roadmap:
        if p.cumplido:
            estado = "ya cumplido"
        elif p.monto_objetivo is not None:
            estado = (
                f"objetivo {_usd(p.monto_objetivo)}, faltan {_usd(p.brecha or 0)}, "
                f"{_meses_txt(p.meses_estimados)}"
            )
        else:
            estado = "se calcula con una proyección"
        lineas.append(f"    {p.orden}. {p.titulo}: {estado}.")
    return "\n".join(lineas)


def contexto_retiro_para_prompt(p: ProyeccionRetiro) -> str:
    s = p.supuestos
    return (
        "PROYECCIÓN DE RETIRO (estimado ilustrativo, no garantizado):\n"
        f"- Si aportas {_usd(s.aportacion_mensual)} al mes durante {s.anios} años, "
        f"con un rendimiento supuesto de {s.rendimiento_anual_real * 100:.1f}% anual real "
        "(ya descuenta la inflación), tendrías cerca de "
        f"{_usd(p.saldo_final)} en dólares de hoy.\n"
        f"- De eso, {_usd(p.total_aportado)} serían tus aportaciones y "
        f"{_usd(p.rendimiento_estimado)} el rendimiento estimado.\n"
        "- El rendimiento es un supuesto que puedes cambiar; no es un dato ni una promesa."
    )


if __name__ == "__main__":
    # Sanity check manual (no es un test formal: ver test_plan_engine.py).
    anas = {
        "Ana primeriza (PFT_0000636)": PerfilFinanciero(
            3704.29, 3077.46, 0.58, 540.88, 2194.05, False, 140.81
        ),
        "Ana más madura (PFT_0002539)": PerfilFinanciero(
            3854.89, 2443.44, 0.17, 1286.49, 2346.98, False, 202.27
        ),
    }
    for nombre, perfil in anas.items():
        print(f"\n=== {nombre} ===")
        print(contexto_plan_para_prompt(generar_plan(perfil)))
    ejemplo = proyectar_retiro(SupuestosRetiro(aportacion_mensual=200))
    print(
        "\n=== Ejemplo de retiro (aportación de ejemplo; plazo y rendimiento por defecto) ==="
    )
    print(contexto_retiro_para_prompt(ejemplo))

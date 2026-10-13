"""
Indicadores de Moneta — rangos, etiquetas y Salud Financiera (UNA sola fuente)

Hasta la Sesión 36 los cortes de IRFI/ICA vivían escritos a mano dentro de la
pantalla "Lo que tengo hoy", y Centavo (prompt + guardrail) tenía instrucciones
contrarias ("no existen umbrales"): la pantalla decía "Moderado" y el asistente
no podía repetirlo. Este módulo es la fuente única: lo importan la pantalla, el
contexto de Centavo y su guardrail.

Origen de cada decisión:
  * IRFI = Índice de Riesgo Financiero INICIAL (Contexto Maestro §6.2; el
    prompt decía "Individual": corregido). ICA = Índice de Capacidad de Ahorro.
    Ambos en [0, 1]. IRFI: más alto = más riesgo. ICA: más alto = más capacidad.
  * "Salud Financiera" es un tercer indicador SOLICITADO por el mentor (Sesión 36)
    y se calcula a partir de IRFI e ICA:  100 * (0.6*ICA + 0.4*(1 - IRFI)).
    El mentor pidió el indicador y que se explique con rangos claros, no la
    fórmula: los pesos y los cortes son PROPUESTA del equipo, por validar.
  * IRFI/ICA de Personal Finance Tracker usan componentes neutros (0.5) donde la
    fuente no trae el dato (Contexto Maestro §6.2.1): la Salud es un ESTIMADO.

Consistencia pantalla <-> pantalla: la etiqueta se decide con el valor REDONDEADO
a lo que se muestra (IRFI/ICA a 2 decimales, Salud a entero), para que nunca se
vea "0.35 — Bajo" con un rango que dice que 0.35 ya es "Moderado".

Si falta IRFI o ICA no se inventa un valor neutro: devuelve None y la pantalla
dice "no disponible".
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Fórmula y cortes (PROPUESTA del equipo, por validar con el mentor) -------
PESO_ICA = 0.6
PESO_IRFI_INVERSO = 0.4

IRFI_CORTE_BAJO = 0.35  # menos de esto: Bajo
IRFI_CORTE_ALTO = 0.60  # menos de esto: Moderado; de aquí en adelante: Alto
ICA_CORTE_BAJO = 0.35  # hasta esto: Baja
ICA_CORTE_ALTO = 0.60  # más de esto: Alta; entre ambos: Media
SALUD_CORTE_ESTABLE = 50
SALUD_CORTE_OPTIMA = 75

NOMBRE_IRFI = "Índice de Riesgo Financiero Inicial"
NOMBRE_ICA = "Índice de Capacidad de Ahorro"

BADGE = {"bueno": "badge-emerald", "medio": "badge-cyan", "atencion": "badge-coral"}
COLOR = {"bueno": "#00E676", "medio": "#00F2FE", "atencion": "#FF5376"}


@dataclass(frozen=True)
class Lectura:
    etiqueta: str
    tono: str  # "bueno" | "medio" | "atencion"

    @property
    def badge(self) -> str:
        return BADGE[self.tono]

    @property
    def color(self) -> str:
        return COLOR[self.tono]


def lectura_irfi(valor: float | None) -> Lectura | None:
    if valor is None:
        return None
    v = round(valor, 2)
    if v < IRFI_CORTE_BAJO:
        return Lectura("Bajo", "bueno")
    if v < IRFI_CORTE_ALTO:
        return Lectura("Moderado", "medio")
    return Lectura("Alto", "atencion")


def lectura_ica(valor: float | None) -> Lectura | None:
    if valor is None:
        return None
    v = round(valor, 2)
    if v > ICA_CORTE_ALTO:
        return Lectura("Alta", "bueno")
    if v > ICA_CORTE_BAJO:
        return Lectura("Media", "medio")
    return Lectura("Baja", "atencion")


def salud_financiera(irfi: float | None, ica: float | None) -> int | None:
    """Nota de 0 a 100, ENTERA (lo que se muestra es lo que se etiqueta)."""
    if irfi is None or ica is None:
        return None
    nota = 100.0 * (PESO_ICA * ica + PESO_IRFI_INVERSO * (1.0 - irfi))
    return int(round(min(max(nota, 0.0), 100.0)))


def lectura_salud(nota: int | None) -> Lectura | None:
    if nota is None:
        return None
    if nota >= SALUD_CORTE_OPTIMA:
        return Lectura("Óptima", "bueno")
    if nota >= SALUD_CORTE_ESTABLE:
        return Lectura("Estable", "medio")
    return Lectura("Vulnerable", "atencion")


# --- Textos de rangos (los usa la pantalla y el contexto de Centavo) ----------
def rango_irfi() -> str:
    return (
        f"Bajo: menos de {IRFI_CORTE_BAJO:.2f} · Moderado: de {IRFI_CORTE_BAJO:.2f} a "
        f"{IRFI_CORTE_ALTO:.2f} (sin incluirlo) · Alto: {IRFI_CORTE_ALTO:.2f} o más"
    )


def rango_ica() -> str:
    return (
        f"Baja: {ICA_CORTE_BAJO:.2f} o menos · Media: más de {ICA_CORTE_BAJO:.2f} hasta "
        f"{ICA_CORTE_ALTO:.2f} · Alta: más de {ICA_CORTE_ALTO:.2f}"
    )


def rango_salud() -> str:
    return (
        f"Vulnerable: menos de {SALUD_CORTE_ESTABLE} · Estable: de {SALUD_CORTE_ESTABLE} a "
        f"{SALUD_CORTE_OPTIMA - 1} · Óptima: {SALUD_CORTE_OPTIMA} o más"
    )


def formula_salud() -> str:
    return (
        f"{PESO_ICA * 100:.0f}% el ICA + {PESO_IRFI_INVERSO * 100:.0f}% el IRFI invertido "
        "(un IRFI más bajo suma más)"
    )


# --- Para Centavo --------------------------------------------------------------
def lineas_para_centavo(irfi: float | None, ica: float | None) -> list[str]:
    """Líneas del bloque DATOS_DEL_USUARIO: valor, ETIQUETA OFICIAL y su rango."""
    lineas: list[str] = []
    li, lc = lectura_irfi(irfi), lectura_ica(ica)
    if li is not None:
        lineas.append(
            f"IRFI ({NOMBRE_IRFI.lower()}): {irfi:.2f}. Etiqueta oficial: {li.etiqueta} "
            f"({rango_irfi()}). Más alto = más riesgo."
        )
    if lc is not None:
        lineas.append(
            f"ICA ({NOMBRE_ICA.lower()}): {ica:.2f}. Etiqueta oficial: {lc.etiqueta} "
            f"({rango_ica()}). Más alto = más capacidad de ahorro."
        )
    nota = salud_financiera(irfi, ica)
    ls = lectura_salud(nota)
    if ls is not None:
        lineas.append(
            f"Salud financiera: {nota} de 100. Etiqueta oficial: {ls.etiqueta} "
            f"({rango_salud()}). Es un estimado: combina {formula_salud()}."
        )
    return lineas


def etiquetas_permitidas(irfi: float | None, ica: float | None) -> frozenset[str]:
    """Fragmentos (en minúsculas) que el guardrail NO debe tratar como "umbral
    inventado" porque coinciden con la etiqueta oficial de esta persona. Una
    etiqueta que no sea la suya sí se marca ("riesgo alto" con un IRFI Moderado)."""
    permitidas: set[str] = set()
    li, lc = lectura_irfi(irfi), lectura_ica(ica)
    if li is not None:
        permitidas |= {
            "Bajo": {"riesgo financiero bajo"},
            "Moderado": {"moderado", "moderada", "riesgo financiero moderado"},
            "Alto": {
                "riesgo alto",
                "alto riesgo",
                "riesgo elevado",
                "riesgo financiero alto",
                "riesgo financiero elevado",
            },
        }[li.etiqueta]
    if lc is not None:
        permitidas |= {
            "Alta": {"alta capacidad", "alta capacidad de ahorro"},
            "Media": set(),
            "Baja": {"baja capacidad", "baja capacidad de ahorro"},
        }[lc.etiqueta]
    return frozenset(permitidas)

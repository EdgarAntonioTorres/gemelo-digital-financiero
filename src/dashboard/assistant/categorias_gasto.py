"""
Categorías de gasto — qué sostienen los datos y qué no (`t077` v2.3, Sesión 36)

El mentor pidió categorizar el gasto con el mayor detalle posible. Lo que la
fuente (Personal Finance Tracker, 3,000 filas) SÍ permite, medido sobre esas
3,000 filas:

  * `rent_or_mortgage` (vivienda): un monto en USD, nunca cero; es <= al gasto
    esencial en 92% de las filas y <= al gasto total en 98%.
  * `essential_spending` y `discretionary_spending`: dos montos declarados que NO
    descomponen el gasto total (suman el total en solo 3% de las filas; su suma
    va de 0.27x a 21.5x el total). Por eso se presentan como categorías
    REPORTADAS, con la cobertura a la vista, nunca como "partes del total".
  * `subscription_services`: solo un conteo (1 a 9), sin montos.

Lo que NO permite, y por qué no se usa:
  * `category` (Dining Out, Groceries...): es la categoría "dominante" de la fila
    y no guarda relación con ningún monto (eta² de 0.002 a 0.005 contra cada
    columna de monto: lo esperable por puro azar). Recomendar "cocina más" porque
    una fila dice "Dining Out" no tendría base. NO se usa para nada.
  * `loan_payment`: no es coherente con `debt_to_income_ratio` (coinciden solo en
    14% de las filas); mostrarlos juntos se contradice. Queda fuera (t077 §7).
  * Subcategorías (comida, transporte, entretenimiento...): no existen en la
    fuente. Con transacciones reales con categoría de comercio esta capa se
    alimentaría sola.

Este módulo es la fuente única de las categorías: lo usan la pantalla y Centavo.
Funciones puras.
"""

from __future__ import annotations

from dataclasses import dataclass

VIVIENDA = "Vivienda (gasto fijo)"
OTROS_BASICOS = "Otros gastos básicos"
FLEXIBLES = "Gastos flexibles (variables)"
SIN_CATEGORIZAR = "Sin categorizar"


@dataclass(frozen=True)
class DesgloseGasto:
    vivienda: float
    otros_basicos: float
    flexibles: float
    gasto_total: float
    ingreso: float

    @property
    def categorizado(self) -> float:
        return self.vivienda + self.otros_basicos + self.flexibles

    @property
    def sin_categorizar(self) -> float:
        """Lo que el total tiene de más que las categorías (0 si no sobra)."""
        return max(self.gasto_total - self.categorizado, 0.0)

    @property
    def exceso(self) -> float:
        """Cuánto las categorías declaradas superan al gasto total (0 si no)."""
        return max(self.categorizado - self.gasto_total, 0.0)

    @property
    def cuadra_con_el_total(self) -> bool:
        """True si las categorías caben dentro del gasto total."""
        return self.exceso == 0.0

    @property
    def cobertura(self) -> float:
        """Fracción del gasto total que cubren las categorías (puede pasar de 1)."""
        return self.categorizado / self.gasto_total if self.gasto_total > 0 else 0.0

    @property
    def vivienda_pct_ingreso(self) -> float | None:
        return self.vivienda / self.ingreso if self.ingreso > 0 else None

    def partes(self) -> list[tuple[str, float]]:
        """Partes para graficar. Si caben en el total se agrega "Sin categorizar" y
        todo suma el gasto total; si no caben, solo las categorías (el gráfico se
        lee como proporción de lo categorizado)."""
        partes = [
            (VIVIENDA, self.vivienda),
            (OTROS_BASICOS, self.otros_basicos),
            (FLEXIBLES, self.flexibles),
        ]
        if self.cuadra_con_el_total and self.sin_categorizar > 0:
            partes.append((SIN_CATEGORIZAR, self.sin_categorizar))
        return partes

    @property
    def denominador(self) -> float:
        """Base de los porcentajes: el gasto total si las categorías caben; si no,
        lo categorizado."""
        return self.gasto_total if self.cuadra_con_el_total else self.categorizado

    def porcentaje(self, monto: float) -> float:
        return monto / self.denominador * 100.0 if self.denominador > 0 else 0.0

    def recorte_ilustrativo(self, fraccion: float = 0.10) -> float:
        """Cuánto se ahorraría al mes si se recortara esa fracción de los gastos
        flexibles. Es aritmética de un "si...", no una estadística."""
        return self.flexibles * fraccion


def desglosar(
    gasto_total: float,
    esencial: float | None,
    discrecional: float | None,
    vivienda: float | None,
    ingreso: float,
) -> DesgloseGasto | None:
    """None si falta cualquiera de los 3 datos (la pantalla cae a la vista de
    proporciones). La vivienda se toma como parte del gasto esencial (se cumple en
    92% de las filas); si la vivienda fuera mayor que el esencial, "otros básicos"
    queda en 0 en vez de negativo."""
    if esencial is None or discrecional is None or vivienda is None:
        return None
    if min(esencial, discrecional, vivienda, gasto_total) < 0:
        raise ValueError("Los montos de gasto no pueden ser negativos.")
    return DesgloseGasto(
        vivienda=vivienda,
        otros_basicos=max(esencial - vivienda, 0.0),
        flexibles=discrecional,
        gasto_total=gasto_total,
        ingreso=ingreso,
    )


def desde_detalle(perfil, detalle) -> DesgloseGasto | None:
    """Arma el desglose desde un PerfilFinanciero y la fila de fact_perfil_detalle.
    Si las columnas nuevas aún no existen (migración sin correr), devuelve None."""

    def num(clave: str) -> float | None:
        try:
            valor = detalle[clave]
        except (KeyError, IndexError):
            return None
        try:
            if valor is None or valor != valor:  # None o NaN
                return None
            return float(valor)
        except (TypeError, ValueError):
            return None

    return desglosar(
        gasto_total=perfil.gasto_mensual,
        esencial=num("gasto_esencial_declarado"),
        discrecional=num("gasto_discrecional_declarado"),
        vivienda=num("vivienda_mensual"),
        ingreso=perfil.ingreso_mensual,
    )

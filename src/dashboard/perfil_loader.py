"""
Cargador de perfil — une las 3 tablas de Gold de UNA persona (`t077` v2.3)

Para un `record_id`, lee:

  * `gold.fact_comportamiento`  — ingreso, gasto, ratio de endeudamiento,
                                  fondo de emergencia en meses.
  * `gold.fact_perfil_detalle`  — meta de ahorro, ahorro del mes, inversión,
                                  fondo en USD, proporción esencial,
                                  suscripciones (tabla sembrada para las 2 Anas).
  * `gold.fact_kpi_perfil`      — IRFI e ICA (rango [0, 1]).

y devuelve un `PerfilCargado` con las filas crudas, el `PerfilFinanciero`
y el `PlanFinanciero` de `plan_engine`. Lo usan la pantalla "Lo que
tengo hoy" y (en el paso 2) el router de Centavo, para que ambos
partan de las MISMAS cifras.

Decisiones de diseño:

1. Cargador NUEVO a propósito: `simulator_engine.load_fact_comportamiento()`
   no trae `ratio_endeudamiento` y lo comparten 3 scripts demo ya
   aprobados — no se toca (handoff Sesión 36, §9).
2. Sin Streamlit: recibe la conexión (el caller decide su ciclo de vida),
   así se puede probar y correr por consola
   (`docker compose exec streamlit python perfil_loader.py`).
3. Consultas por `record_id` con parámetros (`%s`), nunca con f-strings.
4. Termina SIEMPRE la transacción (`rollback`) al acabar: psycopg2 abre
   una transacción implícita en cada SELECT, y con la conexión cacheada
   de Streamlit quedaría "idle in transaction" sosteniendo un lock de
   lectura sobre las tablas de Gold, que Spark reemplaza con DROP +
   CREATE en cada corrida (el DROP esperaría). Además, si una consulta
   falla, una conexión sin rollback rechaza todas las siguientes.
5. Las filas obligatorias que faltan o están duplicadas fallan con un
   error explícito; solo `fact_kpi_perfil` es opcional (IRFI/ICA quedan
   en `None`) porque el resto de la pantalla no depende de él.
   `PerfilFinanciero.desde_filas()` revalida que `fact_comportamiento` y
   `fact_perfil_detalle` describan a la misma persona (S6 de
   `plan_engine`).

Variables de entorno (solo si se corre por consola): DW_POSTGRES_HOST,
DW_POSTGRES_DB, DW_POSTGRES_USER, DW_POSTGRES_PASSWORD.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pandas as pd

from assistant import plan_engine as pe

_Q_COMPORTAMIENTO = """
    SELECT record_id, fuente, segmento, income_type, ingreso_mensual,
           gasto_promedio_3m, ratio_endeudamiento, fondo_emergencia_meses
    FROM gold.fact_comportamiento
    WHERE record_id = %s
"""
_Q_DETALLE = "SELECT * FROM gold.fact_perfil_detalle WHERE record_id = %s"
_Q_KPI = """
    SELECT record_id, irfi, ica, irfi_proxy_flag, ica_proxy_flag
    FROM gold.fact_kpi_perfil
    WHERE record_id = %s
"""


class PerfilNoEncontradoError(LookupError):
    """Falta la fila del perfil en una tabla obligatoria de Gold."""


@dataclass(frozen=True)
class PerfilCargado:
    record_id: str
    comportamiento: pd.Series
    detalle: pd.Series
    irfi: float | None
    ica: float | None
    irfi_proxy_flag: bool | None
    ica_proxy_flag: bool | None
    perfil: pe.PerfilFinanciero
    plan: pe.PlanFinanciero


def _una_fila(
    df: pd.DataFrame, tabla: str, record_id: str, obligatoria: bool
) -> pd.Series | None:
    if df.empty:
        if obligatoria:
            raise PerfilNoEncontradoError(
                f"{record_id} no está en {tabla}. Revisa que el pipeline de Gold "
                "haya corrido y, si falta en fact_perfil_detalle, que se haya "
                "corrido config/create-fact-perfil-detalle.sql."
            )
        return None
    if len(df) > 1:
        raise pe.PerfilIncoherenteError(
            f"{record_id} aparece {len(df)} veces en {tabla}; se esperaba 1."
        )
    return df.iloc[0]


def _float_o_none(valor) -> float | None:
    return None if valor is None or pd.isna(valor) else float(valor)


def _bool_o_none(valor) -> bool | None:
    return None if valor is None or pd.isna(valor) else bool(valor)


def cargar_perfil(conn, record_id: str) -> PerfilCargado:
    """Carga y valida el perfil de `record_id`. Lanza
    `PerfilNoEncontradoError` o `plan_engine.PerfilIncoherenteError`."""
    try:
        df_comp = pd.read_sql(_Q_COMPORTAMIENTO, conn, params=(record_id,))
        df_det = pd.read_sql(_Q_DETALLE, conn, params=(record_id,))
        df_kpi = pd.read_sql(_Q_KPI, conn, params=(record_id,))
    finally:
        conn.rollback()  # ver decisión 4

    comportamiento = _una_fila(df_comp, "gold.fact_comportamiento", record_id, True)
    detalle = _una_fila(df_det, "gold.fact_perfil_detalle", record_id, True)
    kpi = _una_fila(df_kpi, "gold.fact_kpi_perfil", record_id, False)

    perfil = pe.PerfilFinanciero.desde_filas(comportamiento, detalle)
    return PerfilCargado(
        record_id=record_id,
        comportamiento=comportamiento,
        detalle=detalle,
        irfi=None if kpi is None else _float_o_none(kpi["irfi"]),
        ica=None if kpi is None else _float_o_none(kpi["ica"]),
        irfi_proxy_flag=None if kpi is None else _bool_o_none(kpi["irfi_proxy_flag"]),
        ica_proxy_flag=None if kpi is None else _bool_o_none(kpi["ica_proxy_flag"]),
        perfil=perfil,
        plan=pe.generar_plan(perfil),
    )


if __name__ == "__main__":
    # Verificación manual con datos reales (no es un test formal).
    from perfiles_sinteticos import ARQUETIPOS
    from simulator_engine import get_dw_connection

    errores = 0
    conn = get_dw_connection()
    try:
        for a in ARQUETIPOS:
            print(f"\n=== {a['label']} ({a['record_id']}) ===")
            try:
                c = cargar_perfil(conn, a["record_id"])
            except (PerfilNoEncontradoError, pe.PerfilIncoherenteError) as exc:
                print(f"ERROR: {exc}")
                errores += 1
                continue
            print(f"nivel={c.plan.nivel} ({c.plan.nombre_nivel})")
            print(
                f"irfi={c.irfi} (proxy={c.irfi_proxy_flag}) · "
                f"ica={c.ica} (proxy={c.ica_proxy_flag})"
            )
            print(
                f"ahorro_mes={c.perfil.ahorro_mes:.2f} · meta={c.perfil.meta_ahorro_mensual:.2f}"
            )
            print(
                f"income_type={c.comportamiento['income_type']} · "
                f"segmento={c.comportamiento['segmento']}"
            )
    finally:
        conn.close()
    print("\nResultado:", "OK" if errores == 0 else f"{errores} perfil(es) con error")
    sys.exit(1 if errores else 0)

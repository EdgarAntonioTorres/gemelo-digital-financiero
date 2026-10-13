"""
Demo de `plan_engine` con datos reales — las dos Anas (t077 v2.3)

Primera prueba de integración: lee de `postgres-dw` las filas REALES de
`gold.fact_comportamiento` y `gold.fact_perfil_detalle` para las dos Anas
de la demo, arma cada perfil con `PerfilFinanciero.desde_filas()` (que
revalida que ambas tablas describan a la misma persona) e imprime
exactamente el bloque de cifras que recibiría Centavo. Solo lectura.

Mismo patrón que `escenario_renta_demo.py` y compañía: vive junto a
`simulator_engine.py` y se corre dentro del contenedor de streamlit:

    docker compose exec streamlit python plan_engine_demo.py

Variables de entorno requeridas (mismas de `simulator_engine.py`):
DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER, DW_POSTGRES_PASSWORD.
"""

from __future__ import annotations

import sys

import pandas as pd

from assistant import plan_engine as pe
from simulator_engine import get_dw_connection

ANAS = [
    ("Ana primeriza", "PFT_0000636"),
    ("Ana más madura", "PFT_0002539"),
]


def main() -> int:
    ids = ", ".join(f"'{rid}'" for _, rid in ANAS)
    conn = get_dw_connection()
    try:
        comportamiento = pd.read_sql(
            "SELECT record_id, ingreso_mensual, gasto_promedio_3m, ratio_endeudamiento, "
            f"fondo_emergencia_meses FROM gold.fact_comportamiento WHERE record_id IN ({ids})",
            conn,
        )
        detalle = pd.read_sql(
            f"SELECT * FROM gold.fact_perfil_detalle WHERE record_id IN ({ids})", conn
        )
    finally:
        conn.close()

    errores = 0
    for nombre, record_id in ANAS:
        print(f"\n=== {nombre} ({record_id}) ===")
        fila_c = comportamiento.loc[comportamiento["record_id"] == record_id]
        fila_d = detalle.loc[detalle["record_id"] == record_id]
        if fila_c.empty or fila_d.empty:
            print(
                "ERROR: falta la fila en "
                + (
                    "gold.fact_comportamiento"
                    if fila_c.empty
                    else "gold.fact_perfil_detalle"
                )
                + " — revisa que el pipeline de Gold y "
                "config/create-fact-perfil-detalle.sql hayan corrido."
            )
            errores += 1
            continue
        try:
            perfil = pe.PerfilFinanciero.desde_filas(fila_c.iloc[0], fila_d.iloc[0])
        except pe.PerfilIncoherenteError as exc:
            print(f"ERROR de coherencia: {exc}")
            errores += 1
            continue

        plan = pe.generar_plan(perfil)
        print(pe.contexto_plan_para_prompt(plan))

        # Retiro con lo que la persona ya invierte hoy, plazo y rendimiento por defecto.
        referencia = perfil.inversion_mensual
        if referencia > 0:
            retiro = pe.proyectar_retiro(
                pe.SupuestosRetiro(aportacion_mensual=referencia)
            )
            print()
            print(pe.contexto_retiro_para_prompt(retiro))
        else:
            print(
                "\n(No invierte hoy: la aportación de referencia para el retiro "
                "aún no está definida.)"
            )

    print("\nResultado:", "OK" if errores == 0 else f"{errores} perfil(es) con error")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())

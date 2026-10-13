"""
Comparación con el grupo y alerta de fraude — consulta FIJA (`t077` v2.3)

Antes, la categoría DATOS le pedía a Llama 3.1 8B que escribiera SQL
(`text_to_sql.py`) y luego que redactara el resultado. En la primera corrida
real con las dos Anas (Sesión 36) salió esto para "¿Cómo estoy frente al
promedio de mi grupo?" con Ana primeriza:

  * El SQL era basura (dividía una columna entre un AVG con `fuente IN
    ('perfil','irfi','ica')`, valores que no existen) y NO filtraba por
    el grupo correcto.
  * La respuesta inventó números: "estás en el 17% de tu grupo",
    "ligeramente por debajo del promedio" en IRFI.
  * Con Ana más madura, el modelo dijo que "no hay un promedio de tu grupo".

Es el peor tipo de falla del proyecto (cifras fabricadas con apariencia de
estadística), así que esta categoría deja de depender de SQL generado por el
modelo: las consultas son FIJAS (parametrizadas, escritas aquí), corren con
`assistant_ro` (solo lectura, `statement_timeout` 10 s) y el CÓDIGO decide
la lectura de cada comparación ("por encima", "por debajo", "parecido").
El LLM solo la redacta. Mismo principio que el resto de la v2: lo que se
puede decidir con código no se le deja al modelo (t077 §5).

`text_to_sql.py` se conserva (con el blindaje de las dos Anas y sus
pruebas) pero el router ya no lo usa: volver a él es cambiar una rama en
`router.responder_chat()`. Si el mentor quiere conservar Text-to-SQL como
parte visible del proyecto (t079), esa decisión es suya.

Solo agregados: el grupo son las personas de `fact_comportamiento` con el
mismo `income_type` (cientos de filas, no individuos). Nunca se devuelve la
fila de otra persona (t077 §3). No toca `fact_perfil_detalle`.

Variables de entorno (las de `text_to_sql.get_assistant_connection`):
DW_POSTGRES_HOST, DW_POSTGRES_DB, ASSISTANT_DB_USER, ASSISTANT_DB_PASSWORD.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from assistant import text_to_sql

if TYPE_CHECKING:
    from perfil_loader import PerfilCargado

# Diferencia relativa (±) por debajo de la cual se dice "parecido al promedio".
TOLERANCIA_PARECIDO = 0.03

_Q_GRUPO = """
    SELECT COUNT(*),
           AVG(ingreso_mensual),
           AVG(gasto_promedio_3m),
           AVG(GREATEST(0, ingreso_mensual - gasto_promedio_3m)),
           AVG(ratio_endeudamiento),
           AVG(fondo_emergencia_meses)
    FROM gold.fact_comportamiento
    WHERE income_type = %s
"""
_Q_KPI_GRUPO = """
    SELECT AVG(k.irfi), AVG(k.ica)
    FROM gold.fact_kpi_perfil k
    JOIN gold.fact_comportamiento c ON c.record_id = k.record_id
    WHERE c.income_type = %s
"""
_Q_FRAUDE = "SELECT alerta_fraude FROM gold.fact_comportamiento WHERE record_id = %s"


def _f(valor) -> float | None:
    return None if valor is None else float(valor)


def consultar(conn, income_type: str, record_id: str) -> dict:
    """Ejecuta las 3 consultas fijas. Devuelve un dict simple (sin Decimal)."""
    with conn.cursor() as cur:
        cur.execute(_Q_GRUPO, (income_type,))
        n, ingreso, gasto, ahorro, ratio, fondo = cur.fetchone()
        cur.execute(_Q_KPI_GRUPO, (income_type,))
        irfi, ica = cur.fetchone()
        cur.execute(_Q_FRAUDE, (record_id,))
        fila = cur.fetchone()
    return {
        "n": int(n or 0),
        "ingreso": _f(ingreso),
        "gasto": _f(gasto),
        "ahorro": _f(ahorro),
        "ratio": _f(ratio),
        "fondo_meses": _f(fondo),
        "irfi": _f(irfi),
        "ica": _f(ica),
        "alerta_fraude": None if fila is None or fila[0] is None else bool(fila[0]),
    }


def lectura(valor: float, promedio: float | None) -> str:
    """La decide el código, no el modelo: por encima / por debajo / parecido."""
    if promedio is None:
        return "sin dato del grupo"
    if promedio == 0:
        return "parecido al promedio" if valor == 0 else "por encima del promedio"
    if abs(valor - promedio) / abs(promedio) <= TOLERANCIA_PARECIDO:
        return "parecido al promedio"
    return "por encima del promedio" if valor > promedio else "por debajo del promedio"


def formatear(c: "PerfilCargado", g: dict) -> str:
    """Texto listo para RESULTADO_CONSULTA. Función pura (se prueba sin BD)."""
    p, plan = c.perfil, c.plan
    income_type = c.comportamiento["income_type"]
    if g["n"] == 0:
        return (
            "COMPARACIÓN CON EL GRUPO: no hay datos del grupo para este tipo de "
            "ingreso. Díselo con naturalidad; no inventes promedios."
        )
    ahorro_persona = p.ahorro_mes
    lineas = [
        "COMPARACIÓN CON EL GRUPO (calculada por código; el grupo son "
        f"{g['n']:,} personas con el mismo tipo de ingreso: {income_type}). "
        "Cada línea ya trae su lectura: úsala tal cual, no calcules diferencias "
        "ni inventes porcentajes de 'qué lugar ocupas':",
    ]

    def fila(nombre, valor, promedio, fmt):
        lineas.append(
            f"- {nombre}:tú{fmt(valor)}; promedio del grupo{fmt(promedio) if promedio is not None else 'sin dato'} "
            f"({lectura(valor, promedio)})."
        )

    usd = lambda x: f"${x:,.0f}"  # noqa: E731
    fila("Ingreso mensual", p.ingreso_mensual, g["ingreso"], usd)
    fila("Gasto mensual", p.gasto_mensual, g["gasto"], usd)
    fila("Ahorro del mes", ahorro_persona, g["ahorro"], usd)
    fila(
        "Deuda (de cada $100 que ganan, cuántos van a deudas; más alto = más carga)",
        p.ratio_endeudamiento * 100,
        None if g["ratio"] is None else g["ratio"] * 100,
        lambda x: f"${x:,.0f}",
    )
    fila(
        "Fondo de emergencia (meses de gasto cubiertos)",
        plan.fondo_meses,
        g["fondo_meses"],
        lambda x: f"{x:.2f} meses",
    )
    if c.irfi is not None:
        fila(
            "Índice de riesgo financiero, IRFI (más alto = más riesgo)",
            c.irfi,
            g["irfi"],
            lambda x: f"{x:.2f}",
        )
    if c.ica is not None:
        fila(
            "Índice de capacidad de ahorro, ICA (más alto = más capacidad)",
            c.ica,
            g["ica"],
            lambda x: f"{x:.2f}",
        )

    if g["alerta_fraude"] is None:
        lineas.append("- Alerta de fraude: sin dato.")
    else:
        lineas.append(
            "- Alerta de fraude: "
            + (
                "SÍ hay una alerta activa."
                if g["alerta_fraude"]
                else "no hay ninguna alerta activa."
            )
        )
    return "\n".join(lineas)


def bloque_datos(c: "PerfilCargado") -> str:
    """Herramienta fija de la categoría DATOS: abre una conexión de solo
    lectura, consulta y devuelve el texto. El caller captura las excepciones."""
    conn = text_to_sql.get_assistant_connection()
    try:
        g = consultar(conn, str(c.comportamiento["income_type"]), c.record_id)
    finally:
        conn.close()
    return formatear(c, g)

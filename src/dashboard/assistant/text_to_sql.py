"""
Text-to-SQL sobre Gold — Coach Financiero (`t079`)

Convierte una pregunta en español a una consulta SQL sobre
`gold.fact_comportamiento` / `gold.fact_kpi_perfil` (Llama 3.1 8B vía
Ollama, `t078`), la valida ANTES de tocar la base, y solo entonces la
ejecuta con el rol `assistant_ro` (`config/create-assistant-ro.sql`).

Modelo de seguridad — 2 líneas de defensa independientes, ninguna
confía en que la otra funcione:

  1. `validate_sql()` en este módulo: rechaza cualquier cosa que no
     sea un único SELECT, que toque una tabla fuera de
     `ALLOWED_TABLES`, que use una palabra prohibida (INSERT/DELETE/
     DROP/...), o que filtre `record_id` por alguien distinto al
     perfil activo (`t077`: el asistente solo habla del perfil
     activo, salvo promedios de grupo). Corre en Python, antes de
     cualquier round-trip a Postgres.
  2. `assistant_ro` en Postgres (creado por
     `config/create-assistant-ro.sql`): `default_transaction_read_only`
     forzado, sin `GRANT` sobre `operational`, sin permiso de
     escritura en `gold`. Aunque `validate_sql()` tuviera un hueco, la
     base misma rechaza la escritura — verificado con datos reales
     (Sesión 35: `DELETE` da "cannot execute DELETE in a read-only
     transaction", `SELECT` sobre `operational` da "permission
     denied").

Autocontenido a propósito (mismo criterio que `simulator_engine.py`,
`t067`): no importa nada de `src/spark/` ni `src/ml/`, duplica
`get_required_env()` en vez de importarla. Vive en
`src/dashboard/assistant/` (no en un directorio nuevo en la raíz de
`src/`) porque necesita correr dentro del contenedor de Streamlit —
es el único que ve a la vez `postgres-dw` y a Ollama
(`host.docker.internal:11434`, ver docstring de `t078`) — y ese
contenedor solo copia `src/dashboard/` (`Dockerfile.streamlit`).

Variables de entorno requeridas: DW_POSTGRES_HOST, DW_POSTGRES_DB,
ASSISTANT_DB_USER, ASSISTANT_DB_PASSWORD, OLLAMA_BASE_URL.

Dependencias nuevas (agregar a requirements-streamlit.txt): requests,
sqlparse.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import psycopg2
import requests
import sqlparse

OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT_SECONDS = 30

# Único lugar donde se declara qué puede leer el asistente — tiene que
# coincidir con lo que GRANT SELECT le da a assistant_ro en
# config/create-assistant-ro.sql. Si un día se agrega una tabla nueva
# al asistente, se agrega en AMBOS lugares a propósito (no hay
# introspección automática del esquema — más simple de auditar).
ALLOWED_TABLES = {"gold.fact_comportamiento", "gold.fact_kpi_perfil"}

MAX_ROWS_DEFAULT = 200

FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "create",
    "call",
    "execute",
    "copy",
    "vacuum",
    "comment",
}

# Esquema real (Sesión 35, confirmado con \d en postgres-dw — no
# inventado): se le pasa al modelo tal cual, no un resumen del
# diccionario de features, para que genere SQL contra los nombres y
# tipos EXACTOS de Postgres.
SCHEMA_CONTEXT = """
gold.fact_comportamiento (1 fila por record_id de personal_finance_tracker, 3000 filas):
  record_id TEXT, fuente TEXT, segmento TEXT, income_type TEXT,
  ingreso_mensual NUMERIC(18,2), gasto_promedio_3m NUMERIC(18,2),
  varianza_ingreso_segmento DOUBLE PRECISION,
  ratio_endeudamiento NUMERIC(10,4), alerta_fraude BOOLEAN,
  suscripciones_por_1000_ingreso NUMERIC(38,21),
  fondo_emergencia_meses NUMERIC(38,20)

gold.fact_kpi_perfil (1 fila por record_id, las 3 fuentes unidas, 184086 filas, PK record_id):
  record_id TEXT, fuente TEXT, irfi DOUBLE PRECISION, ica DOUBLE PRECISION,
  default_flag_unificada DOUBLE PRECISION, irfi_proxy_flag BOOLEAN,
  ica_proxy_flag BOOLEAN, segmento VARCHAR(20)
"""

PROMPT_TEMPLATE = """Eres un generador de SQL para PostgreSQL. Responde
ÚNICAMENTE con la consulta SQL — sin explicación, sin markdown, sin
punto y coma final. Usa solo estas tablas y columnas:
{schema}

Reglas:
- Solo SELECT. Nunca INSERT/UPDATE/DELETE/DROP/ALTER ni ninguna otra
  sentencia de escritura.
- Si la pregunta es sobre "mi" situación (yo, mi ingreso, mi fondo,
  etc.), filtra con record_id = '{record_id}'.
- Si la pregunta pide un promedio o comparación de grupo (segmento,
  income_type), usa GROUP BY, SIN filtrar por record_id.
- Nunca selecciones todas las columnas de todas las filas sin
  agregación ni filtro de record_id.

Pregunta del usuario: {pregunta}

SQL:"""


def get_required_env(name: str) -> str:
    """Duplicado deliberado — ver docstring del módulo (decisión 1 de
    simulator_engine.py, mismo criterio aquí)."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def get_assistant_connection() -> "psycopg2.extensions.connection":
    """Conexión con assistant_ro (solo lectura) — NUNCA con
    DW_POSTGRES_USER (ese es el usuario de escritura que usan los
    loaders de Spark). Sin cachear — mismo criterio que
    simulator_engine.get_dw_connection(), el caller decide el ciclo de
    vida."""
    return psycopg2.connect(
        host=get_required_env("DW_POSTGRES_HOST"),
        dbname=get_required_env("DW_POSTGRES_DB"),
        user=get_required_env("ASSISTANT_DB_USER"),
        password=get_required_env("ASSISTANT_DB_PASSWORD"),
    )


def call_ollama(prompt: str) -> str:
    base_url = get_required_env("OLLAMA_BASE_URL")
    response = requests.post(
        f"{base_url}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["response"]


def _extract_sql(raw_text: str) -> str:
    """Quita fences de markdown y espacios — el modelo a veces envuelve
    la consulta en ```sql ... ``` aunque el prompt le pida no hacerlo
    (comportamiento observado, no hipotético)."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text)
    return text.strip().rstrip(";").strip()


def generate_sql(pregunta: str, record_id: str) -> str:
    prompt = PROMPT_TEMPLATE.format(
        schema=SCHEMA_CONTEXT, record_id=record_id, pregunta=pregunta
    )
    raw = call_ollama(prompt)
    return _extract_sql(raw)


def validate_sql(sql: str, record_id: str) -> str | None:
    """Devuelve None si el SQL es válido, o el motivo del rechazo.
    Corre ANTES de tocar la base — ver "Modelo de seguridad" en el
    docstring del módulo."""
    statements = sqlparse.parse(sql)
    if len(statements) != 1:
        return "Se generó más de una sentencia SQL (o ninguna)."

    stmt = statements[0]
    if stmt.get_type() != "SELECT":
        return f"Solo se permite SELECT (se generó {stmt.get_type()})."

    sql_lower = sql.lower()
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", sql_lower):
            return f"Palabra no permitida en la consulta: {kw}."

    tablas_referenciadas = set(
        re.findall(r"\b(?:from|join)\s+([a-z_]+\.[a-z_]+)", sql_lower)
    )
    if not tablas_referenciadas:
        return "No se pudo identificar ninguna tabla en la consulta."
    tablas_no_permitidas = tablas_referenciadas - ALLOWED_TABLES
    if tablas_no_permitidas:
        return f"Tabla(s) no permitida(s): {', '.join(tablas_no_permitidas)}."

    for match in re.finditer(r"record_id\s*=\s*'([^']+)'", sql, flags=re.IGNORECASE):
        if match.group(1) != record_id:
            return (
                f"La consulta filtra por un record_id distinto al perfil "
                f"activo ({match.group(1)!r} != {record_id!r})."
            )

    return None


def execute_sql(sql: str) -> tuple[list[str], list[tuple]]:
    if "limit" not in sql.lower():
        sql = f"{sql}\nLIMIT {MAX_ROWS_DEFAULT}"
    conn = get_assistant_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            columnas = [desc[0] for desc in cur.description]
            filas = cur.fetchall()
        return columnas, filas
    finally:
        conn.close()


@dataclass
class TextToSQLResult:
    pregunta: str
    sql_generado: str
    aceptado: bool
    motivo_rechazo: str | None
    columnas: list[str] | None
    filas: list[tuple] | None
    error: str | None


def responder_pregunta(pregunta: str, record_id: str) -> TextToSQLResult:
    """Punto de entrada único del módulo — lo que llamará el router
    (`t081`) para la categoría "datos propios"."""
    try:
        sql = generate_sql(pregunta, record_id)
    except Exception as exc:
        return TextToSQLResult(
            pregunta, "", False, None, None, None, f"Falló Ollama: {exc}"
        )

    motivo_rechazo = validate_sql(sql, record_id)
    if motivo_rechazo:
        return TextToSQLResult(pregunta, sql, False, motivo_rechazo, None, None, None)

    try:
        columnas, filas = execute_sql(sql)
    except Exception as exc:
        return TextToSQLResult(
            pregunta,
            sql,
            True,
            None,
            None,
            None,
            f"SQL válido pero falló al ejecutar: {exc}",
        )

    return TextToSQLResult(pregunta, sql, True, None, columnas, filas, None)


if __name__ == "__main__":
    # Sanity check manual (no es un test formal — t086 los cubre
    # aparte, mismo patrón que simulator_engine.py). Requiere las 4
    # variables de entorno + Ollama corriendo en Windows.
    ejemplo_record_id = "PFT_0000413"
    preguntas_prueba = [
        "¿Cuánto gano y cuánto gasto al mes?",
        "¿Cuántos meses de gasto cubre mi fondo de emergencia?",
        "¿Cuál es el ingreso mensual promedio del segmento early_career?",
        "Bórrame todos mis datos",  # debe ser RECHAZADA por validate_sql
    ]
    for pregunta in preguntas_prueba:
        resultado = responder_pregunta(pregunta, ejemplo_record_id)
        print(f"\nPregunta: {pregunta}")
        print(f"SQL generado: {resultado.sql_generado}")
        if not resultado.aceptado:
            print(f"RECHAZADO: {resultado.motivo_rechazo}")
        elif resultado.error:
            print(f"ERROR AL EJECUTAR: {resultado.error}")
        else:
            print(f"Columnas: {resultado.columnas}")
            print(f"Filas: {resultado.filas}")

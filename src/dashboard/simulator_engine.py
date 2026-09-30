"""
Motor base del simulador Monte Carlo — Moneta (`t067`)

Simula la probabilidad de alcanzar una meta de ahorro (independizarse,
comprar un primer auto, cubrir una primera tarjeta de crédito) dentro
de un horizonte de tiempo elegido por el usuario, a partir del
disponible mensual real (`ingreso_mensual - gasto_promedio_3m`) de
`gold.fact_comportamiento` (Personal Finance Tracker, única fuente
con estos 2 datos — ver diccionario_features.md).

Decisiones de diseño (acordadas con el alumno, Sesión 34):

1. Autocontenido — no importa nada de `src/spark/` ni `src/ml/`
   (mismo criterio ya documentado en `train_baseline_model.py`, t062:
   "duplicar, no acoplar entre capas" — Contexto Maestro §7.3
   extendido). Se conecta a `postgres-dw` con su propia función de
   conexión, en vez de reusar `get_dw_connection()` de
   `quality_dashboard.py` (que está cacheada vía `st.cache_resource`,
   específico de Streamlit) — así este módulo se puede probar
   (`t086`) sin arrastrar Streamlit.

2. Horizonte temporal: 6-36 meses, elegido por el usuario (default
   12) — coherente con el público del proyecto (§2 Contexto Maestro:
   metas de corto/mediano plazo de un adulto joven en inserción
   laboral, no un horizonte de 5+ años).

3. Ruido del Monte Carlo: BOOTSTRAP del disponible mensual real
   (`ingreso_mensual - gasto_promedio_3m`) de otras personas con el
   mismo `income_type` (Salary/Mixed/Freelance) — no una distribución
   paramétrica inventada. Personal Finance Tracker es corte
   transversal (`t107`), no hay serie temporal real de una persona
   en el tiempo; en cada mes simulado se toma prestado (con
   reemplazo) un disponible real de alguien con perfil de ingreso
   similar. Es el mismo espíritu de "no fabricar lo que los datos no
   sostienen" ya aplicado en todo el proyecto (age sintética, housing
   proxies, etc.).

4. Disponible mensual negativo (gasto > ingreso) NO se excluye ni se
   trunca a 0 — se deja tal cual en el pool de bootstrap y en el
   disponible base del perfil. Es un caso real (coherente con
   `fondo_emergencia_meses` medio de 0.37, ya documentado sin
   suavizar) — el simulador debe poder mostrarle a este segmento de
   usuarios una probabilidad de éxito honesta (incluyendo 0%), no
   ocultarlo.

Lee:
    gold.fact_comportamiento (postgres-dw) — record_id, income_type,
    ingreso_mensual, gasto_promedio_3m.

No escribe nada — es una librería de simulación pura, se invoca desde
la futura página Streamlit del simulador (t071/t073), que le pasa los
inputs del usuario y muestra el resultado.

Variables de entorno requeridas (mismas que quality_dashboard.py):
DW_POSTGRES_HOST, DW_POSTGRES_DB, DW_POSTGRES_USER, DW_POSTGRES_PASSWORD.

Dependencias nuevas (agregadas en esta tarea, ver requirements-streamlit.txt):
numpy, scipy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

# Horizonte permitido para el simulador (ver decisión 2 arriba).
HORIZONTE_MIN_MESES = 6
HORIZONTE_MAX_MESES = 36
HORIZONTE_DEFAULT_MESES = 12

# Ajuste de ahorro que el usuario puede aplicar sobre su disponible
# base (-20% a +50%) — permite "jugar" con el simulador sin editar un
# dato que no le pertenece directamente.
AHORRO_EXTRA_PCT_MIN = -0.20
AHORRO_EXTRA_PCT_MAX = 0.50

N_SIMULACIONES_DEFAULT = 10_000


def get_required_env(name: str) -> str:
    """Duplicado deliberado de la misma función en quality_dashboard.py
    y en todo src/spark/ — mismo criterio, este módulo no importa de
    otras capas (ver decisión 1 en el docstring del módulo)."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def get_dw_connection() -> "psycopg2.extensions.connection":
    """Conexión propia, SIN cachear (a diferencia de
    quality_dashboard.get_dw_connection(), que usa st.cache_resource
    porque vive en un contexto de Streamlit). El caller decide el
    ciclo de vida de la conexión — importante para que este módulo se
    pueda probar de forma aislada (t086)."""
    return psycopg2.connect(
        host=get_required_env("DW_POSTGRES_HOST"),
        dbname=get_required_env("DW_POSTGRES_DB"),
        user=get_required_env("DW_POSTGRES_USER"),
        password=get_required_env("DW_POSTGRES_PASSWORD"),
    )


def load_fact_comportamiento(conn) -> pd.DataFrame:
    """Lee las columnas necesarias de gold.fact_comportamiento para
    los 3 escenarios (t068 renta, t069 auto, t070 empleo). Mismo
    patrón de query directa que quality_dashboard.py (sin ORM).
    fondo_emergencia_meses se agregó en t070 (t068/t069 no la usan,
    pero traerla siempre evita tener 3 funciones de carga casi
    idénticas — mismo criterio de 'una tabla que se llena, no
    fragmentar' ya usado en FACT_COMPORTAMIENTO)."""
    query = """
        SELECT record_id, income_type, ingreso_mensual, gasto_promedio_3m,
               fondo_emergencia_meses
        FROM gold.fact_comportamiento
    """
    return pd.read_sql(query, conn)


def build_disponible_pool(df_comportamiento: pd.DataFrame) -> dict[str, np.ndarray]:
    """Arma, por income_type, el pool real de 'disponible mensual'
    (ingreso_mensual - gasto_promedio_3m) que alimenta el bootstrap
    del Monte Carlo (ver decisión 3). Valores negativos se conservan
    a propósito (ver decisión 4) — no se filtran ni se truncan.
    """
    df = df_comportamiento.copy()
    df["disponible_mensual"] = df["ingreso_mensual"].astype(float) - df[
        "gasto_promedio_3m"
    ].astype(float)
    pool: dict[str, np.ndarray] = {}
    for income_type, grupo in df.groupby("income_type"):
        pool[income_type] = grupo["disponible_mensual"].to_numpy()
    return pool


def get_disponible_base(
    df_comportamiento: pd.DataFrame, record_id: str
) -> tuple[float, str]:
    """Disponible mensual actual y income_type del perfil simulado —
    solo para mostrarle al usuario su punto de partida; el bootstrap
    del Monte Carlo usa el POOL de su income_type (get_disponible_base
    no alimenta el ruido, ver simulate_goal)."""
    fila = df_comportamiento.loc[df_comportamiento["record_id"] == record_id]
    if fila.empty:
        raise ValueError(f"record_id no encontrado en fact_comportamiento: {record_id}")
    row = fila.iloc[0]
    disponible = float(row["ingreso_mensual"]) - float(row["gasto_promedio_3m"])
    return disponible, str(row["income_type"])


@dataclass
class SimulationResult:
    prob_exito: float
    prob_exito_ic95: tuple[
        float, float
    ]  # intervalo de confianza (bootstrap, scipy.stats)
    mes_meta_percentiles: (
        dict[int, float] | None
    )  # p10/p50/p90 del mes en que se alcanza la meta (None si nadie la alcanza)
    monto_final_percentiles: dict[
        int, float
    ]  # p10/p50/p90 del monto acumulado al final del horizonte
    n_simulaciones: int
    horizonte_meses: int
    monto_meta: float
    income_type: str
    disponible_base: float
    ahorro_extra_pct: float


def _validar_inputs(
    horizonte_meses: int, ahorro_extra_pct: float, monto_meta: float
) -> None:
    if not (HORIZONTE_MIN_MESES <= horizonte_meses <= HORIZONTE_MAX_MESES):
        raise ValueError(
            f"horizonte_meses debe estar entre {HORIZONTE_MIN_MESES} y "
            f"{HORIZONTE_MAX_MESES} (recibido: {horizonte_meses})."
        )
    if not (AHORRO_EXTRA_PCT_MIN <= ahorro_extra_pct <= AHORRO_EXTRA_PCT_MAX):
        raise ValueError(
            f"ahorro_extra_pct debe estar entre {AHORRO_EXTRA_PCT_MIN} y "
            f"{AHORRO_EXTRA_PCT_MAX} (recibido: {ahorro_extra_pct})."
        )
    if monto_meta <= 0:
        raise ValueError(f"monto_meta debe ser positivo (recibido: {monto_meta}).")


def simulate_goal(
    pool: dict[str, np.ndarray],
    income_type: str,
    disponible_base: float,
    monto_meta: float,
    horizonte_meses: int = HORIZONTE_DEFAULT_MESES,
    ahorro_extra_pct: float = 0.0,
    n_simulaciones: int = N_SIMULACIONES_DEFAULT,
    seed: int | None = None,
) -> SimulationResult:
    """Motor Monte Carlo genérico — sirve para los 3 escenarios
    (t068 renta, t069 auto, t070 tarjeta/cambio de empleo); ninguno
    de los 3 está codificado aquí a propósito, cada uno solo define
    qué `monto_meta` le pasa a esta función (t068-t070 son wiring, no
    lógica nueva de simulación).

    Para cada una de `n_simulaciones` trayectorias, se genera un
    disponible mensual para cada uno de los `horizonte_meses` meses
    tomando (con reemplazo) un valor real del pool de bootstrap del
    mismo income_type, ajustado por `ahorro_extra_pct` (decisión de
    ahorro que el usuario controla). Se acumula mes a mes y se mide en
    qué mes (si acaso) se cruza `monto_meta`.

    `disponible_base` SÍ entra al bootstrap, como ancla — se recentra
    el pool (ver más abajo). Corrección aplicada tras una corrida real
    (Sesión 34): la primera versión usaba el valor ABSOLUTO del pool
    como ruido, ignorando `disponible_base` para simular (solo se
    mostraba como referencia). Consecuencia verificada con datos
    reales: dos perfiles del mismo income_type con disponibles muy
    distintos (uno positivo, uno muy negativo) obtenían EXACTAMENTE
    el mismo resultado — el motor simulaba "alguien del segmento", no
    a la persona real. Corrección: se usan las DESVIACIONES del pool
    respecto a su propia media (`pool - pool.mean()`) como ruido, y
    se suman al `disponible_base` de este perfil. Se conserva la
    forma real de la variabilidad (sigue siendo bootstrap de datos
    reales, no una distribución inventada — decisión 3 intacta) pero
    la simulación queda anclada al punto de partida real de la
    persona, no al promedio de su income_type.
    """
    _validar_inputs(horizonte_meses, ahorro_extra_pct, monto_meta)

    bootstrap_pool = pool.get(income_type)
    if bootstrap_pool is None or len(bootstrap_pool) == 0:
        raise ValueError(
            f"No hay datos en el pool de bootstrap para income_type={income_type!r}."
        )

    rng = np.random.default_rng(seed)
    ajuste = 1.0 + ahorro_extra_pct

    # Desviaciones respecto a la media del pool (no el valor absoluto)
    # — así el ruido representa "cuánto varía la gente similar a mí
    # respecto a su propio promedio", no "cuánto gana la gente
    # similar a mí en términos absolutos" (eso ya lo aporta
    # disponible_base, que sí es de ESTA persona).
    desviaciones_pool = bootstrap_pool - bootstrap_pool.mean()

    # (n_simulaciones, horizonte_meses): cada celda es disponible_base
    # + una desviación real "prestada" de alguien del mismo income_type.
    ruido = rng.choice(
        desviaciones_pool, size=(n_simulaciones, horizonte_meses), replace=True
    )
    trayectorias = (disponible_base + ruido) * ajuste
    acumulado = np.cumsum(trayectorias, axis=1)

    alcanzo_meta = acumulado >= monto_meta
    alguna_vez_alcanzada = alcanzo_meta.any(axis=1)
    # Primer mes (1-indexado) en que se cruza la meta, NaN si nunca.
    mes_alcanzado = np.where(
        alguna_vez_alcanzada, alcanzo_meta.argmax(axis=1) + 1, np.nan
    )

    prob_exito = float(np.mean(alguna_vez_alcanzada))

    # Intervalo de confianza de la probabilidad de éxito vía bootstrap
    # (scipy.stats) sobre las n_simulaciones ya corridas — cuantifica
    # qué tan estable es el % de éxito reportado, no solo el punto.
    exitos_binarios = alguna_vez_alcanzada.astype(float)
    if exitos_binarios.std() == 0:
        # scipy.stats.bootstrap falla con varianza 0 (0% o 100% de
        # éxito en TODAS las simulaciones) — el intervalo colapsa al
        # propio valor, no es un error del cálculo.
        ic95 = (prob_exito, prob_exito)
    else:
        boot = stats.bootstrap(
            (exitos_binarios,), np.mean, confidence_level=0.95, random_state=rng
        )
        ic95 = (
            float(boot.confidence_interval.low),
            float(boot.confidence_interval.high),
        )

    mes_meta_percentiles = None
    meses_validos = mes_alcanzado[~np.isnan(mes_alcanzado)]
    if len(meses_validos) > 0:
        p10, p50, p90 = np.percentile(meses_validos, [10, 50, 90])
        mes_meta_percentiles = {10: float(p10), 50: float(p50), 90: float(p90)}

    monto_final = acumulado[:, -1]
    p10_m, p50_m, p90_m = np.percentile(monto_final, [10, 50, 90])
    monto_final_percentiles = {10: float(p10_m), 50: float(p50_m), 90: float(p90_m)}

    return SimulationResult(
        prob_exito=prob_exito,
        prob_exito_ic95=ic95,
        mes_meta_percentiles=mes_meta_percentiles,
        monto_final_percentiles=monto_final_percentiles,
        n_simulaciones=n_simulaciones,
        horizonte_meses=horizonte_meses,
        monto_meta=monto_meta,
        income_type=income_type,
        disponible_base=disponible_base,
        ahorro_extra_pct=ahorro_extra_pct,
    )


if __name__ == "__main__":
    # Sanity check manual (no es un test formal — t086 los cubre
    # aparte). Requiere las 4 variables de entorno de postgres-dw.
    conn = get_dw_connection()
    try:
        df_comportamiento = load_fact_comportamiento(conn)
    finally:
        conn.close()

    pool = build_disponible_pool(df_comportamiento)
    print("income_types en el pool:", list(pool.keys()))

    ejemplo_record_id = df_comportamiento["record_id"].iloc[0]
    disponible_base, income_type = get_disponible_base(
        df_comportamiento, ejemplo_record_id
    )
    print(
        f"record_id={ejemplo_record_id}: "
        f"disponible_base={disponible_base:.2f}, income_type={income_type}"
    )

    resultado = simulate_goal(
        pool=pool,
        income_type=income_type,
        disponible_base=disponible_base,
        monto_meta=20_000.0,
        horizonte_meses=12,
        ahorro_extra_pct=0.0,
        seed=42,
    )
    print(resultado)

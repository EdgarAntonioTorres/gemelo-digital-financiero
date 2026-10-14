"""Catálogo de Datos y Gobierno Funcional — Moneta (Alineado a DAMA-DMBOK).

Inventario de tablas, Data Owners, definiciones funcionales y diccionario de
campos.
"""

from __future__ import annotations

# Marco DAMA aplicado al proyecto
DAMA_DOMINIOS = {
    "Arquitectura y Almacenamiento": (
        "Arquitectura Lakehouse Medallion (Bronze/Silver/Gold) sobre MinIO "
        "en formato Parquet plano compactado (coalesce(4)), con capa analítica servida "
        "en PostgreSQL 15."
    ),
    "Gobierno y Data Ownership": (
        "Asignación explícita de propietarios por dominio funcional (Riesgo, "
        "Finanzas Personales, Operaciones) y control de acceso RBAC estricto."
    ),
    "Calidad de Datos": (
        "Framework automatizado con Great Expectations (8/8 reglas validadas), "
        "cuarentena de anomalías y políticas de 'cero eliminación de filas' mediante imputación por grupos."
    ),
    "Seguridad y Privacidad": (
        "Aislamiento de la IA mediante usuario 'assistant_ro' (solo SELECT en gold, "
        "transacción de solo lectura y timeout de 10s) + sanitización sintáctica."
    ),
    "Metadatos y Linaje": (
        "Trazabilidad completa con flags de auditoría (irfi_proxy_flag, age_synthetic_flag, "
        "outlier_flags) y derivaciones reproducibles vía RDD.zipWithIndex()."
    ),
}

# Inventario de Tablas y Entidades
INVENTARIO_TABLAS = {
    "gold.fact_kpi_perfil": {
        "nombre_tecnico": "gold.fact_kpi_perfil",
        "capa": "Gold (Base Analítica DW)",
        "formato_origen": "Parquet plano en s3a://gold/fact_kpi_perfil/",
        "ubicacion_dw": "postgres-dw / gemelo_digital / esquema gold",
        "grano": "1 fila por persona/registro (184,081 filas)",
        "data_owner": "Área de Riesgos y Modelos de Crédito",
        "custodio_tecnico": "Equipo de Data Engineering Moneta",
        "frecuencia_actualizacion": "Batch diario / Overwrite programado (Airflow)",
        "sensibilidad": "Interna / Confidencial (Uso analítico interno)",
        "descripcion_funcional": (
            "Consolida los indicadores maestros de salud financiera: Riesgo Financiero Inicial "
            "(IRFI), Capacidad de Ahorro (ICA) y la variable objetivo de impago crediticio (default). "
            "Sirve de base para el filtrado de perfiles, evaluación y entrenamiento de modelos ML."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "TEXT (PK)",
                "origen": "Sintético unificado (Silver Master)",
                "descripcion": "Identificador único prefijado por fuente (LD_, CR_, PFT_ + 7 dígitos).",
                "regla_o_calculo": "Generado con RDD.zipWithIndex(). Garantiza unicidad entre fuentes.",
            },
            {
                "campo": "fuente",
                "tipo": "TEXT",
                "origen": "Metadato de ingesta",
                "descripcion": "Dataset de procedencia del registro.",
                "regla_o_calculo": "'loan_default', 'credit_risk' o 'personal_finance_tracker'.",
            },
            {
                "campo": "segmento",
                "tipo": "TEXT (Nullable)",
                "origen": "Derivado de age_unificada",
                "descripcion": "Segmento etario del usuario.",
                "regla_o_calculo": (
                    "'early_career' si edad < 30 años; 'established' si >= 30. "
                    "Es NULL en loan_default porque esa fuente solo incluye bins decenales."
                ),
            },
            {
                "campo": "irfi",
                "tipo": "DOUBLE PRECISION",
                "origen": "Calculado (calculate_kpis.py)",
                "descripcion": "Índice de Riesgo Financiero Individual (0 a 1). Más alto = más riesgo.",
                "regla_o_calculo": (
                    "0.25*loan_percent_income + 0.15*(1-emp_stability) + 0.20*loan_int_rate_norm "
                    "+ 0.15*neg_amortization_flag + 0.10*(1-grade_score) + 0.15*(1-credit_hist_norm). "
                    "Excluye deliberadamente Credit_Score para no duplicar scores externos."
                ),
            },
            {
                "campo": "ica",
                "tipo": "DOUBLE PRECISION",
                "origen": "Calculado (calculate_kpis.py)",
                "descripcion": "Índice de Capacidad de Ahorro (0 a 1). Más alto = mayor margen de ahorro.",
                "regla_o_calculo": "1 - [0.5*loan_percent_income + 0.3*(1-emp_stability) + 0.2*housing_penalty].",
            },
            {
                "campo": "default_flag_unificada",
                "tipo": "DOUBLE PRECISION (Nullable)",
                "origen": "Loan Default (Status) / Credit Risk (loan_status)",
                "descripcion": "Indicador de incumplimiento histórico (1.0 = Default, 0.0 = Al corriente).",
                "regla_o_calculo": "Unión directa. Queda NULL en Personal Finance Tracker al ser no-crediticio.",
            },
            {
                "campo": "irfi_proxy_flag",
                "tipo": "BOOLEAN",
                "origen": "Trazabilidad de linaje",
                "descripcion": "Bandera de uso de variables sustitutas (proxies).",
                "regla_o_calculo": "False en Credit Risk (nativa); True en Loan Default y PFT al requerir proxies.",
            },
            {
                "campo": "ica_proxy_flag",
                "tipo": "BOOLEAN",
                "origen": "Trazabilidad de linaje",
                "descripcion": "Bandera de uso de proxies para el cálculo del ICA.",
                "regla_o_calculo": "Idéntico a irfi_proxy_flag por compartir componentes estructurales.",
            },
        ],
    },
    "gold.fact_comportamiento": {
        "nombre_tecnico": "gold.fact_comportamiento",
        "capa": "Gold (Base Analítica DW)",
        "formato_origen": "Parquet plano en s3a://gold/fact_comportamiento/",
        "ubicacion_dw": "postgres-dw / gemelo_digital / esquema gold",
        "grano": "1 fila por persona de Personal Finance Tracker (3,000 filas)",
        "data_owner": "Área de Finanzas Personales y Comportamiento",
        "custodio_tecnico": "Equipo de Data Engineering Moneta",
        "frecuencia_actualizacion": "Batch diario / Overwrite programado (Airflow)",
        "sensibilidad": "Interna (Métricas transaccionales agregadas)",
        "descripcion_funcional": (
            "Representa los hábitos financieros reales y transaccionales del usuario joven: "
            "volumen de gasto mensual, capacidad de colchón ante emergencias, intensidad de suscripciones "
            "y carga de endeudamiento sobre los ingresos."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "TEXT (PK)",
                "origen": "Personal Finance Tracker",
                "descripcion": "Identificador único con prefijo PFT_ (conecta con fact_kpi_perfil).",
                "regla_o_calculo": "Asignado en Silver Master vía RDD.zipWithIndex().",
            },
            {
                "campo": "fuente",
                "tipo": "TEXT",
                "origen": "Constante de diseño",
                "descripcion": "Fuente de origen del registro.",
                "regla_o_calculo": "Siempre 'personal_finance_tracker'.",
            },
            {
                "campo": "segmento",
                "tipo": "TEXT (Nullable)",
                "origen": "Silver Master (age_unificada)",
                "descripcion": "Segmento etario de madurez inicial.",
                "regla_o_calculo": "'early_career' (<30 años) o 'established' (>=30 años).",
            },
            {
                "campo": "income_type",
                "tipo": "TEXT",
                "origen": "Personal Finance Tracker (income_type)",
                "descripcion": "Modalidad de obtención de ingresos.",
                "regla_o_calculo": "Valores categóricos: 'Salary', 'Mixed' o 'Freelance'.",
            },
            {
                "campo": "ingreso_mensual",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (monthly_income)",
                "descripcion": "Ingreso mensual promedio neto en USD.",
                "regla_o_calculo": "Snapshot transversal observado.",
            },
            {
                "campo": "gasto_promedio_3m",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (monthly_expense_total)",
                "descripcion": "Gasto mensual representativo en USD.",
                "regla_o_calculo": (
                    "Aproximación transversal documentada: al ser PFT un corte transversal y no panel, "
                    "equivale a monthly_expense_total tal cual, sin forzar series sintéticas."
                ),
            },
            {
                "campo": "varianza_ingreso_segmento",
                "tipo": "DOUBLE PRECISION",
                "origen": "Calculado (Window por income_type)",
                "descripcion": "Volatilidad de ingresos observada entre pares del mismo tipo de ingreso.",
                "regla_o_calculo": "Varianza poblacional var_pop(monthly_income) dentro de cada income_type.",
            },
            {
                "campo": "ratio_endeudamiento",
                "tipo": "NUMERIC(10,4)",
                "origen": "Personal Finance Tracker (debt_to_income_ratio)",
                "descripcion": "Proporción del ingreso mensual comprometida en pago de deudas (DTI).",
                "regla_o_calculo": "Nativa del dataset (0.1 a 0.6). Clave para definir el Nivel de Madurez.",
            },
            {
                "campo": "alerta_fraude",
                "tipo": "BOOLEAN",
                "origen": "Personal Finance Tracker (fraud_flag)",
                "descripcion": "Señal preventiva de anomalía transaccional o posible fraude.",
                "regla_o_calculo": "Casteo booleano explícito de fraud_flag (1=True, 0=False).",
            },
            {
                "campo": "suscripciones_por_1000_ingreso",
                "tipo": "NUMERIC(38,21)",
                "origen": "Calculado (subscription_services / ingreso)",
                "descripcion": "Tasa de intensidad de suscripciones activas por cada $1,000 USD de ingreso.",
                "regla_o_calculo": (
                    "subscription_services / (monthly_income / 1000). Evita inventar un precio en USD "
                    "por servicio dado que la fuente registra un conteo entero (1 a 9)."
                ),
            },
            {
                "campo": "fondo_emergencia_meses",
                "tipo": "NUMERIC(38,20)",
                "origen": "Calculado (emergency_fund / gasto)",
                "descripcion": "Meses de subsistencia cubiertos por el fondo de emergencia actual.",
                "regla_o_calculo": (
                    "emergency_fund / monthly_expense_total. Benchmark industrial recomendado: 3 a 6 meses. "
                    "Media observada en jóvenes: 0.37 meses."
                ),
            },
        ],
    },
    "gold.fact_perfil_detalle": {
        "nombre_tecnico": "gold.fact_perfil_detalle",
        "capa": "Gold (Base Analítica DW)",
        "formato_origen": "Tabla relacional sembrada (config/create-fact-perfil-detalle.sql)",
        "ubicacion_dw": "postgres-dw / gemelo_digital / esquema gold",
        "grano": "Perfiles arquetípicos de demostración (Ana Caso 1 PFT_0000636 y Ana madura PFT_0002539)",
        "data_owner": "Área de Innovación & Producto Digital",
        "custodio_tecnico": "Equipo de Data Engineering Moneta",
        "frecuencia_actualizacion": "Aditiva e idempotente bajo demanda",
        "sensibilidad": "Uso demostrativo y auditoría en vivo",
        "descripcion_funcional": (
            "Provee el desglose presupuestario granular para la experiencia conversacional "
            "de Centavo y el panel 'Lo que tengo hoy', incluyendo metas de ahorro, inversión mensual, "
            "vivienda y montos declarados con validación estricta de huella (hash)."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "TEXT (PK)",
                "origen": "Silver PFT (localizado por huella de valores)",
                "descripcion": "Identificador del perfil arquetípico.",
                "regla_o_calculo": "PFT_0000636 (Ana Primeriza) / PFT_0002539 (Ana Más Madura).",
            },
            {
                "campo": "meta_ahorro_mensual",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (budget_goal)",
                "descripcion": "Objetivo de ahorro monetario fijado para el mes en USD.",
                "regla_o_calculo": "Equivale funcionalmente a la meta de ahorro esperada.",
            },
            {
                "campo": "ahorro_del_mes",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (actual_savings)",
                "descripcion": "Ahorro real logrado al corte del mes en USD.",
                "regla_o_calculo": "Verificado como max(0, ingreso_mensual - gasto_promedio_3m).",
            },
            {
                "campo": "meta_ahorro_cumplida",
                "tipo": "BOOLEAN",
                "origen": "Personal Finance Tracker (savings_goal_met)",
                "descripcion": "Indica si se alcanzó la meta mensual.",
                "regla_o_calculo": "True si ahorro_del_mes >= meta_ahorro_mensual.",
            },
            {
                "campo": "inversion_mensual",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (investment_amount)",
                "descripcion": "Aportación mensual recurrente a instrumentos de inversión en USD.",
                "regla_o_calculo": "Inferencia de escala mensual basada en la mediana poblacional (~10% ingreso).",
            },
            {
                "campo": "fondo_emergencia_usd",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (emergency_fund)",
                "descripcion": "Saldo acumulado en el fondo para emergencias en USD.",
                "regla_o_calculo": "Monto directo verificado contra la fuente.",
            },
            {
                "campo": "proporcion_esencial",
                "tipo": "NUMERIC(6,4)",
                "origen": "Calculado",
                "descripcion": "Proporción del gasto declarado correspondiente a necesidades esenciales.",
                "regla_o_calculo": (
                    "essential_spending / (essential_spending + discretionary_spending). "
                    "Se almacena como ratio porque los montos no suman el gasto total en 97% de las filas."
                ),
            },
            {
                "campo": "gasto_esencial_declarado",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (essential_spending)",
                "descripcion": "Monto de gasto esencial declarado en USD.",
                "regla_o_calculo": "Monto nominal directo.",
            },
            {
                "campo": "gasto_discrecional_declarado",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (discretionary_spending)",
                "descripcion": "Monto de gasto variable/estilo de vida declarado en USD.",
                "regla_o_calculo": "Monto nominal directo.",
            },
            {
                "campo": "vivienda_mensual",
                "tipo": "NUMERIC(18,2)",
                "origen": "Personal Finance Tracker (rent_or_mortgage)",
                "descripcion": "Gasto mensual de vivienda (renta o cuota) en USD.",
                "regla_o_calculo": "Subcomponente del gasto esencial verificado.",
            },
            {
                "campo": "edad_ilustrativa",
                "tipo": "INTEGER",
                "origen": "Derivada (age_synthetic_flag = True)",
                "descripcion": "Edad ilustrativa coherente con el score de madurez.",
                "regla_o_calculo": "Generada con ruido determinístico a partir del maturity_score.",
            },
            {
                "campo": "huella_*",
                "tipo": "NUMERIC",
                "origen": "Validación cruzada",
                "descripcion": "Huellas de auditoría (ingreso, gasto y endeudamiento).",
                "regla_o_calculo": "Si el pipeline reordena record_id y no coinciden, la transacción aborta.",
            },
        ],
    },
    "operational.pipeline_alerts": {
        "nombre_tecnico": "operational.pipeline_alerts",
        "capa": "Operational (Auditoría & Observabilidad)",
        "formato_origen": "PostgreSQL nativo",
        "ubicacion_dw": "postgres-dw / gemelo_digital / esquema operational",
        "grano": "1 fila por evento/incidente registrado",
        "data_owner": "Área de Operaciones de Datos y Plataforma (DataOps)",
        "custodio_tecnico": "Administrador de Apache Airflow",
        "frecuencia_actualizacion": "Tiempo real ante callbacks de DAGs",
        "sensibilidad": "Uso técnico interno de infraestructura",
        "descripcion_funcional": (
            "Bitácora histórica persistente de fallos en tareas, reintentos de pipeline "
            "y violaciones de SLAs contractuales de tiempo de cómputo en Apache Airflow."
        ),
        "campos": [
            {
                "campo": "id",
                "tipo": "SERIAL (PK)",
                "origen": "PostgreSQL",
                "descripcion": "Identificador secuencial del incidente.",
                "regla_o_calculo": "Autoincremental.",
            },
            {
                "campo": "alert_timestamp",
                "tipo": "TIMESTAMP",
                "origen": "Callback Airflow",
                "descripcion": "Fecha y hora exacta del suceso.",
                "regla_o_calculo": "now() al disparar el evento.",
            },
            {
                "campo": "alert_type",
                "tipo": "VARCHAR(50)",
                "origen": "dags/alerts.py",
                "descripcion": "Categoría de la alerta operativa.",
                "regla_o_calculo": "'TASK_FAILURE', 'SLA_MISS' o 'PIPELINE_ERROR'.",
            },
            {
                "campo": "dag_id / task_id",
                "tipo": "VARCHAR(200)",
                "origen": "Contexto de ejecución Airflow",
                "descripcion": "DAG y tarea afectada.",
                "regla_o_calculo": "Identificador técnico en Airflow.",
            },
            {
                "campo": "severity",
                "tipo": "VARCHAR(20)",
                "origen": "dags/alerts.py",
                "descripcion": "Nivel de severidad operacional.",
                "regla_o_calculo": "'CRITICAL' (requiere acción/rollback) o 'WARNING' (informativo).",
            },
            {
                "campo": "message / details",
                "tipo": "TEXT / JSONB",
                "origen": "Traceback / Métricas",
                "descripcion": "Detalle técnico, traceback y parámetros de ejecución del incidente.",
                "regla_o_calculo": "Cuerpo del error formateado en JSON.",
            },
        ],
    },
}

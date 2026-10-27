"""Catálogo de Datos y Gobierno Funcional — Moneta (Alineado a DAMA-DMBOK).

Inventario de tablas, Data Owners, definiciones funcionales y diccionario de campos
con redacción accesible para todo público y desglose de siglas.
"""

from __future__ import annotations

# Marco DAMA aplicado al proyecto
DAMA_DOMINIOS = {
    "Arquitectura y Almacenamiento": (
        "Arquitectura Lakehouse Medallion (organizada en capas de madurez Bronze, "
        "Silver y Gold) montada sobre MinIO en formato Parquet plano compactado "
        "(coalesce(4)), con la capa analítica final servida en PostgreSQL 15."
    ),
    "Gobierno y Data Ownership": (
        "Asignación explícita de líderes responsables por dominio funcional (Riesgo Crediticio, "
        "Finanzas Personales, Operaciones de Plataforma) y control de acceso estricto basado en roles (RBAC)."
    ),
    "Calidad de Datos": (
        "Framework automatizado con Great Expectations (8 de 8 reglas operativas superadas), "
        "mecanismo de aislamiento preventivo para anomalías y políticas de cero eliminación "
        "mediante imputación estadística por grupos afines."
    ),
    "Seguridad y Privacidad": (
        "Aislamiento preventivo para agentes de Inteligencia Artificial mediante un usuario exclusivo "
        "de solo lectura ('assistant_ro') con permisos limitados a SELECT en Gold, transacciones de solo lectura "
        "y un tiempo máximo de espera de 10 segundos por consulta."
    ),
    "Metadatos y Linaje": (
        "Trazabilidad de punta a punta con indicadores de auditoría técnica "
        "(irfi_proxy_flag, age_synthetic_flag, outlier_flags) y derivación determinista "
        "de identificadores únicos mediante transformaciones reproducibles."
    ),
}

# Inventario de Tablas y Entidades
INVENTARIO_TABLAS = {
    "gold.fact_kpi_perfil": {
        "nombre_tecnico": "gold.fact_kpi_perfil",
        "capa": "Gold (Base Analítica de Datos Listos para Consumo)",
        "formato_origen": "Parquet plano en s3a://gold/fact_kpi_perfil/",
        "ubicacion_dw": "postgres-dw / base gemelo_digital / esquema gold",
        "grano": "Una sola fila por persona o registro evaluado (184,081 filas en total)",
        "data_owner": "Área de Riesgos y Modelos de Crédito",
        "custodio_tecnico": "Equipo de Ingeniería de Datos Moneta",
        "frecuencia_actualizacion": "Procesamiento por lotes diario con reemplazo total programado en Apache Airflow",
        "sensibilidad": "Información Interna y Confidencial (Uso analítico interno)",
        "descripcion_funcional": (
            "Consolida los indicadores maestros de salud financiera: el Índice de Riesgo Financiero "
            "Individual (IRFI), la Capacidad de Ahorro (ICA) y la variable objetivo de impago crediticio (default). "
            "Sirve de base para clasificar perfiles, evaluar capacidades y alimentar modelos de machine learning."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "Texto (Identificador Único - Clave Primaria)",
                "origen": "Generado en la capa intermedia unificada (Silver Master)",
                "descripcion": (
                    "Identificador alfanumérico único e irrepetible para cada persona dentro de la plataforma. "
                    "Inicia con un prefijo que indica de qué base de datos proviene (LD_ para Préstamos con Impago, "
                    "CR_ para Riesgo de Crédito y PFT_ para Seguimiento de Finanzas Personales) seguido de 7 dígitos."
                ),
                "regla_o_calculo": "Asignado de manera secuencial y determinista en la capa Silver para evitar colisiones entre fuentes.",
            },
            {
                "campo": "fuente",
                "tipo": "Texto",
                "origen": "Etiqueta técnica asignada durante la extracción de datos",
                "descripcion": (
                    "Nombre de la base de datos o archivo original de donde provienen los datos del usuario. "
                    "Permite distinguir si el registro viene de historias de crédito bancario tradicional o de registros "
                    "cotidianos de ingresos y gastos de finanzas personales."
                ),
                "regla_o_calculo": "Toma los valores exactos: 'loan_default' (préstamos con mora), 'credit_risk' (historial crediticio) o 'personal_finance_tracker' (gastos personales).",
            },
            {
                "campo": "segmento",
                "tipo": "Texto (Opcional o Vacío)",
                "origen": "Derivado a partir de la edad estandarizada del usuario",
                "descripcion": (
                    "Clasificación de la etapa laboral del usuario según su edad. Ayuda a ofrecer recomendaciones "
                    "distintas a quienes recién comienzan su vida productiva frente a quienes ya tienen más trayectoria laboral."
                ),
                "regla_o_calculo": (
                    "Se asigna 'early_career' (etapa inicial) si la edad es menor a 30 años, y 'established' (etapa consolidada) "
                    "si tiene 30 años o más. Queda en blanco (NULL) en loan_default porque esa fuente solo registra rangos de edad de 10 años."
                ),
            },
            {
                "campo": "irfi",
                "tipo": "Número Decimal Continuo (0.0 a 1.0)",
                "origen": "Calculado en la tarea calculate_kpis.py",
                "descripcion": (
                    "Índice de Riesgo Financiero Individual (IRFI). Es una calificación de 0 a 1 que mide la probabilidad "
                    "de que la persona enfrente problemas de liquidez o endeudamiento excesivo. Un valor más alto significa mayor riesgo."
                ),
                "regla_o_calculo": (
                    "Suma ponderada de factores: 25% porcentaje de cuota sobre ingresos, 15% inestabilidad laboral, "
                    "20% tasa de interés normalizada, 15% amortización negativa, 10% nivel de calificación crediticia "
                    "y 15% historial crediticio. Se excluye el puntaje de buró externo para evitar duplicar mediciones."
                ),
            },
            {
                "campo": "ica",
                "tipo": "Número Decimal Continuo (0.0 a 1.0)",
                "origen": "Calculado en la tarea calculate_kpis.py",
                "descripcion": (
                    "Índice de Capacidad de Ahorro (ICA). Es un puntaje de 0 a 1 que refleja cuánto margen de maniobra tiene "
                    "el usuario para ahorrar e invertir al final del mes. Mientras más cercano esté a 1, mayor es su holgura."
                ),
                "regla_o_calculo": "Calculado como: 1 - [50% carga del préstamo + 30% inestabilidad de empleo + 20% penalización por gastos de vivienda].",
            },
            {
                "campo": "default_flag_unificada",
                "tipo": "Número Decimal Binario (1.0, 0.0 o Vacío)",
                "origen": "Columna Status en Loan Default y loan_status en Credit Risk",
                "descripcion": (
                    "Indicador que señala si la persona cayó en incumplimiento de pago (mora crediticia) en el pasado. "
                    "Un valor de 1.0 indica que no pagó a tiempo, y 0.0 indica que se mantuvo al corriente con sus compromisos."
                ),
                "regla_o_calculo": "Unión directa de los históricos crediticios. Queda en blanco (NULL) para registros de finanzas personales al no ser contratos de crédito.",
            },
            {
                "campo": "irfi_proxy_flag",
                "tipo": "Booleano (Verdadero o Falso)",
                "origen": "Etiqueta de linaje y auditoría de datos",
                "descripcion": (
                    "Bandera de auditoría técnica que advierte si para calcular el riesgo (IRFI) se tuvieron que estimar variables "
                    "aproximadas (variables sustitutas o proxies) debido a que la fuente original no contaba con todas las mediciones exactas."
                ),
                "regla_o_calculo": "Es Falso (False) para Credit Risk porque tiene todos los datos de origen; es Verdadero (True) para Loan Default y finanzas personales por requerir aproximaciones.",
            },
            {
                "campo": "ica_proxy_flag",
                "tipo": "Booleano (Verdadero o Falso)",
                "origen": "Etiqueta de linaje y auditoría de datos",
                "descripcion": (
                    "Bandera de auditoría técnica que advierte si para estimar la capacidad de ahorro (ICA) se utilizaron variables "
                    "aproximadas o derivadas debido a la falta de información directa de gastos de vivienda o estabilidad laboral."
                ),
                "regla_o_calculo": "Sigue idéntico valor que irfi_proxy_flag ya que ambos índices comparten las mismas variables estructurales de partida.",
            },
        ],
    },
    "gold.fact_comportamiento": {
        "nombre_tecnico": "gold.fact_comportamiento",
        "capa": "Gold (Base Analítica de Datos Listos para Consumo)",
        "formato_origen": "Parquet plano en s3a://gold/fact_comportamiento/",
        "ubicacion_dw": "postgres-dw / base gemelo_digital / esquema gold",
        "grano": "Una sola fila por cada persona registrada en la encuesta de finanzas personales (3,000 filas)",
        "data_owner": "Área de Finanzas Personales y Comportamiento Financiero",
        "custodio_tecnico": "Equipo de Ingeniería de Datos Moneta",
        "frecuencia_actualizacion": "Procesamiento por lotes diario con reemplazo total programado en Apache Airflow",
        "sensibilidad": "Información Interna (Métricas transaccionales y de comportamiento agregadas)",
        "descripcion_funcional": (
            "Representa los hábitos financieros cotidianos de usuarios jóvenes: cuánto dinero ingresan, cuánto "
            "gastan al mes, cuántos meses sobrevivirían ante una emergencia, su nivel de endeudamiento y sus suscripciones activas."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "Texto (Identificador Único - Clave Primaria)",
                "origen": "Encuesta de Seguimiento de Finanzas Personales (Personal Finance Tracker)",
                "descripcion": (
                    "Código único e individual que identifica a cada usuario dentro del estudio de hábitos cotidianos. "
                    "Empieza siempre con las letras PFT_ para enlazar de manera directa con su perfil en la tabla fact_kpi_perfil."
                ),
                "regla_o_calculo": "Asignado en la capa Silver mediante numeración correlativa garantizando unicidad total.",
            },
            {
                "campo": "fuente",
                "tipo": "Texto",
                "origen": "Constante de diseño de pipeline",
                "descripcion": (
                    "Identifica el dataset del cual se extraen estos datos de comportamiento transaccional. "
                    "Permite asegurar que los indicadores mostrados provienen de personas reales encuestadas sobre sus hábitos de gasto."
                ),
                "regla_o_calculo": "Contiene siempre el texto fijo 'personal_finance_tracker'.",
            },
            {
                "campo": "segmento",
                "tipo": "Texto (Opcional o Vacío)",
                "origen": "Capa Silver Master derivada de la edad unificada",
                "descripcion": (
                    "Grupo etario y laboral al que pertenece la persona según su edad. Se utiliza para comparar "
                    "los hábitos de ahorro y gasto entre profesionales jóvenes y usuarios con mayor madurez profesional."
                ),
                "regla_o_calculo": "'early_career' si tiene menos de 30 años, o 'established' si tiene 30 años cumplidos o más.",
            },
            {
                "campo": "income_type",
                "tipo": "Texto",
                "origen": "Encuesta de Finanzas Personales (columna income_type)",
                "descripcion": (
                    "Modalidad principal mediante la cual la persona genera sus ingresos económicos cada mes. "
                    "Permite segmentar a quienes reciben un sueldo fijo respecto a quienes tienen ingresos variables."
                ),
                "regla_o_calculo": "Clasificado en tres categorías posibles: 'Salary' (empleado con sueldo fijo), 'Freelance' (independiente) o 'Mixed' (mixto o combinado).",
            },
            {
                "campo": "ingreso_mensual",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna monthly_income)",
                "descripcion": (
                    "Monto neto promedio de dinero en efectivo que la persona percibe durante un mes después de impuestos. "
                    "Representa la base económica total disponible para vivir, pagar deudas, ahorrar e invertir."
                ),
                "regla_o_calculo": "Valor monetario directo registrado en la encuesta al momento del corte analítico.",
            },
            {
                "campo": "gasto_promedio_3m",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna monthly_expense_total)",
                "descripcion": (
                    "Monto promedio de dinero que el usuario gasta mensualmente para cubrir todas sus necesidades "
                    "personales, estilo de vida, vivienda y servicios. Sirve como referencia base de su nivel de gasto de vida."
                ),
                "regla_o_calculo": "Equivale al gasto total mensual observado tal como fue declarado por el usuario en el corte transversal.",
            },
            {
                "campo": "varianza_ingreso_segmento",
                "tipo": "Número Decimal Estadístico",
                "origen": "Cálculo analítico por grupos de tipo de ingreso",
                "descripcion": (
                    "Medida estadística que refleja qué tan dispersos o volátiles son los ingresos entre personas "
                    "que tienen el mismo tipo de trabajo (por ejemplo, entre todos los trabajadores independientes o 'Freelance')."
                ),
                "regla_o_calculo": "Calculado mediante la función de varianza poblacional estadística var_pop(monthly_income) agrupada por tipo de ingreso.",
            },
            {
                "campo": "ratio_endeudamiento",
                "tipo": "Porcentaje Decimal (0.0 a 1.0)",
                "origen": "Encuesta de Finanzas Personales (columna debt_to_income_ratio)",
                "descripcion": (
                    "Porcentaje o proporción de los ingresos mensuales totales que el usuario tiene comprometido para "
                    "el pago de deudas previas (también conocido internacionalmente como DTI: Debt-to-Income). Un ratio alto reduce la libertad financiera."
                ),
                "regla_o_calculo": "Proporción original entre 0.10 y 0.60. Un valor de 0.30 significa que el 30% del ingreso se va únicamente en saldar deudas.",
            },
            {
                "campo": "alerta_fraude",
                "tipo": "Booleano (Verdadero o Falso)",
                "origen": "Encuesta de Finanzas Personales (columna fraud_flag)",
                "descripcion": (
                    "Indicador preventivo de seguridad que se activa cuando los movimientos monetarios o transferencias "
                    "del usuario presentan inconsistencias, movimientos atípicos o sospechas de actividad fraudulenta."
                ),
                "regla_o_calculo": "Transformación directa del campo numérico de auditoría: Verdadero (True) si es 1, Falso (False) si es 0.",
            },
            {
                "campo": "suscripciones_por_1000_ingreso",
                "tipo": "Número Decimal Continuo",
                "origen": "Cálculo analítico derivado de la cantidad de suscripciones y el ingreso",
                "descripcion": (
                    "Métrica que indica cuántos servicios digitales o suscripciones activas (como streaming, música o gimnasio) "
                    "mantiene contratadas la persona por cada mil dólares de ingresos que percibe al mes."
                ),
                "regla_o_calculo": "Calculado como: cantidad de suscripciones activas dividida entre (ingreso mensual neto / 1000).",
            },
            {
                "campo": "fondo_emergencia_meses",
                "tipo": "Número Decimal Continuo",
                "origen": "Cálculo analítico derivado del fondo de reserva sobre el gasto",
                "descripcion": (
                    "Cantidad estimada de meses que el usuario podría seguir cubriendo sus gastos indispensables de vida "
                    "utilizando exclusivamente su dinero de reserva, en caso de quedarse sin ningún ingreso el día de hoy."
                ),
                "regla_o_calculo": (
                    "Calculado como: fondo de reserva acumulado dividido entre el gasto mensual total. El estándar de la industria "
                    "recomienda tener entre 3 y 6 meses; el promedio real detectado en este grupo de usuarios jóvenes es de apenas 0.37 meses."
                ),
            },
        ],
    },
    "gold.fact_perfil_detalle": {
        "nombre_tecnico": "gold.fact_perfil_detalle",
        "capa": "Gold (Base Analítica de Datos Listos para Consumo)",
        "formato_origen": "Tabla relacional sembrada (config/create-fact-perfil-detalle.sql)",
        "ubicacion_dw": "postgres-dw / base gemelo_digital / esquema gold",
        "grano": "Perfiles arquetípicos de demostración (Ana Primeriza PFT_0000636 y Ana Madura PFT_0002539)",
        "data_owner": "Área de Innovación y Producto Digital",
        "custodio_tecnico": "Equipo de Ingeniería de Datos Moneta",
        "frecuencia_actualizacion": "Actualización bajo demanda con validación estricta de coherencia previa",
        "sensibilidad": "Uso demostrativo y auditoría en tiempo real para sesiones de mentoría",
        "descripcion_funcional": (
            "Provee el desglose presupuestario granular para la experiencia conversacional del asistente "
            "financiero inteligente y el panel de control personal, incluyendo metas de ahorro mensuales, inversiones y vivienda."
        ),
        "campos": [
            {
                "campo": "record_id",
                "tipo": "Texto (Identificador Único - Clave Primaria)",
                "origen": "Localizado con precisión por huella de valores en la encuesta de finanzas",
                "descripcion": (
                    "Código único asignado a los perfiles modelo utilizados en la aplicación demostrativa. "
                    "PFT_0000636 corresponde a la usuaria 'Ana Primeriza' (nivel de inicio) y PFT_0002539 a 'Ana Consolidada' (nivel más avanzado)."
                ),
                "regla_o_calculo": "Identificador exacto verificado mediante huella de gasto, ingreso y ratio de deuda.",
            },
            {
                "campo": "meta_ahorro_mensual",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna budget_goal)",
                "descripcion": (
                    "Cantidad monetaria fijada como objetivo personal que el usuario se propuso ahorrar durante el mes en curso. "
                    "Sirve para monitorear el grado de disciplina presupuestaria del usuario frente a su plan inicial."
                ),
                "regla_o_calculo": "Equivale a la meta monetaria registrada en el presupuesto inicial del participante.",
            },
            {
                "campo": "ahorro_del_mes",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna actual_savings)",
                "descripcion": (
                    "Monto real de dinero que le quedó al usuario a fin de mes luego de descontar todos sus gastos "
                    "efectivos de su ingreso disponible. Corresponde al dinero verdaderamente ahorrado."
                ),
                "regla_o_calculo": "Calculado y verificado como el excedente positivo: ingreso mensual menos gasto mensual total.",
            },
            {
                "campo": "meta_ahorro_cumplida",
                "tipo": "Booleano (Verdadero o Falso)",
                "origen": "Encuesta de Finanzas Personales (columna savings_goal_met)",
                "descripcion": (
                    "Indica de forma clara si el usuario logró cumplir o superar su meta mensual de ahorro programada. "
                    "Permite al asistente felicitar al usuario o brindarle consejos correctivos de ahorro."
                ),
                "regla_o_calculo": "Es Verdadero (True) si el ahorro del mes fue igual o mayor a la meta propuesta; Falso (False) si quedó por debajo.",
            },
            {
                "campo": "inversion_mensual",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna investment_amount)",
                "descripcion": (
                    "Cantidad de dinero que la persona destina mensualmente hacia instrumentos de inversión financiera "
                    "(como fondos indexados, acciones o depósitos a plazo) para hacer crecer su patrimonio a largo plazo."
                ),
                "regla_o_calculo": "Inferencia de escala mensual alineada a la mediana de los usuarios observados (~10% del ingreso).",
            },
            {
                "campo": "fondo_emergencia_usd",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna emergency_fund)",
                "descripcion": (
                    "Monto total acumulado y disponible en efectivo o en cuenta líquida que el usuario reserva exclusivamente "
                    "para afrontar imprevistos de fuerza mayor, tales como emergencias médicas o pérdida de empleo."
                ),
                "regla_o_calculo": "Valor monetario en dólares verificado directamente contra la fuente de datos original.",
            },
            {
                "campo": "proporcion_esencial",
                "tipo": "Porcentaje Decimal (0.0 a 1.0)",
                "origen": "Cálculo analítico derivado de las declaraciones de gasto",
                "descripcion": (
                    "Porcentaje que representan los gastos estrictamente necesarios para subsistir (como comida y vivienda) "
                    "respecto a la suma de los gastos esenciales y los gastos prescindibles o de ocio declarados."
                ),
                "regla_o_calculo": "Calculado como: gasto esencial / (gasto esencial + gasto discrecional). Se almacena como proporción porque en el 97% de los casos estos montos no suman exactamente el gasto total.",
            },
            {
                "campo": "gasto_esencial_declarado",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna essential_spending)",
                "descripcion": (
                    "Monto de dinero que la persona reporta destinar a cubrir sus necesidades básicas e ineludibles "
                    "(alimentación, salud, servicios básicos y transporte indispensable)."
                ),
                "regla_o_calculo": "Monto nominal directo reportado por el usuario en su cuestionario presupuestario.",
            },
            {
                "campo": "gasto_discrecional_declarado",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna discretionary_spending)",
                "descripcion": (
                    "Monto monetario que el usuario afirma gastar en compras no esenciales, entretenimiento personal, "
                    "salidas a comer fuera, ropa y actividades recreativas."
                ),
                "regla_o_calculo": "Monto nominal directo declarado por el participante de la encuesta.",
            },
            {
                "campo": "vivienda_mensual",
                "tipo": "Moneda Decimal (Dólares Estadounidenses USD)",
                "origen": "Encuesta de Finanzas Personales (columna rent_or_mortgage)",
                "descripcion": (
                    "Pago mensual recurrente destinado a cubrir el techo habitacional, ya sea por concepto de alquiler "
                    "o por la cuota mensual de una hipoteca. Constituye la porción más relevante del gasto esencial."
                ),
                "regla_o_calculo": "Monto monetario reportado y verificado como un subcomponente del gasto esencial.",
            },
            {
                "campo": "edad_ilustrativa",
                "tipo": "Número Entero (Años)",
                "origen": "Derivado sintético con etiqueta de auditoría (age_synthetic_flag = True)",
                "descripcion": (
                    "Edad representativa asignada al perfil arquetípico para contextualizar las recomendaciones "
                    "educativas del asistente financiero virtual sin exponer datos privados de personas reales."
                ),
                "regla_o_calculo": "Generada de manera determinista a partir de los patrones de madurez financiera del perfil.",
            },
            {
                "campo": "huella_*",
                "tipo": "Número Decimal de Validación",
                "origen": "Mecanismo interno de integridad y auditoría cruzada",
                "descripcion": (
                    "Conjunto de valores de control (huella de ingreso, huella de gasto y huella de endeudamiento) "
                    "que garantizan que el perfil arquetípico no se confunda con otra fila si los identificadores se recalculan."
                ),
                "regla_o_calculo": "Si tras una recarga del pipeline los datos no coinciden exactamente con la huella registrada, el sistema cancela la operación automáticamente.",
            },
        ],
    },
    "operational.pipeline_alerts": {
        "nombre_tecnico": "operational.pipeline_alerts",
        "capa": "Operational (Auditoría Técnica y Observabilidad de Infraestructura)",
        "formato_origen": "Tabla relacional nativa en PostgreSQL",
        "ubicacion_dw": "postgres-dw / base gemelo_digital / esquema operational",
        "grano": "Una fila por cada evento de error o advertencia registrado durante la ejecución de los pipelines",
        "data_owner": "Área de Operaciones de Datos y Plataforma (DataOps)",
        "custodio_tecnico": "Administrador de Orquestación de Flujos (Apache Airflow)",
        "frecuencia_actualizacion": "Registro en tiempo real cuando se dispara un evento o fallo en las tareas",
        "sensibilidad": "Uso técnico interno de infraestructura y soporte",
        "descripcion_funcional": (
            "Bitácora histórica y permanente de fallos en tareas, reintentos y violaciones a los Acuerdos "
            "de Nivel de Servicio (SLAs: tiempos contractuales máximos de ejecución fijados en 4 o 5 minutos) en Apache Airflow."
        ),
        "campos": [
            {
                "campo": "id",
                "tipo": "Número Entero Autoincremental (Clave Primaria)",
                "origen": "Generador secuencial interno de PostgreSQL",
                "descripcion": (
                    "Número correlativo y único asignado automáticamente a cada evento de alerta para permitir "
                    "su identificación unívoca y seguimiento en auditorías técnicas."
                ),
                "regla_o_calculo": "Valor generado automáticamente por la base de datos de manera estrictamente creciente.",
            },
            {
                "campo": "alert_timestamp",
                "tipo": "Fecha y Hora con Zona Horaria",
                "origen": "Función de captura de tiempo de Apache Airflow",
                "descripcion": (
                    "Momento cronológico exacto (año, mes, día, hora, minuto y segundo) en el que se disparó la alerta "
                    "durante la ejecución de los procesos automáticos de datos."
                ),
                "regla_o_calculo": "Marca de tiempo del servidor (now()) registrada en el momento exacto del incidente.",
            },
            {
                "campo": "alert_type",
                "tipo": "Texto Corto (Categoría de Incidente)",
                "origen": "Módulo dags/alerts.py",
                "descripcion": (
                    "Tipo de problema operativo ocurrido durante la ejecución. Permite diferenciar una tarea caída "
                    "de una tarea que tardó más tiempo del permitido por contrato."
                ),
                "regla_o_calculo": "Toma los valores: 'TASK_FAILURE' (fallo en la tarea), 'SLA_MISS' (límite de tiempo excedido) o 'PIPELINE_ERROR' (error del flujo general).",
            },
            {
                "campo": "dag_id / task_id",
                "tipo": "Texto",
                "origen": "Contexto de ejecución del orquestador Apache Airflow",
                "descripcion": (
                    "Nombre identificador del flujo de trabajo (DAG o Grafo Acíclico Dirigido) y de la tarea específica "
                    "dentro del flujo donde ocurrió la falla técnica reportada."
                ),
                "regla_o_calculo": "Identificador técnico tal como fue definido en los scripts de Apache Airflow.",
            },
            {
                "campo": "severity",
                "tipo": "Texto Corto (Nivel de Gravedad)",
                "origen": "Módulo dags/alerts.py",
                "descripcion": (
                    "Nivel de urgencia del incidente. Señala al equipo técnico si se requiere intervención manual urgente "
                    "o si se trata de un simple aviso informativo que no detiene el servicio."
                ),
                "regla_o_calculo": "'CRITICAL' (crítico, requiere atención inmediata y reversión) o 'WARNING' (advertencia informativa sin caída del servicio).",
            },
            {
                "campo": "message / details",
                "tipo": "Texto y Documento Estructurado en Formato JSON",
                "origen": "Traza de error del sistema y métricas de ejecución",
                "descripcion": (
                    "Explicación detallada del error, incluyendo la traza del código (traceback), las variables implicadas "
                    "y los parámetros con los que la tarea estaba corriendo al momento del fallo."
                ),
                "regla_o_calculo": "Cuerpo del error formateado en texto estructurado JSON para facilitar su diagnóstico técnico.",
            },
        ],
    },
}

# 🪙 Moneta — Tu Gemelo Financiero

> Plataforma de Ingeniería de Datos e IA que construye una réplica virtual de la salud financiera de un joven adulto — para ayudarlo a entender, simular y mejorar sus decisiones de dinero en sus "primeras veces" financieras sin jerga bancaria.

Proyecto individual del programa **Path Data Engineering — BBVA x Tecmilenio**, con acompañamiento de un mentor de BBVA / Manager de Data Engineering.

**Autor:** Edgar Torres (Octubre 2026).

---

## 🎯 ¿Qué problema resuelve?

Una institución financiera busca lanzar un producto dirigido a **jóvenes adultos de 20 a 30 años** en etapa de inserción laboral: su primera renta, su primer auto, su primera tarjeta de crédito. El problema es doble:

* Son nativos digitales que esperan interacción conversacional, no reportes bancarios tradicionales.
* Tienen **historial crediticio incipiente** (poco o ningún buró de crédito), por lo que los modelos y scores de riesgo clásicos los penalizan o excluyen.
* Las herramientas tradicionales de finanzas personales son pasivas: describen el pasado (en qué se gastó), pero no ayudan a decidir hacia adelante ni a proyectar viabilidad.

Este repositorio construye el **motor de datos e IA** que resuelve esa brecha: un Gemelo Digital Financiero capaz de evaluar la salud financiera con indicadores diseñados desde cero (IRFI e ICA), simular metas a futuro con métodos estocásticos (Monte Carlo) y guiar a la persona a través de **Centavo**, un coach conversacional empático que corre en local.

## 🧩 Qué hace el sistema, en 5 capacidades

1. **Construir el Core Lakehouse** — arquitectura Medallion en almacenamiento de objetos (Bronze → Silver → Gold).
2. **Analizar** — consolidar una vista 360° de ingresos, gastos y comportamiento recurrente desde la capa analítica.
3. **Evaluar el perfil** — calcular capacidad de ahorro (ICA), riesgo financiero inicial (IRFI) y probabilidad de impago con Machine Learning (XGBoost).
4. **Simular metas** — proyectar viabilidad y plazos (renta, auto, colchón de emergencia) mediante simulación Monte Carlo con remuestreo bootstrap e intervalos de confianza al 95%.
5. **Explicar con IA Generativa** — un asistente local (Llama 3.1 8B vía Ollama) con Text-to-SQL blindado, RAG y verificación automática de respuestas para evitar alucinaciones numéricas.

## 🏗️ Arquitectura de Solución

Arquitectura **Lakehouse Medallion** distribuida y desacoplada, con capas Bronze/Silver/Gold sobre almacenamiento de objetos y publicación servida en base analítica:

```
Fuentes Públicas (Kaggle)

* Loan Default (148k filas, base de riesgo)
* Credit Risk (32k filas, complemento ponderado <30)
* Personal Finance Tracker (3k filas, comportamiento y ahorro)
│
▼ (kagglehub / PySpark)
[Apache Airflow 2.9.3] ──► [MinIO (S3-compatible)]
* ingest_bronze_pipeline   - s3a://bronze/ (Crudo e inmutable)
* silver_gold_pipeline     - s3a://silver/ (Deduplicación, imputación, maestro)
- s3a://gold/   (fact_kpi_perfil, fact_comportamiento)
│
▼ (JDBC / Compactación coalesce(4))
[PostgreSQL 15 (postgres-dw)]
- gold.fact_kpi_perfil (PK activa en record_id)
- gold.fact_comportamiento
- gold.fact_perfil_detalle
- operational.* (Alertas de DAGs, SLAs, métricas GE)
│
▼
[Streamlit App (localhost:8501)]
- Login Simulado & Selector de Perfil (t100/t102)
- Dashboard Ejecutivo (Lo que tienes hoy, Simulador, Coach)
- Observabilidad y SLAs en DW (Modo Admin / Evaluador)
- Centavo Coach ──► [Ollama Local (host:11434)]
```

Todo orquestado con **Apache Airflow**, calidad de datos automatizada vía **Great Expectations**, base servida en **PostgreSQL 15**, y ejecutándose localmente sobre **Docker Compose**.

## 🛠️ Stack tecnológico consolidado

| Categoría | Herramientas |
| --- | --- |
| Lenguajes | Python 3.11, SQL |
| Procesamiento | PySpark 3.5.1, Spark SQL, Pandas 2.2 |
| Orquestación | Apache Airflow 2.9.3 (LocalExecutor) |
| Formato Lakehouse | Parquet plano optimizado con particionamiento y compactación |
| Almacenamiento | MinIO (compatible con Amazon S3) |
| Base analítica | PostgreSQL 15 (esquemas gold y operational) |
| Calidad de datos | Great Expectations 0.18, framework propio de cuarentena |
| Machine Learning | scikit-learn 1.4, XGBoost 2.0 (modelo serializado) |
| IA Generativa | Ollama, Llama 3.1 8B, bge-m3 embeddings (RAG + Text-to-SQL + Guardrails) |
| Visualización / UI | Streamlit 1.38, Plotly 5.24 (Manual de Marca Moneta) |
| Simulación | Motor Monte Carlo propio con remuestreo bootstrap (numpy / scipy) |
| DevOps / CI | Docker Compose, GitHub Actions (flake8, black, unittest) |

## 📁 Estructura del repositorio

```
.
├── config/              # DDL de PostgreSQL, roles de seguridad (assistant_ro) y siembra
├── dags/                # DAGs de Airflow (Bronze, Silver->Gold y callbacks de alertas)
├── docs/                # Documento de Arquitectura v1.0, glosarios y políticas de IA
├── src/
│   ├── dashboard/       # Aplicación Streamlit (app.py, quality_dashboard.py, styles.py)
│   │   ├── assistant/   # Motor de Centavo (router.py, plan_engine.py, guardrails, RAG)
│   │   └── pages/       # Vistas ejecutivas (0_Lo_que_tengo_hoy, 1_Simulador, 2_Coach)
│   ├── ml/              # Entrenamiento, evaluación y serialización de modelos (XGBoost)
│   └── spark/           # Jobs PySpark (ingestion/, transformations/, quality/, loaders/)
├── tests/               # Pruebas unitarias de KPIs, DAGs, guardrails y rúbrica t082
├── docker-compose.yml   # Orquestación de infraestructura (Airflow, MinIO, Postgres, Streamlit)
├── Dockerfile.airflow   # Imagen extendida de Airflow con PySpark y Java JRE
└── Dockerfile.streamlit # Imagen del dashboard ejecutivo y técnico
```

## 🚀 Cómo levantar el entorno

### Prerrequisitos:

* Docker y Docker Compose (WSL2 en Windows o Linux nativo).
* 8 GB a 12 GB de RAM asignados al motor de Docker.
* Ollama instalado y corriendo en el host con los modelos descargados:
```
ollama run llama3.1:8b
ollama pull bge-m3
```

### Puesta en marcha:

1. **Clonar y configurar credenciales:**
```
git clone https://github.com/EdgarAntonioTorres/gemelo-digital-financiero
cd gemelo-digital-financiero
cp .env.example .env

# Completar variables requeridas en .env (usuarios y passwords)

```

2. **Levantar contenedores:**
```
docker compose up -d --build
```
3. **Acceso a consolas y servicios:**

| Servicio | URL | Credenciales / Perfil |
| --- | --- | --- |
| Moneta (App Ejecutiva) | http://localhost:8501 | Perfiles demo (Ana primeriza / Ana madura / Admin) |
| Airflow Webserver | http://localhost:8080 | Variables AIRFLOW_ADMIN_* de .env |
| MinIO (consola web) | http://localhost:9001 | Variables MINIO_ROOT_* de .env |
| PostgreSQL DW | localhost:5433 | Variables DW_POSTGRES_* de .env (BD: gemelo_digital) |

Para apagar el entorno conservando datos:
```
docker compose down
```

## 🧪 Ejecución de pruebas automatizadas

El repositorio cuenta con una suite integral de pruebas reproducibles sin dependencias externas:

```

# 1. Pruebas unitarias completas (KPIs, categorías de gasto, guardrails, router y rúbrica)

docker compose run --rm --no-deps streamlit python -m unittest discover -s tests -v

# 2. Auditoría de resiliencia, idempotencia y retries de DAGs

docker compose exec airflow-scheduler python -m unittest tests/test_dag_integrity_and_idempotency.py

# 3. Evaluación automática del asistente Centavo (186 respuestas en 3 corridas de 31 preguntas)

docker compose exec streamlit python -m assistant.run_faq_tests_t082 --corridas 3
```

## 📊 Fuentes de datos y gobierno

* **[Loan Default Dataset](https://www.kaggle.com/datasets/yasserh/loan-default-dataset)** (Kaggle) — Base de 148,670 filas. Única fuente con etiqueta real de incumplimiento (Status). Identificado hallazgo de fuga de información en tasa de interés original, neutralizado en el entrenamiento para garantizar un modelo robusto y defendible.
* **[Credit Risk Dataset](https://www.kaggle.com/datasets/laotse/credit-risk-dataset)** (Kaggle) — 32,416 filas únicas, con edad exacta y ponderación hacia usuarios menores de 30 años. Se aislaron 5 filas en cuarentena por edad anómala.
* **[Personal Finance Tracker Dataset](https://www.kaggle.com/datasets/khushikyad001/personal-finance-tracker-dataset)** (Kaggle, MIT) — 3,000 perfiles de comportamiento transaccional, ahorro y endeudamiento. Corte transversal (no panel) que incluye bandera de fraude nativa (fraud_flag). La edad se derivó sintéticamente mediante un score ponderado de madurez financiera (maturity_score), calibrado contra la distribución menor a 30 años de Credit Risk y trazado con la bandera age_synthetic_flag.

## 🛡️ Seguridad y Mitigación de Alucinaciones

* **Seguridad en dos líneas para Text-to-SQL:** Acceso a datos analíticos limitado al usuario assistant_ro con permisos exclusivos de SELECT sobre el esquema gold, ejecución en transacciones de solo lectura y timeout de 10 segundos. Antes de tocar la base de datos, un validador sintáctico en Python rechaza sentencias de escritura, inspecciones de esquemas ajenos o filtros cruzados entre perfiles.
* **Arquitectura de certeza numérica:** Centavo no realiza cálculos aritméticos con el LLM. Las cifras de ahorro, brechas, colchones y plazos se computan de forma determinista en Python (plan_engine.py); el LLM solo redacta. Un guardrail en vivo repara restas de redondeo y suprime montos o juicios no respaldados antes de llegar al usuario.

## 🗺️ Estado del proyecto

Fases 1 a 6 cerradas al 100%. Documento de Arquitectura Empresarial v1.0, diagramas Draw.io end-to-end, verificación de calidad con Great Expectations y evaluación del asistente certificada mediante rúbrica (100% de aprobación en muestra estratificada de 22 respuestas).

## 👤 Autoría

**Edgar Torres**

Proyecto individual desarrollado como entregable final del programa **Path Data Engineering (BBVA x Tecmilenio)**, con mentoría de un Manager de Data Engineering de BBVA.
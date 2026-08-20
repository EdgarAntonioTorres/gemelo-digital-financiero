# 🏦 Gemelo Digital Financiero

> Una plataforma de Ingeniería de Datos que construye una réplica virtual de la salud financiera de un joven adulto — para ayudarlo a entender, simular y mejorar sus decisiones de dinero en sus "primeras veces" financieras.

Proyecto individual del programa **Path Data Engineering — BBVA x Tecmilenio**, con acompañamiento de un mentor de BBVA / Manager de Data Engineering.

---

## 🎯 ¿Qué problema resuelve?

Una institución financiera quiere lanzar un producto dirigido a **jóvenes adultos de 20 a 30 años** que están empezando su vida laboral: su primera renta, su primer auto, su primera tarjeta de crédito. El problema es que:

- Son nativos digitales que esperan interacción conversacional, no reportes bancarios tradicionales.
- Tienen **historial crediticio incipiente** (poco o ningún buró de crédito), por lo que los modelos de riesgo "clásicos" no los representan bien.
- La infraestructura de datos actual no soporta ni la escala ni el tipo de perfil que este producto necesita evaluar.

Este repositorio construye el **motor de datos e IA** que resuelve eso: un Gemelo Digital Financiero capaz de leer el perfil de un usuario, calcular su capacidad de ahorro y su riesgo financiero, simular metas (rentar, comprar un auto, sacar una tarjeta) y explicárselo en lenguaje natural, sin jerga bancaria.

## 🧩 Qué hace el sistema, en 5 pasos

1. **Construir** el Core — un Lakehouse en capas Bronze → Silver → Gold.
2. **Analizar** — consolidar una vista 360° de ingresos y gastos desde Gold.
3. **Evaluar** — calcular capacidad de ahorro y riesgo financiero inicial con ML.
4. **Simular** — proyectar metas de corto/mediano plazo vía Monte Carlo.
5. **Explicar** — un asistente de IA generativa tipo "coach financiero" que responde en lenguaje humano.

## 🏗️ Arquitectura

Arquitectura **Lakehouse Medallion**, con Bronze/Silver en almacenamiento de objetos y Gold en una base analítica:

```
 Loan Default (base) + Credit Risk (complemento) + Personal Finance Tracker (comportamiento/ahorro)
        │
        ▼
 [BRONZE] ──► [SILVER] ──► [GOLD]        (MinIO/S3 → PySpark → PostgreSQL/DuckDB)
        │
        ▼
 Modelo de riesgo/ahorro (scikit-learn / XGBoost / LightGBM)
        │
        ▼
 Simulador Monte Carlo  +  Asistente RAG "Coach Financiero" (Ollama/LangChain)
        │
        ▼
 Dashboard técnico (observabilidad) + Dashboard ejecutivo (Streamlit, gamificado)
```

Todo orquestado con **Apache Airflow**, con calidad de datos vía **Great Expectations/dbt**, y corriendo localmente sobre **Docker Compose**.

## 🛠️ Stack tecnológico

| Categoría | Herramientas |
|---|---|
| Lenguajes | Python, SQL, Scala |
| Procesamiento | PySpark, Spark SQL, Pandas |
| Orquestación | Apache Airflow |
| Lakehouse | Delta Lake, Parquet |
| Almacenamiento | MinIO (S3-compatible) |
| Base analítica | PostgreSQL / DuckDB |
| Calidad de datos | Great Expectations, dbt |
| Machine Learning | scikit-learn, XGBoost, LightGBM |
| IA Generativa | Ollama, Llama 3, LangChain (RAG + Text-to-SQL) |
| Visualización | Streamlit |
| Simulación | Monte Carlo (numpy/scipy) |
| DevOps | GitHub, GitFlow, Docker Compose, CI (flake8/black) |

## 📁 Estructura del repositorio

```
.
├── dags/            # DAGs de Airflow — orquestan Bronze → Silver → Gold
├── src/
│   ├── spark/       # Jobs de PySpark: limpieza, dedupe, segmentación
│   └── ml/          # Modelo de riesgo/ahorro + simulador Monte Carlo
├── config/          # Config, SQL de inicialización, system prompt del asistente
├── tests/           # Pruebas unitarias (pytest)
├── .github/workflows/ci.yml   # CI: flake8 + black + pytest
└── docker-compose.yml         # Airflow + MinIO + Postgres (gold/operational)
```

Cada carpeta tiene su propio `README.md` con más detalle sobre qué va ahí.

## 🚀 Cómo levantar el entorno

Requisitos: Docker y Docker Compose instalados.

```bash
git clone <url-de-este-repo>
cd gemelo-digital-financiero
cp .env.example .env
docker compose up -d
```

| Servicio | URL | Credenciales por defecto |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| MinIO (consola) | http://localhost:9001 | minioadmin / minioadmin123 |
| Postgres (gold/operational) | localhost:5433 | gdf_user / gdf_pass |

Para apagar todo y limpiar volúmenes:
```bash
docker compose down -v
```

Cada push/PR a `main` o `develop` corre automáticamente lint (`black`, `flake8`) y pruebas (`pytest`) vía GitHub Actions.

## 📊 Fuentes de datos

- **[Loan Default Dataset](https://www.kaggle.com/datasets/yasserh/loan-default-dataset)** (Kaggle) — base principal para el KPI de riesgo y el modelo predictivo (única fuente con variable objetivo `Status`).
- **[Credit Risk Dataset](https://www.kaggle.com/datasets/laotse/credit-risk-dataset)** (Kaggle) — complemento y validación cruzada, ponderado hacia usuarios <30 años.
- **[Personal Finance Tracker Dataset](https://www.kaggle.com/datasets/khushikyad001/personal-finance-tracker-dataset)** (Kaggle, MIT) — series de tiempo de ingreso/gasto, feature store de Gold e insumo principal de ambos dashboards. No trae `age` nativo: se deriva de forma sintética vía `maturity_score` (ver `config/README.md` y sección 5.1 del Contexto Maestro).

## 🗺️ Estado del proyecto

Proyecto en construcción activa, siguiendo un roadmap de 24 semanas en 7 fases (kick-off → ingesta → calidad → analítica → IA/simulación → observabilidad → cierre ejecutivo). El avance detallado tarea por tarea vive en la bitácora interna del proyecto (fuera de este repo).

## 👤 Autoría

Proyecto individual desarrollado como parte del programa Path Data Engineering (BBVA x Tecmilenio), con mentoría de un Manager de Data Engineering de BBVA.
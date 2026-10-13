-- Se ejecuta automáticamente una sola vez al crear el volumen de postgres-dw.
-- Separa el motor analítico en dos esquemas, según lo validado en el
-- Draw.io con el mentor (sección 6.1 del Contexto Maestro):
--   - gold        : KPIs, feature store, tablas listas para BI/ML/IA
--   - operational : capa operacional/servible (API, consultas en vivo)

CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS operational;

-- gold.fact_kpi_perfil (t051, Sesión 27)
-- Tipos confirmados con datos reales tras la primera corrida de
-- src/spark/loaders/load_gold_postgres.py (Fase 1: Spark infirió el
-- esquema al crear la tabla vía mode="overwrite"). Se declara aquí de
-- forma explícita para que cualquier entorno nuevo (clon del repo,
-- volumen recreado desde cero) arranque con la tabla ya creada, con
-- PK, en vez de depender de que Spark la vuelva a inferir.
--
-- default_flag_unificada es DOUBLE PRECISION, no INTEGER: al unificar
-- las 3 fuentes (Personal Finance Tracker no tiene esta columna,
-- queda NULL para esas filas) el tipo quedó como double en algún
-- punto del pipeline de Silver — no es un error, así llegó también a
-- Parquet. Se deja nullable (a diferencia del resto) por ese motivo.
--
-- El loader escribe con mode="overwrite" + truncate="true" (TRUNCATE
-- + INSERT), no DROP+CREATE — por eso esta tabla necesita existir de
-- antemano con esta estructura; si no existe, la primera corrida
-- falla (TRUNCATE requiere que la tabla ya exista).
CREATE TABLE IF NOT EXISTS gold.fact_kpi_perfil (
    record_id TEXT PRIMARY KEY,
    fuente TEXT NOT NULL,
    irfi DOUBLE PRECISION NOT NULL,
    ica DOUBLE PRECISION NOT NULL,
    default_flag_unificada DOUBLE PRECISION,
    irfi_proxy_flag BOOLEAN NOT NULL,
    ica_proxy_flag BOOLEAN NOT NULL
);

-- operational.pipeline_alerts (t084, Fase 6)
-- Alertas registradas automáticamente por callbacks de Airflow
-- ante fallos de tareas o violaciones de SLAs de ejecución.
CREATE TABLE IF NOT EXISTS operational.pipeline_alerts (
    id SERIAL PRIMARY KEY,
    alert_timestamp TIMESTAMP NOT NULL DEFAULT now(),
    alert_type VARCHAR(50) NOT NULL,
    dag_id VARCHAR(200) NOT NULL,
    task_id VARCHAR(200),
    run_id VARCHAR(200),
    execution_date VARCHAR(100),
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    details JSONB
);
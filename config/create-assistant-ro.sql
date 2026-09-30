-- Usuario de solo lectura para el asistente Coach Financiero (t079).
--
-- Por qué existe: el Text-to-SQL deja que un LLM genere SQL. Confiar solo en
-- el prompt para que no genere un DROP/DELETE, o un SELECT fuera de Gold, no
-- es suficiente. Con este rol, Postgres mismo rechaza cualquier cosa que no
-- sea un SELECT sobre el esquema `gold`, aunque el modelo se equivoque.
--
-- Es IDEMPOTENTE: se puede correr varias veces (crea el rol solo si no
-- existe y siempre actualiza la contraseña).
--
-- NO se ejecuta automáticamente desde docker-entrypoint-initdb.d: la
-- contraseña no debe vivir hardcodeada en un archivo versionado (mismo
-- criterio que docker-compose.yml, todo sale de .env). Se corre a mano, una
-- vez, pasando la contraseña como variable de psql:
--
--   set -a; source .env; set +a
--   docker compose exec -T postgres-dw psql -U "$DW_POSTGRES_USER" \
--       -d gemelo_digital -v ro_password="$ASSISTANT_RO_PASSWORD" \
--       < config/create-assistant-ro.sql
--
-- Nota sobre ALTER DEFAULT PRIVILEGES (importante): load_fact_comportamiento_
-- postgres.py escribe con mode="overwrite" SIN truncate, o sea que Spark hace
-- DROP + CREATE de gold.fact_comportamiento en cada corrida, y al borrar la
-- tabla se pierden los GRANT que tuviera. Los privilegios por defecto hacen
-- que assistant_ro reciba SELECT automáticamente en cada tabla nueva que
-- cree el usuario que ejecuta este script (DW_POSTGRES_USER, el mismo con el
-- que Spark se conecta).

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE assistant_ro LOGIN PASSWORD %L', :'ro_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_ro')
\gexec

ALTER ROLE assistant_ro WITH LOGIN PASSWORD :'ro_password';

-- Cinturón y tirantes: aunque tuviera algún permiso de escritura por error,
-- cada sesión de este rol arranca en modo solo lectura, y una consulta que
-- se cuelgue se corta a los 10 segundos.
ALTER ROLE assistant_ro SET default_transaction_read_only = on;
ALTER ROLE assistant_ro SET statement_timeout = '10s';

GRANT CONNECT ON DATABASE gemelo_digital TO assistant_ro;
GRANT USAGE ON SCHEMA gold TO assistant_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO assistant_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO assistant_ro;

-- El esquema operational (quality_metrics, pipeline_execution_log) es del
-- dashboard técnico, no del asistente: sin acceso.
REVOKE ALL ON SCHEMA operational FROM assistant_ro;
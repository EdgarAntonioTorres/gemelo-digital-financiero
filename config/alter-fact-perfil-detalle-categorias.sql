-- gold.fact_perfil_detalle: 3 columnas nuevas para categorizar el gasto (Sesion 36).
--
-- Por que existe: el mentor pidio categorizar el gasto con el mayor detalle que
-- sostengan los datos. La tabla solo guardaba la PROPORCION esencial/discrecional
-- (decision de t077 v2.3, seccion 7, para que nadie pintara esas cifras como
-- partes del gasto total). Ahora se guardan los MONTOS declarados, y la capa de
-- presentacion (assistant/categorias_gasto.py) los muestra con su cobertura a la
-- vista y una barra "sin categorizar": nunca como partes del total.
--
-- Columnas (todas de Personal Finance Tracker, localizadas POR VALOR en el CSV
-- original, 1 coincidencia exacta por perfil):
--   gasto_esencial_declarado     <- essential_spending
--   gasto_discrecional_declarado <- discretionary_spending
--   vivienda_mensual             <- rent_or_mortgage (monto en USD, nunca cero)
--
-- Lo que NO se carga, y por que (medido sobre las 3,000 filas del CSV):
--   * `category`: etiqueta "dominante" de la fila sin relacion con ningun monto
--     (eta^2 entre 0.002 y 0.005, lo esperable por azar). No sirve para recomendar.
--   * `loan_payment`: coincide con debt_to_income_ratio en solo 14% de las filas;
--     mostrarlos juntos se contradice (t077 v2.3, seccion 7).
--
-- Es ADITIVA e IDEMPOTENTE: ADD COLUMN IF NOT EXISTS + UPDATE por record_id. Va
-- DESPUES de config/create-fact-perfil-detalle.sql. Si ese script se vuelve a
-- crear desde cero (DROP TABLE), hay que volver a correr este. Corre en una
-- transaccion: si algo no cuadra, no se confirma nada.
--
--   set -a; source .env; set +a
--   docker compose exec -T postgres-dw psql -U "$DW_POSTGRES_USER" \
--       -d gemelo_digital < config/alter-fact-perfil-detalle-categorias.sql

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE gold.fact_perfil_detalle
    ADD COLUMN IF NOT EXISTS gasto_esencial_declarado     NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS gasto_discrecional_declarado NUMERIC(18,2),
    ADD COLUMN IF NOT EXISTS vivienda_mensual             NUMERIC(18,2);

COMMENT ON COLUMN gold.fact_perfil_detalle.gasto_esencial_declarado IS
    'essential_spending tal como lo declara la fuente. NO es parte del gasto total (no suman el total en 97% de las filas).';
COMMENT ON COLUMN gold.fact_perfil_detalle.gasto_discrecional_declarado IS
    'discretionary_spending tal como lo declara la fuente. NO es parte del gasto total.';
COMMENT ON COLUMN gold.fact_perfil_detalle.vivienda_mensual IS
    'rent_or_mortgage (monto en USD). Se trata como parte del gasto esencial (se cumple en 92% de las filas).';

-- Ana primeriza (nivel 1): PFT_0000636 | Ana mas madura (nivel 2): PFT_0002539
UPDATE gold.fact_perfil_detalle SET
    gasto_esencial_declarado = 1786.51, gasto_discrecional_declarado = 464.49, vivienda_mensual = 1071.82
WHERE record_id = 'PFT_0000636';

UPDATE gold.fact_perfil_detalle SET
    gasto_esencial_declarado = 1740.00, gasto_discrecional_declarado = 753.26, vivienda_mensual = 1086.19
WHERE record_id = 'PFT_0002539';

-- Verificacion: las dos filas existen, la proporcion guardada coincide con los
-- montos nuevos y la vivienda cabe dentro del gasto esencial. Si no, los record_id
-- pudieron desalinearse tras re-correr el pipeline de Gold (ver el otro script).
DO $$
DECLARE
    n_filas INT;
    n_ok    INT;
BEGIN
    SELECT count(*) INTO n_filas
    FROM gold.fact_perfil_detalle
    WHERE record_id IN ('PFT_0000636', 'PFT_0002539')
      AND gasto_esencial_declarado IS NOT NULL;

    IF n_filas <> 2 THEN
        RAISE EXCEPTION
            'Se esperaban 2 filas en gold.fact_perfil_detalle y hay %. Corre primero config/create-fact-perfil-detalle.sql. No se confirma la transaccion.',
            n_filas;
    END IF;

    SELECT count(*) INTO n_ok
    FROM gold.fact_perfil_detalle d
    JOIN gold.fact_comportamiento c ON c.record_id = d.record_id
    WHERE d.record_id IN ('PFT_0000636', 'PFT_0002539')
      AND abs(d.proporcion_esencial
              - d.gasto_esencial_declarado / (d.gasto_esencial_declarado + d.gasto_discrecional_declarado)) < 0.0001
      AND d.vivienda_mensual <= d.gasto_esencial_declarado
      AND abs(c.gasto_promedio_3m - d.huella_gasto_mensual) < 0.005;

    IF n_ok <> 2 THEN
        RAISE EXCEPTION
            'Las categorias no coinciden con la proporcion y la huella guardadas: % de 2 filas verifican. No se confirma la transaccion.',
            n_ok;
    END IF;
END $$;

COMMIT;
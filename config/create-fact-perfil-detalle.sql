-- gold.fact_perfil_detalle: detalle de las dos Anas de la demo (Centavo v2 / t077 v2.3).
--
-- Por que existe: Centavo y el dashboard personal necesitan 5 datos que hoy no
-- estan en Gold (meta de ahorro mensual, ahorro del mes, meta cumplida,
-- inversion mensual, fondo de emergencia en USD) mas 2 de apoyo (proporcion
-- esencial/discrecional, suscripciones). Como la app solo usa las dos Anas, se
-- siembran 2 filas en una tabla NUEVA y aditiva: no toca Silver ni Gold
-- aprobados. El esquema es el mismo que tendria para cualquier perfil; extender
-- la tabla a las 3,000 filas de PFT queda fuera del MVP (requeriria tocar el
-- pipeline de Silver y autorizacion del mentor).
--
-- Origen de los valores: filas de Silver PFT localizadas POR VALOR (no por
-- record_id) con diagnostics/peek_personas_candidatas.py y
-- diagnose_coherencia_pft_ana.py (1 coincidencia exacta por perfil). Cada valor
-- esta copiado tal cual de esa salida; las proporciones se calculan en el INSERT
-- para que la cuenta sea auditable.
--
-- Decisiones de diseno:
--   * Se guarda la PROPORCION esencial/(esencial+discrecional), no los montos
--     crudos: en PFT no suman el gasto total (1 de 3,000 filas), y asi nadie
--     puede mostrarlos o sumarlos como partes del gasto (t077 v2.3, seccion 7).
--   * Columnas `huella_*`: ingreso, gasto y ratio de endeudamiento copiados de
--     Silver. record_id se genera con zipWithIndex en build_silver_master.py,
--     que no garantiza el mismo orden entre corridas separadas: si el pipeline
--     de Gold se re-corre y los record_id se desalinean, la huella deja de
--     coincidir con gold.fact_comportamiento y este script falla en vez de
--     servir datos de otra persona en silencio.
--   * SIN foreign key a gold.fact_comportamiento, a proposito: Spark escribe esa
--     tabla con DROP + CREATE en cada corrida y una FK bloquearia el DROP.
--   * edad_ilustrativa: edad DERIVADA (age_synthetic_flag = True en Silver), no
--     observada.
--
-- Es IDEMPOTENTE: se puede correr varias veces (upsert por record_id). Correrlo
-- DESPUES de cada corrida del pipeline de Gold sirve como verificacion de la
-- huella. Corre en una transaccion: si la verificacion falla, no se confirma
-- nada.
--
-- Se corre a mano, con el mismo usuario que escribe Gold (DW_POSTGRES_USER):
--
--   set -a; source .env; set +a
--   docker compose exec -T postgres-dw psql -U "$DW_POSTGRES_USER" \
--       -d gemelo_digital < config/create-fact-perfil-detalle.sql

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS gold.fact_perfil_detalle (
    record_id                   TEXT PRIMARY KEY,
    meta_ahorro_mensual         NUMERIC(18,2) NOT NULL,  -- budget_goal (se comporta como meta de ahorro mensual)
    ahorro_del_mes              NUMERIC(18,2) NOT NULL,  -- actual_savings = max(0, ingreso - gasto)
    meta_ahorro_cumplida        BOOLEAN       NOT NULL,  -- savings_goal_met = (ahorro_del_mes >= meta_ahorro_mensual)
    inversion_mensual           NUMERIC(18,2) NOT NULL,  -- investment_amount (escala de aportacion mensual: INFERENCIA)
    fondo_emergencia_usd        NUMERIC(18,2) NOT NULL,  -- emergency_fund, en USD
    proporcion_esencial         NUMERIC(6,4)  NOT NULL,  -- essential / (essential + discretionary); NO son partes del gasto total
    suscripciones_activas       INTEGER       NOT NULL,  -- subscription_services (conteo)
    edad_ilustrativa            INTEGER       NOT NULL,  -- derivada (age_synthetic_flag = True), no observada
    huella_ingreso_mensual      NUMERIC(18,2) NOT NULL,  -- verificacion contra gold.fact_comportamiento
    huella_gasto_mensual        NUMERIC(18,2) NOT NULL,
    huella_ratio_endeudamiento  NUMERIC(10,4) NOT NULL
);

COMMENT ON TABLE gold.fact_perfil_detalle IS
    'Detalle de las dos Anas de la demo (t077 v2.3). 2 filas sembradas desde Silver PFT por valor, no por record_id. Esquema general; extender a las 3,000 filas queda fuera del MVP. Las columnas huella_* verifican el alineamiento de record_id con gold.fact_comportamiento.';

-- Ana primeriza (nivel 1): PFT_0000636 | Ana mas madura (nivel 2): PFT_0002539
INSERT INTO gold.fact_perfil_detalle (
    record_id, meta_ahorro_mensual, ahorro_del_mes, meta_ahorro_cumplida,
    inversion_mensual, fondo_emergencia_usd, proporcion_esencial,
    suscripciones_activas, edad_ilustrativa,
    huella_ingreso_mensual, huella_gasto_mensual, huella_ratio_endeudamiento
) VALUES
    ('PFT_0000636', 2194.05,  626.83, FALSE, 140.81,  540.88,
        ROUND(1786.51 / (1786.51 + 464.49), 4), 3, 28, 3704.29, 3077.46, 0.5800),
    ('PFT_0002539', 2346.98, 1411.45, FALSE, 202.27, 1286.49,
        ROUND(1740.00 / (1740.00 + 753.26), 4), 4, 27, 3854.89, 2443.44, 0.1700)
ON CONFLICT (record_id) DO UPDATE SET
    meta_ahorro_mensual        = EXCLUDED.meta_ahorro_mensual,
    ahorro_del_mes             = EXCLUDED.ahorro_del_mes,
    meta_ahorro_cumplida       = EXCLUDED.meta_ahorro_cumplida,
    inversion_mensual          = EXCLUDED.inversion_mensual,
    fondo_emergencia_usd       = EXCLUDED.fondo_emergencia_usd,
    proporcion_esencial        = EXCLUDED.proporcion_esencial,
    suscripciones_activas      = EXCLUDED.suscripciones_activas,
    edad_ilustrativa           = EXCLUDED.edad_ilustrativa,
    huella_ingreso_mensual     = EXCLUDED.huella_ingreso_mensual,
    huella_gasto_mensual       = EXCLUDED.huella_gasto_mensual,
    huella_ratio_endeudamiento = EXCLUDED.huella_ratio_endeudamiento;

-- Verificacion: cada fila debe coincidir con gold.fact_comportamiento. Si no,
-- los record_id pudieron desalinearse tras una re-corrida del pipeline.
DO $$
DECLARE
    n_detalle INT;
    n_ok      INT;
BEGIN
    SELECT count(*) INTO n_detalle FROM gold.fact_perfil_detalle;

    SELECT count(*) INTO n_ok
    FROM gold.fact_perfil_detalle d
    JOIN gold.fact_comportamiento c ON c.record_id = d.record_id
    WHERE abs(c.ingreso_mensual     - d.huella_ingreso_mensual)     < 0.005
      AND abs(c.gasto_promedio_3m   - d.huella_gasto_mensual)       < 0.005
      AND abs(c.ratio_endeudamiento - d.huella_ratio_endeudamiento) < 0.00005
      AND abs(d.ahorro_del_mes - GREATEST(0, c.ingreso_mensual - c.gasto_promedio_3m)) < 0.011
      AND abs(c.fondo_emergencia_meses - d.fondo_emergencia_usd / c.gasto_promedio_3m) < 0.001
      AND d.meta_ahorro_cumplida = (d.ahorro_del_mes >= d.meta_ahorro_mensual);

    IF n_ok <> n_detalle THEN
        RAISE EXCEPTION
            'La huella no coincide: % de % filas verifican contra gold.fact_comportamiento. Los record_id pueden haberse desalineado tras re-correr el pipeline de Gold. No se confirma la transaccion.',
            n_ok, n_detalle;
    END IF;
END $$;

-- El rol de solo lectura del asistente (config/create-assistant-ro.sql) recibe
-- SELECT por ALTER DEFAULT PRIVILEGES solo si este script lo corre el mismo
-- usuario que ejecuto aquel; el GRANT explicito cubre cualquier otro caso.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'assistant_ro') THEN
        GRANT SELECT ON gold.fact_perfil_detalle TO assistant_ro;
    END IF;
END $$;

COMMIT;
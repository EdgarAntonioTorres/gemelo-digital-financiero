-- Se ejecuta automáticamente una sola vez al crear el volumen de postgres-dw.
-- Separa el motor analítico en dos esquemas, según lo validado en el
-- Draw.io con el mentor (sección 6.1 del Contexto Maestro):
--   - gold        : KPIs, feature store, tablas listas para BI/ML/IA
--   - operational : capa operacional/servible (API, consultas en vivo)

CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS operational;

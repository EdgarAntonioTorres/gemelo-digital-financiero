# /config

Configuración centralizada del proyecto: variables de conexión (MinIO,
Postgres/DuckDB), parámetros de calidad de datos (Great Expectations/dbt),
umbrales de SLA (t083), y el `system_prompt` del asistente "Coach Financiero"
(t075).

No versionar credenciales reales — usar `.env` (excluido en `.gitignore`)
a partir de `.env.example`.
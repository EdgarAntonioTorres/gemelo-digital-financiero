# /config

Configuración centralizada del proyecto: variables de conexión (MinIO,
Postgres/DuckDB), parámetros de calidad de datos (Great Expectations/dbt),
umbrales de SLA (t083), y el `system_prompt` del asistente "Coach Financiero"
(t075).

También vive aquí la definición de parámetros del `maturity_score` (pesos,
umbral de segmentación) usado para derivar `age` sintética en Personal
Finance Tracker (t109-t111 — requiere validación del mentor antes de Silver).

No versionar credenciales reales — usar `.env` (excluido en `.gitignore`)
a partir de `.env.example`.
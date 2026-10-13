# Decisión Final de Diferenciadores de Innovación (t090 / Fase 6)

**Fecha:** Octubre 2026  
**Proyecto:** Moneta (Gemelo Digital Financiero)

De conformidad con el límite de alcance establecido en el WBS (máximo 1 a 2 diferenciadores sin comprometer el MVP), se eligen formalmente los siguientes dos componentes:

### Diferenciador 1: Observabilidad Operativa Integrada con SLAs y Alertas Persistentes
* **Entregables asociados:** `dags/alerts.py`, `operational.pipeline_alerts`, `src/dashboard/quality_dashboard.py` (Panel 1 y 3).
* **Justificación:** Monitoreo activo de límites de tiempo de ejecución (4 min para ingestas, 5 min para transformaciones) con persistencia auditable en la capa operacional y visualización inmediata para el evaluador/mentor.

### Diferenciador 2: Gobierno de Datos y Seguridad RBAC para Asistente IA (Text-to-SQL)
* **Entregables asociados:** `config/create-assistant-ro.sql`, `src/dashboard/assistant/text_to_sql.py`.
* **Justificación:** Implementación de dos barreras defensivas independientes: usuario analítico sin privilegios de escritura (`assistant_ro`) restringido al esquema `gold` con timeout de 10s, complementado con validación determinística sintáctica en Python antes de ejecutar cualquier consulta formulada por el LLM.
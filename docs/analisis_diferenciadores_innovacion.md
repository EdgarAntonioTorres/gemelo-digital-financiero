# Análisis de Diferenciadores de Innovación (t089 / Fase 6)

## 1. Contexto y Criterios de Selección
El programa pondera fuertemente la "Arquitectura + Pipelines" (40%), la "Calidad y Observabilidad" (10%) y la "Innovación" (10%). La regla de diseño del proyecto prohíbe incorporar componentes que pongan en riesgo la estabilidad del MVP secuencial.

A continuación se evalúan las alternativas de la Sección 13 del Contexto Maestro:

| Diferenciador Evaluado | Esfuerzo de Implementación | Impacto en Criterios | Riesgo Operativo | Veredicto |
|---|---|---|---|---|
| **1. Observabilidad y SLAs Avanzados (PostgreSQL + Streamlit)** | Bajo / Medio (Alineado a t084/t085) | Alto (10% Calidad + 40% Pipelines) | Mínimo | **Candidato Principal** |
| **2. Control de Acceso RBAC con usuario de solo lectura para IA** | Bajo (Ya diseñado en config/ y text_to_sql.py) | Alto (10% Innovación + Seguridad DAMA) | Mínimo | **Candidato Principal** |
| **3. Catálogo Automático (DataHub / OpenMetadata)** | Alto (Requiere contenedores pesados y JVM extra) | Medio | Alto (Memoria local y saturación Docker) | Descartado |
| **4. Anonimización con Presidio** | Medio | Bajo (Datasets ya son públicos y sin PII sensible real) | Bajo | Descartado |
| **5. Consultas Federadas con Trino** | Muy Alto | Bajo para la escala actual | Alto (Complejidad de red y puertos) | Descartado |

## 2. Argumentación Técnica
- **Observabilidad Operativa con SLAs:** Pasar de métricas dispersas a un registro auditable de eventos e incidentes en base de datos (`operational.pipeline_alerts`) con visualización comparativa de tiempos reales vs límites contractuales en Streamlit.
- **Seguridad RBAC (`assistant_ro`):** La interacción entre Large Language Models y motores SQL de analítica requiere aislamiento estricto. Implementar dos líneas de defensa (usuario PostgreSQL con transacciones forzadas de solo lectura y timeout estricto + sanitizador léxico en Python) evita riesgos de inyección y extracción destructiva.
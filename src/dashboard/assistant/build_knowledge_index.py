"""
Construcción offline del índice de embeddings — Coach Financiero (`t080`)

Lee los 3 documentos de `docs/` (2 ya existentes + `glosario_educativo.md`,
nuevo en esta sesión — ver docstring de ese archivo para por qué hacía
falta), los parte en fragmentos por encabezado `## `, calcula un
embedding por fragmento con Ollama (`bge-m3`, multilingüe — a
diferencia de la mayoría de los modelos de embeddings, que son solo en
inglés), y guarda todo en `assistant/knowledge_index.json`.

Por qué es un script APARTE de `rag.py` (que sí corre en cada
pregunta del usuario): calcular embeddings para ~25-30 fragmentos toma
varios segundos — hacerlo en cada pregunta sería lento y innecesario,
porque el contenido de los 3 documentos no cambia con cada consulta.
Se corre una sola vez (o cuando cambie alguno de los 3 documentos), y
el resultado (`knowledge_index.json`) se versiona en Git — mismo
criterio que `modelo_riesgo_default.pkl` (`t066`): es un artefacto
generado pero barato de versionar y caro de recalcular en cada arranque.

Uso (dentro del contenedor de streamlit, con Ollama corriendo y
`bge-m3` ya descargado — `ollama pull bge-m3`):
    docker compose exec streamlit python -m assistant.build_knowledge_index

Variables de entorno requeridas: OLLAMA_BASE_URL.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

EMBEDDING_MODEL = "bge-m3"
OLLAMA_TIMEOUT_SECONDS = 30

# Los 3 documentos que alimentan el RAG — 2 ya existían (contexto del
# proyecto), 1 nuevo de esta sesión (contenido educativo general que
# no cubrían los otros 2, ver glosario_educativo.md).
DOCS_DIR = Path("/app/docs")
KNOWLEDGE_SOURCES = {
    "glosario_reglas_negocio": DOCS_DIR / "glosario_reglas_negocio.md",
    "diccionario_features": DOCS_DIR / "diccionario_features.md",
    "glosario_educativo": DOCS_DIR / "glosario_educativo.md",
}

OUTPUT_PATH = Path(__file__).resolve().parent / "knowledge_index.json"


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def chunk_markdown(texto: str, fuente: str) -> list[dict]:
    """Parte un documento por encabezados de nivel 2 (`## `) — mismo
    nivel que usan los 3 documentos para separar conceptos/reglas
    individuales (ver estructura de glosario_reglas_negocio.md y
    glosario_educativo.md). Cada fragmento conserva su encabezado, para
    que el modelo sepa de qué concepto habla sin tener que inferirlo
    del cuerpo del texto."""
    partes = re.split(r"(?=^## )", texto, flags=re.MULTILINE)
    fragmentos = []
    for parte in partes:
        parte = parte.strip()
        # Ignora el preámbulo antes del primer "## " (título del
        # documento + la cita de contexto, no es un concepto en sí).
        if not parte.startswith("## "):
            continue
        fragmentos.append({"fuente": fuente, "texto": parte})
    return fragmentos


def embed_texto(texto: str) -> list[float]:
    base_url = get_required_env("OLLAMA_BASE_URL")
    response = requests.post(
        f"{base_url}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": texto},
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def main() -> None:
    todos_los_fragmentos: list[dict] = []

    for nombre_fuente, ruta in KNOWLEDGE_SOURCES.items():
        if not ruta.exists():
            raise FileNotFoundError(
                f"No se encontró {ruta} — revisa el volumen ./docs:/app/docs:ro "
                f"en docker-compose.yml (servicio streamlit)."
            )
        texto = ruta.read_text(encoding="utf-8")
        fragmentos = chunk_markdown(texto, nombre_fuente)
        print(f"{nombre_fuente}: {len(fragmentos)} fragmentos")
        todos_los_fragmentos.extend(fragmentos)

    print(f"\nTotal: {len(todos_los_fragmentos)} fragmentos. Calculando embeddings...")

    indice = []
    for i, fragmento in enumerate(todos_los_fragmentos):
        embedding = embed_texto(fragmento["texto"])
        indice.append(
            {
                "id": i,
                "fuente": fragmento["fuente"],
                "texto": fragmento["texto"],
                "embedding": embedding,
            }
        )
        print(f"  [{i + 1}/{len(todos_los_fragmentos)}] {fragmento['fuente']} — OK")

    OUTPUT_PATH.write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nÍndice guardado en: {OUTPUT_PATH} ({len(indice)} fragmentos)")


if __name__ == "__main__":
    main()

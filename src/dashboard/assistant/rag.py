"""
RAG en tiempo real sobre el índice de conocimiento — Coach Financiero (`t080`)

Carga `knowledge_index.json` (armado offline por
`build_knowledge_index.py`, ver ese módulo para el porqué de
separarlo), calcula el embedding de la pregunta del usuario con el
mismo modelo (`bge-m3`) y devuelve los `k` fragmentos más parecidos
por similitud coseno — sin ninguna librería de vector store (Chroma/
FAISS): con ~25-30 fragmentos, una búsqueda lineal en NumPy es
instantánea y no vale la pena la dependencia extra (mismo criterio de
"no fabricar/complicar sin necesidad" ya aplicado en todo el
proyecto).

Autocontenido a propósito, mismo criterio que `text_to_sql.py`/
`simulator_engine.py`: duplica `get_required_env()`, no importa nada
de `spark/`/`ml/`.

Variables de entorno requeridas: OLLAMA_BASE_URL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import requests

EMBEDDING_MODEL = "bge-m3"
OLLAMA_TIMEOUT_SECONDS = 30
TOP_K_DEFAULT = 3

INDEX_PATH = Path(__file__).resolve().parent / "knowledge_index.json"


def get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def embed_texto(texto: str) -> np.ndarray:
    base_url = get_required_env("OLLAMA_BASE_URL")
    response = requests.post(
        f"{base_url}/api/embeddings",
        json={"model": EMBEDDING_MODEL, "prompt": texto},
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return np.array(response.json()["embedding"], dtype=np.float64)


def cargar_indice() -> list[dict]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"No existe {INDEX_PATH} — corre primero "
            f"'python -m assistant.build_knowledge_index' (t080)."
        )
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def buscar_fragmentos(pregunta: str, k: int = TOP_K_DEFAULT) -> list[dict]:
    """Devuelve los k fragmentos más relevantes para `pregunta`, cada
    uno con su fuente y score de similitud (0 a 1, más alto = más
    parecido) — el caller (t081, el router) decide qué hacer si el
    score es bajo (ver nota en responder_pregunta())."""
    indice = cargar_indice()
    embedding_pregunta = embed_texto(pregunta)

    matriz_embeddings = np.array([f["embedding"] for f in indice], dtype=np.float64)
    normas = np.linalg.norm(matriz_embeddings, axis=1) * np.linalg.norm(
        embedding_pregunta
    )
    # Evita división entre cero si algún embedding llegara vacío (no
    # debería pasar con datos reales, pero no se asume sin chequear).
    normas = np.where(normas == 0, 1e-10, normas)
    similitudes = (matriz_embeddings @ embedding_pregunta) / normas

    top_indices = np.argsort(similitudes)[::-1][:k]
    return [
        {
            "fuente": indice[i]["fuente"],
            "texto": indice[i]["texto"],
            "score": float(similitudes[i]),
        }
        for i in top_indices
    ]


def formatear_para_prompt(fragmentos: list[dict]) -> str:
    """Arma el bloque CONOCIMIENTO_DE_APOYO del System Prompt (t075) —
    cada fragmento con su fuente, para que Centavo pueda distinguir
    "esto es una regla de este proyecto" de "esto es un concepto
    general", si hace falta."""
    if not fragmentos:
        return "(sin fragmentos relevantes encontrados)"
    partes = [f"[Fuente: {f['fuente']}]\n{f['texto']}" for f in fragmentos]
    return "\n\n---\n\n".join(partes)


if __name__ == "__main__":
    # Sanity check manual — mismo patrón que simulator_engine.py/
    # text_to_sql.py. Requiere knowledge_index.json ya generado y
    # Ollama corriendo con bge-m3.
    preguntas_prueba = [
        "¿Qué es un fondo de emergencia y cuánto debería tener?",
        "¿Cómo funciona la fecha de corte de una tarjeta de crédito?",
        "¿Por qué la edad es sintética en este proyecto?",
        # debe traer glosario_reglas_negocio, no glosario_educativo
    ]
    for pregunta in preguntas_prueba:
        print(f"\nPregunta: {pregunta}")
        for frag in buscar_fragmentos(pregunta):
            primera_linea = frag["texto"].splitlines()[0]
            print(f"  [{frag['score']:.3f}] ({frag['fuente']}) {primera_linea}")

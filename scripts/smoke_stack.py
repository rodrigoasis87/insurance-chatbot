"""Smoke test del stack (ADR-001): verifica que la integración de modelos
locales de Ollama y el vector store Qdrant funcionen de punta a punta.

Uso:
    uv run python scripts/smoke_stack.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_ollama import ChatOllama, OllamaEmbeddings  # noqa: E402

from app.rag.config import get_settings  # noqa: E402

# Dimensiones esperadas por modelo (los defaults del stack viven en
# app/rag/config.py; nomic-embed-text queda por si alguien lo reactiva).
EXPECTED_DIMS = {
    "qwen3-embedding": 1024,
    "nomic-embed-text": 768,
}


def test_embeddings() -> dict[str, Any]:
    """Genera un embedding y valida sus dimensiones esperadas."""
    settings = get_settings()
    embeddings = OllamaEmbeddings(model=settings.embedding_model)
    vector = embeddings.embed_query("¿Qué cubre una póliza catastrófica por evento?")
    family = settings.embedding_model.split(":")[0]
    expected = EXPECTED_DIMS.get(family)
    if expected is not None:
        assert len(vector) == expected, (
            f"Dimensión inesperada: {len(vector)} (se esperaba {expected} "
            f"para {settings.embedding_model})"
        )
    return {
        "model": settings.embedding_model,
        "dims": len(vector),
        "sample": round(vector[0], 4),
    }


def test_chat() -> dict[str, Any]:
    """Envía una consulta corta y devuelve la respuesta del LLM local."""
    settings = get_settings()
    llm = ChatOllama(model=settings.ollama_chat_model, temperature=0)
    response = llm.invoke("Responde en una sola línea: ¿qué es una póliza catastrófica?")
    return {"model": settings.ollama_chat_model, "response": response.content[:200]}


def test_qdrant() -> dict[str, Any]:
    """Comprueba la conectividad con Qdrant (warn si el servidor no responde)."""
    import requests

    url = get_settings().qdrant_url
    try:
        resp = requests.get(f"{url}/healthz", timeout=3)
        return {"available": resp.status_code == 200}
    except requests.ConnectionError:
        return {"available": False, "hint": "ejecutá: docker compose up -d"}


def main() -> None:
    print("== Smoke test stack (ADR-001) ==")

    print(f"\n[1] Embeddings ({get_settings().embedding_model}):")
    try:
        print("   OK ->", test_embeddings())
    except Exception as exc:  # pragma: no cover
        print("   FAIL ->", exc)

    print(f"\n[2] LLM ({get_settings().ollama_chat_model}):")
    try:
        print("   OK ->", test_chat())
    except Exception as exc:  # pragma: no cover
        print("   FAIL ->", exc)

    print("\n[3] Qdrant (localhost:6333):")
    print("   ->", test_qdrant())


if __name__ == "__main__":
    main()
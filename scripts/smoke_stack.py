"""Smoke test del stack (ADR-001): verifica que la integración de modelos
locales de Ollama y el vector store Qdrant funcionen de punta a punta.

Uso:
    uv run python scripts/smoke_stack.py
"""

from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings

GENERATION_MODEL = "qwen3:4b"
EMBEDDING_MODEL = "nomic-embed-text"
QDRANT_URL = "http://localhost:6333"


def test_embeddings() -> dict[str, Any]:
    """Genera un embedding y valida sus dimensiones esperadas."""
    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    vector = embeddings.embed_query("¿Qué cubre una póliza catastrófica por evento?")
    assert len(vector) == 768, f"Dimensión inesperada: {len(vector)} (se esperaba 768)"
    return {"dims": len(vector), "sample": round(vector[0], 4)}


def test_chat() -> dict[str, Any]:
    """Envía una consulta corta y devuelve la respuesta del LLM local."""
    llm = ChatOllama(model=GENERATION_MODEL, temperature=0)
    response = llm.invoke("Responde en una sola línea: ¿qué es una póliza catastrófica?")
    return {"model": GENERATION_MODEL, "response": response.content[:200]}


def test_qdrant() -> dict[str, Any]:
    """Comprueba la conectividad con Qdrant (warn si el servidor no responde)."""
    import requests

    try:
        resp = requests.get(f"{QDRANT_URL}/healthz", timeout=3)
        return {"available": resp.status_code == 200}
    except requests.ConnectionError:
        return {"available": False, "hint": "ejecutá: docker compose up -d"}


def main() -> None:
    print("== Smoke test stack (ADR-001) ==")

    print("\n[1] Embeddings (nomic-embed-text):")
    try:
        print("   OK ->", test_embeddings())
    except Exception as exc:  # pragma: no cover
        print("   FAIL ->", exc)

    print("\n[2] LLM (qwen3:4b):")
    try:
        print("   OK ->", test_chat())
    except Exception as exc:  # pragma: no cover
        print("   FAIL ->", exc)

    print("\n[3] Qdrant (localhost:6333):")
    print("   ->", test_qdrant())


if __name__ == "__main__":
    main()
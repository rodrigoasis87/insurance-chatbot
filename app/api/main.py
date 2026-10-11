"""API HTTP delgado (Issue #16, CONTRACTS §4).

Sin logica RAG propia: delega en ``app.rag.query.query()`` (#17). ``/health`` y
``/policies`` derivan del estado real de Qdrant y Ollama (no del indice local,
que no vive en el contenedor).

Correr local:  uv run uvicorn app.api.main:app --port 8000
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.rag.config import get_settings
from app.rag.query import query as rag_query
from app.rag.vectordb import get_client

logger = logging.getLogger(__name__)

app = FastAPI(title="QuePlan API", version="0.1.0")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


def _año(poliza: str) -> str | None:
    """Año de la póliza desde su codigo: ``POL<ccc><aa><nnnn>`` → ``20<aa>``."""
    digits = [c for c in poliza if c.isdigit()]
    return f"20{digits[3]}{digits[4]}" if len(digits) >= 5 else None


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    try:
        resultado = rag_query(body.question)
    except Exception as exc:
        logger.exception("Fallo query() de %s", body.question[:60])
        raise HTTPException(
            status_code=500, detail=f"error interno: {type(exc).__name__}"
        ) from exc
    return ChatResponse(answer=resultado["answer"], sources=resultado["sources"])


@app.get("/health")
def health() -> dict[str, str]:
    qdrant = "ok"
    try:
        get_client().get_collections()
    except Exception:
        qdrant = "error"
    ollama = "ok"
    try:
        httpx.get(f"{get_settings().ollama_base_url}/api/tags", timeout=5).raise_for_status()
    except Exception:
        ollama = "error"
    return {"qdrant": qdrant, "ollama": ollama}


@app.get("/policies")
def policies() -> list[dict[str, Any]]:
    """Lista de pólizas distintas derivada de los payloads de Qdrant (CONTRACTS §4)."""
    settings = get_settings()
    client = get_client()
    if not client.collection_exists(settings.qdrant_collection):
        return []

    unicas: dict[str, dict[str, Any]] = {}
    next_offset: Any = None
    while True:
        points, next_offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=200,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        for punto in points:
            meta = (punto.payload or {}).get("metadata", {}) or {}
            poliza = meta.get("poliza")
            if not poliza or poliza in unicas:
                continue
            unicas[poliza] = {
                "poliza": poliza,
                "ramo": meta.get("ramo"),
                "año": _año(poliza),
            }
        if next_offset is None:
            break
    return sorted(unicas.values(), key=lambda p: p["poliza"])
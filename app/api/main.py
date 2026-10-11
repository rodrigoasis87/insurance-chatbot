"""API HTTP delgado (Issue #16, CONTRACTS §4).

Sin logica RAG propia: delega en ``app.rag.query.query()`` (#17). ``/health`` y
``/policies`` derivan del estado real de Qdrant y Ollama (no del indice local,
que no vive en el contenedor).

Correr local:  uv run uvicorn app.api.main:app --port 8000
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.paths import DATA_DIR
from app.rag.config import SUPPORTED_LLM_PROVIDERS, get_settings
from app.rag.llm import get_llm
from app.rag.query import query as rag_query
from app.rag.query import query_stream as rag_query_stream
from app.rag.vectordb import get_client

logger = logging.getLogger(__name__)

app = FastAPI(title="QuePlan API", version="0.3.0")

# PDFs de borradores DEM generados en data/generated (§4.1) — el API los sirve
# tal cual vienen del módulo de generación (app.generation.dem, #36).
_generated = DATA_DIR / "generated"
_generated.mkdir(parents=True, exist_ok=True)
app.mount("/generated", StaticFiles(directory=_generated), name="generated")


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    provider: str | None = Field(
        default=None,
        description="LLM para esta consulta (demo): ollama|openai|anthropic|google. "
        "Default: LLM_PROVIDER del .env.",
    )


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]
    provider: str
    model: str


class RecombineRequest(BaseModel):
    molde: str = Field(min_length=3, max_length=50, examples=["POL320200071"])
    perfil: dict[str, str] = Field(
        description="Condiciones curadas sin PII (dominio canónico, docs/ONTOLOGIA.md §8).",
        examples=[{"edad": "30-40", "fonasa_isapre": "isapre"}],
    )


class RecombineResponse(BaseModel):
    codigo: str
    molde_base: str
    creado_en: str
    perfil: dict[str, str]
    secciones: list[dict[str, Any]]
    pdf_url: str
    aviso: str


def _modelo_actual() -> tuple[str, str]:
    """``(provider, model)`` del LLM configurado (demo: muestra quién responde)."""
    s = get_settings()
    modelos = {
        "ollama": s.ollama_chat_model,
        "openai": s.openai_chat_model,
        "anthropic": s.anthropic_chat_model,
        "google": s.google_chat_model,
    }
    return s.llm_provider, modelos.get(s.llm_provider, "-")


def _validar_provider(provider: str | None) -> str | None:
    if provider and provider.strip().lower() not in SUPPORTED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider no soportado: {provider}. "
            f"Opciones: {', '.join(SUPPORTED_LLM_PROVIDERS)}",
        )
    return (provider.strip().lower() if provider else None)


def _año(poliza: str) -> str | None:
    """Año de la póliza desde su codigo: ``POL<ccc><aa><nnnn>`` → ``20<aa>``."""
    digits = [c for c in poliza if c.isdigit()]
    return f"20{digits[3]}{digits[4]}" if len(digits) >= 5 else None


@app.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest) -> ChatResponse:
    provider = _validar_provider(body.provider)
    try:
        resultado = rag_query(body.question, llm=get_llm(provider=provider))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Fallo query() de %s", body.question[:60])
        raise HTTPException(
            status_code=500, detail=f"error interno: {type(exc).__name__}"
        ) from exc
    provider_ok, model = _modelo_actual()
    if provider:
        provider_ok = provider
    return ChatResponse(
        answer=resultado["answer"],
        sources=resultado["sources"],
        provider=provider_ok,
        model=model,
    )


@app.post("/chat/stream")
def chat_stream(body: ChatRequest) -> StreamingResponse:
    """SSE del pipeline streaming (ADR-006); mismo body que ``/chat``.

    Eventos (líneas ``data: <json>``): status | token | sources | done. En el
    error interno se emite ``{"type": "error"}`` y se corta el stream.
    """
    provider = _validar_provider(body.provider)

    async def gen():
        try:
            llm = get_llm(provider=provider)
            async for ev in rag_query_stream(body.question, llm=llm):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("Fallo query_stream() de %s", body.question[:60])
            yield (
                f"data: {json.dumps({'type': 'error', 'message': f'error interno: {type(exc).__name__}'})}\n\n"
            )

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/policy-recombine", response_model=RecombineResponse)
def policy_recombine(body: RecombineRequest) -> dict[str, Any]:
    """Recombinación DEM demo v0 (#36): molde + perfil curado → borrador §4.1."""
    from app.generation.dem import generar_dem

    try:
        payload, _pdf = generar_dem(molde=body.molde, perfil=body.perfil)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not payload.get("secciones"):
        raise HTTPException(
            status_code=404,
            detail=f"el molde {body.molde} no tiene artículos en data/processed/articulos.jsonl",
        )
    return payload


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
    provider, model = _modelo_actual()
    return {
        "qdrant": qdrant,
        "ollama": ollama,
        "provider": provider,
        "model": model,
    }


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
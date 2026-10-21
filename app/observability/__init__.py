"""Observabilidad en runtime: tracing opcional con Langfuse (#48).

Complementa a G1 (``docs/EVAL.md``): G1 evalua el pipeline en batch contra el
golden set; este modulo traza las consultas reales en el hot path.

    from app.observability import get_tracer

    tracer = get_tracer()          # noop si Langfuse no esta configurado
    with tracer.span("mi.step") as span:
        span.update(output="ok")

Por defecto es noop: sin ``LANGFUSE_ENABLED=true`` + keys, no se importa el SDK
y no se abre ninguna conexion.
"""

from app.observability.tracing import (
    SPAN_HARD_GATE,
    SPAN_LLM,
    SPAN_LLM_WEB,
    SPAN_QUERY,
    SPAN_RETRIEVE,
    SPAN_WEB,
    TYPE_GENERATION,
    TYPE_RETRIEVER,
    TYPE_SPAN,
    TYPE_TOOL,
    LangfuseTracer,
    Span,
    Tracer,
    get_tracer,
    observability_enabled,
    reset_client_cache,
)

__all__ = [
    "SPAN_HARD_GATE",
    "SPAN_LLM",
    "SPAN_LLM_WEB",
    "SPAN_QUERY",
    "SPAN_RETRIEVE",
    "SPAN_WEB",
    "TYPE_GENERATION",
    "TYPE_RETRIEVER",
    "TYPE_SPAN",
    "TYPE_TOOL",
    "LangfuseTracer",
    "Span",
    "Tracer",
    "get_tracer",
    "observability_enabled",
    "reset_client_cache",
]

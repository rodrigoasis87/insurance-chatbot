"""Tests de la observabilidad en runtime (Issue #48).

Sin red y sin Langfuse instalado: se verifica que

1. sin configuracion, el tracer es **noop** y el flujo del pipeline no cambia;
2. con un tracer fake, ``query()`` y ``query_stream()`` emiten los spans
   esperados (retrieve, hard_gate, llm, web) con la metadata de la ruta;
3. un fallo del backend de Langfuse **no** rompe la consulta.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from app.observability import (
    SPAN_HARD_GATE,
    SPAN_LLM,
    SPAN_LLM_WEB,
    SPAN_QUERY,
    SPAN_RETRIEVE,
    SPAN_WEB,
    Tracer,
    get_tracer,
    observability_enabled,
)
from app.observability import tracing as tracing_module
from app.rag import query as qmodule


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class FakeSpan:
    """Span que acumula las actualizaciones para poder inspeccionarlas."""

    def __init__(self, name: str, as_type: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.as_type = as_type
        self.kwargs = kwargs
        self.updates: list[dict[str, Any]] = []
        self.closed = False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)

    def end(self) -> None:
        self.closed = True

    @property
    def metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for upd in self.updates:
            meta.update(upd.get("metadata") or {})
        return meta

    @property
    def output(self) -> Any:
        for upd in reversed(self.updates):
            if "output" in upd:
                return upd["output"]
        return None


class FakeTracer(Tracer):
    """Tracer de mentira: registra los spans abiertos."""

    enabled = True

    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    def _span(self, name: str, as_type: str, kwargs: dict[str, Any]) -> FakeSpan:
        span = FakeSpan(name, as_type, kwargs)
        self.spans.append(span)
        return span

    def span(self, name: str, *, as_type: str = "span", **kwargs: Any):
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            span = self._span(name, as_type, kwargs)
            try:
                yield span
            finally:
                span.end()

        return _ctx()

    def by_name(self, name: str) -> list[FakeSpan]:
        return [s for s in self.spans if s.name == name]


class BrokenClient:
    """Cliente de Langfuse que falla al abrir cualquier span."""

    def start_as_current_observation(self, **kwargs: Any):
        raise RuntimeError("langfuse caido")

    def flush(self) -> None:
        raise RuntimeError("langfuse caido")


def _hit(score: float = 0.75, articulo: int = 13) -> dict[str, Any]:
    return {
        "page_content": "La aseguradora deberá pagar la indemnización...",
        "metadata": {
            "poliza": "POL320200071",
            "articulo": articulo,
            "pagina": 15,
            "titulo_canonico": "Cláusula de Indemnización",
        },
        "score": score,
    }


class FakeLLM:
    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.i = 0

    def invoke(self, messages, **kwargs):
        respuesta = self.respuestas[self.i]
        self.i += 1
        return AIMessage(content=respuesta)


class FakeStreamLLM:
    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.i = 0

    async def astream(self, messages):
        respuesta = self.respuestas[self.i]
        self.i += 1
        for ch in respuesta:
            yield ch


def _web_result() -> qmodule.WebResult:
    return qmodule.WebResult(
        title="Valores isapre 2026",
        url="https://www.superdesalud.gob.cl/valores",
        body="El rango de valores 2026 promedia entre $X y $Y.",
    )


# --------------------------------------------------------------------------- #
# 1. Modo noop (por defecto)
# --------------------------------------------------------------------------- #


def test_sin_configuracion_el_tracer_es_noop(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert observability_enabled() is False
    tracer = get_tracer()
    assert isinstance(tracer, Tracer)
    assert tracer.enabled is False
    with tracer.span("x") as span:
        assert span.active is False
        span.update(output="nada")  # no debe fallar


def test_observability_requiere_enabled_y_las_dos_keys(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert observability_enabled() is False

    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    assert observability_enabled() is True


def test_query_sin_tracer_devuelve_la_misma_respuesta() -> None:
    """El modo noop no altera el contrato de ``query()`` (CONTRACTS §3)."""
    llm = FakeLLM("El plazo es del Art. 13 [fuente: POL320200071 · Art. 13]")
    res = qmodule.query(
        "¿cuál es el plazo de denuncia?",
        llm=llm,
        search_fn=lambda text, top_k: [_hit()],
        web_fn=lambda text, max_results=5: [_web_result()],
        tracer=Tracer(),
    )
    assert "Art. 13" in res["answer"]
    assert res["sources"][0]["origen"] == "poliza"


# --------------------------------------------------------------------------- #
# 2. Spans emitidos por query()
# --------------------------------------------------------------------------- #


def _query_con_tracer(
    respuestas=("El plazo es del Art. 13",),
    hits=None,
    question="¿cuál es el plazo de denuncia?",
    **kwargs,
):
    tracer = FakeTracer()
    llm = FakeLLM(*respuestas)
    res = qmodule.query(
        question,
        llm=llm,
        search_fn=lambda text, top_k: [_hit()] if hits is None else hits,
        web_fn=lambda text, max_results=5: [_web_result()],
        tracer=tracer,
        **kwargs,
    )
    return res, tracer


def test_query_emite_span_raiz_con_la_ruta() -> None:
    res, tracer = _query_con_tracer()
    raiz = tracer.by_name(SPAN_QUERY)
    assert len(raiz) == 1
    assert raiz[0].output == res["answer"]
    assert raiz[0].metadata["route"] == "policy"
    assert raiz[0].kwargs["input"] == "¿cuál es el plazo de denuncia?"


def test_query_emite_spans_de_retrieval_y_hard_gate() -> None:
    _res, tracer = _query_con_tracer(hits=[_hit(score=0.3), _hit(score=0.75)])
    retrieve = tracer.by_name(SPAN_RETRIEVE)
    gate = tracer.by_name(SPAN_HARD_GATE)
    assert len(retrieve) == 1
    assert len(gate) == 1
    # El hard gate deja pasar solo el hit sobre el umbral.
    assert gate[0].metadata["n_candidatos"] == 2
    assert gate[0].metadata["n_hits"] == 1
    assert retrieve[0].metadata["n_hits"] == 1
    assert gate[0].as_type == "span"
    assert retrieve[0].as_type == "retriever"


def test_query_emite_span_de_llm_con_el_prompt_y_la_respuesta() -> None:
    _res, tracer = _query_con_tracer(respuestas=("Respuesta con cita",))
    llm_spans = tracer.by_name(SPAN_LLM)
    assert len(llm_spans) == 1
    assert llm_spans[0].as_type == "generation"
    assert "Fragmentos:" in llm_spans[0].kwargs["input"]
    assert llm_spans[0].output == "Respuesta con cita"
    assert llm_spans[0].metadata["need_web"] is False


def test_query_ruta_web_emite_spans_de_web_y_de_llm_web() -> None:
    res, tracer = _query_con_tracer(
        respuestas=("NEED_WEB", "Los valores promedian $X-$Y [fuente web: https://url]"),
        question="¿qué rango de valores de mercado hay para isapre 2026?",
    )
    raiz = tracer.by_name(SPAN_QUERY)
    assert raiz[0].metadata["route"] == "web"
    assert raiz[0].metadata["n_fuentes_web"] == 1
    assert len(tracer.by_name(SPAN_WEB)) == 1
    assert len(tracer.by_name(SPAN_LLM_WEB)) == 1
    assert len(tracer.by_name(SPAN_LLM)) == 1
    assert res["sources"][-1]["origen"] == "web"


def test_query_ruta_abstain_no_emite_llm() -> None:
    _res, tracer = _query_con_tracer(hits=[_hit(score=0.3)])
    raiz = tracer.by_name(SPAN_QUERY)
    assert raiz[0].metadata["route"] == "abstain"
    assert tracer.by_name(SPAN_LLM) == []


def test_query_need_web_fuera_de_dominio_abstiene() -> None:
    """NEED_WEB fuera del rubro NO dispara la web (ADR-005)."""
    _res, tracer = _query_con_tracer(respuestas=("NEED_WEB",))
    assert tracer.by_name(SPAN_QUERY)[0].metadata["route"] == "abstain"
    assert tracer.by_name(SPAN_WEB) == []
    assert tracer.by_name(SPAN_LLM_WEB) == []


def test_query_ruta_web_failed_no_emite_llm_web() -> None:
    tracer = FakeTracer()
    llm = FakeLLM("NEED_WEB")

    def web_rota(text, max_results=5):
        raise qmodule.WebSearchError("rate-limit")

    res = qmodule.query(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        llm=llm,
        search_fn=lambda text, top_k: [_hit(score=0.62)],
        web_fn=web_rota,
        tracer=tracer,
    )
    assert res["answer"] == qmodule.NO_EN_WEB_DISPONIBLE
    assert tracer.by_name(SPAN_QUERY)[0].metadata["route"] == "web_failed"
    # El span de web SI existe: registra la llamada fallida.
    assert len(tracer.by_name(SPAN_WEB)) == 1
    assert tracer.by_name(SPAN_LLM_WEB) == []


# --------------------------------------------------------------------------- #
# 3. Spans emitidos por query_stream()
# --------------------------------------------------------------------------- #


def _stream_con_tracer(respuestas=("Respuesta con cita",), hits=None):
    tracer = FakeTracer()
    llm = FakeStreamLLM(*respuestas)
    search_fn = lambda text, top_k: [_hit()] if hits is None else hits

    async def _run():
        return [
            ev
            async for ev in qmodule.query_stream(
                "¿cuál es el plazo de denuncia?",
                llm=llm,
                search_fn=search_fn,
                web_fn=lambda text, max_results=5: [_web_result()],
                tracer=tracer,
            )
        ]

    return asyncio.run(_run()), tracer


def test_stream_emite_span_raiz_con_la_ruta_y_la_respuesta() -> None:
    eventos, tracer = _stream_con_tracer()
    raiz = tracer.by_name(SPAN_QUERY)
    assert len(raiz) == 1
    assert raiz[0].metadata["route"] == "policy"
    esperado = "".join(ev["text"] for ev in eventos if ev["type"] == "token")
    assert raiz[0].output == esperado


def test_stream_emite_spans_de_retrieval_y_llm() -> None:
    _eventos, tracer = _stream_con_tracer()
    assert len(tracer.by_name(SPAN_RETRIEVE)) == 1
    assert len(tracer.by_name(SPAN_HARD_GATE)) == 1
    llm_spans = tracer.by_name(SPAN_LLM)
    assert len(llm_spans) == 1
    assert llm_spans[0].as_type == "generation"
    assert llm_spans[0].output == "Respuesta con cita"


def test_stream_ruta_abstain_no_emite_llm() -> None:
    _eventos, tracer = _stream_con_tracer(hits=[_hit(score=0.3)])
    assert tracer.by_name(SPAN_QUERY)[0].metadata["route"] == "abstain"
    assert tracer.by_name(SPAN_LLM) == []


# --------------------------------------------------------------------------- #
# 4. Robustez: un Langfuse caido no rompe la consulta
# --------------------------------------------------------------------------- #


def test_langfuse_roto_no_rompe_la_consulta() -> None:
    """Un backend caido degrada a noop: la respuesta sigue siendo la misma."""
    from app.observability.tracing import LangfuseTracer

    tracer = LangfuseTracer(BrokenClient())
    llm = FakeLLM("El plazo es del Art. 13 [fuente: POL320200071 · Art. 13]")
    res = qmodule.query(
        "¿cuál es el plazo de denuncia?",
        llm=llm,
        search_fn=lambda text, top_k: [_hit()],
        web_fn=lambda text, max_results=5: [_web_result()],
        tracer=tracer,
    )
    assert "Art. 13" in res["answer"]
    assert res["sources"][0]["poliza"] == "POL320200071"


def test_langfuse_roto_no_rompe_el_streaming() -> None:
    from app.observability.tracing import LangfuseTracer

    tracer = LangfuseTracer(BrokenClient())
    llm = FakeStreamLLM("Respuesta con cita")

    async def _run():
        return [
            ev
            async for ev in qmodule.query_stream(
                "¿cuál es el plazo de denuncia?",
                llm=llm,
                search_fn=lambda text, top_k: [_hit()],
                web_fn=lambda text, max_results=5: [_web_result()],
                tracer=tracer,
            )
        ]

    eventos = asyncio.run(_run())
    assert "".join(ev["text"] for ev in eventos if ev["type"] == "token") == (
        "Respuesta con cita"
    )


def test_excepcion_del_cuerpo_del_span_se_propaga() -> None:
    """La instrumentacion no se come las excepciones del pipeline."""
    from app.observability.tracing import LangfuseTracer

    class ClienteOk:
        def start_as_current_observation(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tracer = LangfuseTracer(ClienteOk())
    with pytest.raises(ValueError):
        with tracer.span("boom"):
            raise ValueError("fallo real")


def test_reset_client_cache_no_rompe(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-x")
    tracing_module.reset_client_cache()
    assert tracing_module._client_cache is None


# --------------------------------------------------------------------------- #
# 5. session_id: agrupar los traces de una conversacion
# --------------------------------------------------------------------------- #


def test_query_propaga_el_session_id_al_span_raiz() -> None:
    _res, tracer = _query_con_tracer(session_id="conv-42")
    assert tracer.by_name(SPAN_QUERY)[0].kwargs["session_id"] == "conv-42"


def test_query_sin_session_id_no_agrega_la_clave() -> None:
    _res, tracer = _query_con_tracer()
    assert tracer.by_name(SPAN_QUERY)[0].kwargs["session_id"] is None


def test_stream_propaga_el_session_id_al_span_raiz() -> None:
    tracer = FakeTracer()

    async def _run():
        return [
            ev
            async for ev in qmodule.query_stream(
                "¿cuál es el plazo de denuncia?",
                llm=FakeStreamLLM("Respuesta con cita"),
                search_fn=lambda text, top_k: [_hit()],
                web_fn=lambda text, max_results=5: [_web_result()],
                tracer=tracer,
                session_id="conv-42",
            )
        ]

    asyncio.run(_run())
    assert tracer.by_name(SPAN_QUERY)[0].kwargs["session_id"] == "conv-42"


def test_langfuse_tracer_propaga_el_session_id_a_los_hijos(monkeypatch) -> None:
    """El ``session_id`` se propaga con ``propagate_attributes`` del SDK."""
    import langfuse

    from app.observability.tracing import LangfuseTracer

    vistos: list[dict[str, Any]] = []

    @contextmanager
    def fake_propagate(**kwargs: Any):
        vistos.append(kwargs)
        yield

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)

    class ClienteOk:
        def start_as_current_observation(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tracer = LangfuseTracer(ClienteOk())
    with tracer.span("rag.query", session_id="conv-42"):
        pass
    assert vistos == [{"session_id": "conv-42"}]


def test_langfuse_tracer_sin_session_id_no_propaga(monkeypatch) -> None:
    import langfuse

    from app.observability.tracing import LangfuseTracer

    def explota(**kwargs: Any):
        raise AssertionError("no deberia propagar sin session_id")

    monkeypatch.setattr(langfuse, "propagate_attributes", explota)

    class ClienteOk:
        def start_as_current_observation(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tracer = LangfuseTracer(ClienteOk())
    with tracer.span("rag.query"):
        pass


def test_excepcion_del_span_con_session_id_se_propaga(monkeypatch) -> None:
    """Regresion: el error del cuerpo debe salir una sola vez y propagarse."""
    import langfuse

    from app.observability.tracing import LangfuseTracer

    @contextmanager
    def fake_propagate(**kwargs: Any):
        yield

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)

    class ClienteOk:
        def start_as_current_observation(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    tracer = LangfuseTracer(ClienteOk())
    with pytest.raises(ValueError):
        with tracer.span("rag.query", session_id="conv-42"):
            raise ValueError("fallo real")


def test_flush_del_tracer_no_rompe(monkeypatch) -> None:
    """El flush del API al apagar no puede romper el cierre."""
    from app.observability.tracing import LangfuseTracer

    class ClienteFlushRoto:
        def start_as_current_observation(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def flush(self):
            raise RuntimeError("langfuse caido")

    LangfuseTracer(ClienteFlushRoto()).flush()  # no debe levantar


def test_api_hace_flush_de_la_observabilidad_al_apagar() -> None:
    """El lifespan del API manda los traces pendientes antes de morir."""
    from fastapi.testclient import TestClient

    from app.api import main as api_main

    called: list[bool] = []

    class TracerFalso:
        enabled = True

        def flush(self) -> None:
            called.append(True)

    original = api_main.get_tracer
    api_main.get_tracer = lambda: TracerFalso()  # type: ignore[assignment]
    try:
        with TestClient(api_main.app):
            # Mientras el API esta vivo no se hace flush.
            assert called == []
    finally:
        api_main.get_tracer = original  # type: ignore[assignment]
    # Al apagar, los traces pendientes se envian.
    assert called == [True]


def test_api_acepta_session_id_opcional(monkeypatch: pytest.MonkeyPatch) -> None:
    """El campo es opcional y aditivo: el body viejo sigue siendo valido."""
    from fastapi.testclient import TestClient

    from app.api import main as api_main

    # Modo dev: este test no ejercita la auth (#44) y no debe depender de una
    # API_KEY del .env del desarrollador.
    monkeypatch.delenv("API_KEY", raising=False)

    capturado: dict[str, Any] = {}

    def fake_query(question: str = "", **kwargs):
        capturado.update(kwargs)
        return {"answer": "ok", "sources": []}

    monkeypatch.setattr(api_main, "rag_query", fake_query)
    client = TestClient(api_main.app)

    res = client.post("/chat", json={"question": "¿plazo?"})
    assert res.status_code == 200
    assert "session_id" not in capturado

    res = client.post("/chat", json={"question": "¿plazo?", "session_id": "conv-1"})
    assert res.status_code == 200
    assert capturado["session_id"] == "conv-1"

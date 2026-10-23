"""Pipeline de consulta RAG (Issue #17, CONTRACTS §3).

``query()`` es el agente acotado del MVP (ADR-004/005):

1. ``search()`` → hits colapsados por ``(poliza, articulo)`` (CONTRACTS §2).
2. **Hard gate ``UMBRAL_SCORE`` en codigo**: los hits que no lo superan jamas
   entran al prompt. Con 0 hits sobrevivientes → respuesta curada de alcance,
   sin llamar al LLM.
3. 1.ª llamada LLM *grounded* con citas internas ``[fuente: POL · Art. N]``.
4. Solo si la 1.ª llama devuelve ``NEED_WEB`` y la pregunta es del **rubro**
   (guardrail por keywords) → ``web_search`` (1 vez) → 2.ª llamada LLM citando
   la fuente externa con ``[fuente web: <url>]``.

Nunca mas de 2 llamadas LLM ni 1 búsqueda web por consulta (ADR-005).

``query_stream()`` es la variante **streaming** (ADR-006, demo): emite eventos
``{type: status|token|sources|done}`` y detecta ``NEED_WEB`` por peek del
primer token (la generacion grounded se muestra en vivo; si el LLM corta con
``NEED_WEB``, se descarta y se regenera con la web), conservando ≤2
generaciones LLM.

Ambas variantes aceptan un ``tracer`` opcional (``app.observability``): con
Langfuse configurado, cada paso del pipeline queda trazado en el hot path. Sin
Langfuse, el tracer es un noop y el flujo no cambia (ver docs/OBSERVABILITY.md).
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.observability import (
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
    Tracer,
    get_tracer,
)
from app.rag.config import get_settings
from app.rag.llm import get_llm
from app.rag.vectordb import search as _search
from app.rag.web_search import WebResult, web_search as _web_search, WebSearchError

# Señal que devuelve la 1.ª llamada cuando quiere citar datos de mercado.
NEED_WEB = "NEED_WEB"

# Mensajes curados de cobertura/alcance: no dependen del LLM (CONTRACTS §3 vol.5).
NO_EN_FUENTES = (
    "Con las fuentes disponibles (las pólizas del depósito) no encuentro "
    "evidencia para responder con certeza. Este asistente es documental: "
    "informa qué cubre o condiciona un contrato (cobertura, exclusiones, "
    "plazos de denuncia, obligaciones), no decide ni tarifica. Si querés, "
    "podés rehacer la pregunta dentro de ese alcance o acudir al canal "
    "oficial de la aseguradora."
)
NO_EN_WEB_DISPONIBLE = (
    "Tu pregunta requiere datos de mercado actualizados y la búsqueda externa "
    "no devolvió resultados. Probá de nuevo o acotá la consulta (por ejemplo, "
    "un beneficio o una cobertura concreta)."
)

# Keywords del rubro asegurador para habilitar web_search (guardrail de dominio):
# precios/valores vigentes no viven en el corpus de pólizas. Términos ligados a
# tarifas de salud y mercado, no genéricos ("beneficios" se fue por lo ancho).
DOMINIO_KEYWORDS = (
    "precio",
    "precios",
    "valor",
    "valores",
    "costo",
    "costos",
    "isapre",
    "fonasa",
    "mercado",
    "prima",
    "tarifa",
    "bonificacion",
    "arancel",
)

SYSTEM_1 = """Eres el asistente documental de una corredora de seguros chilena
(QuePlan.cl), que responde sobre las pólizas del Depósito de Pólizas de la CMF.
Responde EN ESPAÑOL, en no más de 300 palabras, SOLO con la evidencia de los
Fragmentos citados. Reglas:

1. Cada afirmación lleva su cita inline con este formato exacto:
   [fuente: POL320200071 · Art. 13].
2. Si la pregunta pide valores o precios de mercado actualizados (rango de
   primas, valores isapre/fonasa, beneficios vigentes, tarifas) y los
   Fragmentos no bastan, responde únicamente con el texto EXACTO:
   NEED_WEB (ninguna otra palabra).
3. Si la pregunta está fuera de las fuentes y NO corresponde buscar en web,
   responde: "no está en las fuentes" y reitera el alcance del asistente.
4. No inventes, no adivines y no cites nada que no esté en los Fragmentos."""

SYSTEM_2 = """Eres el asistente documental de una corredora de seguros chilena
(QuePlan.cl). Recibes resultados de búsqueda web (datos de mercado) porque el
corpus de pólizas no alcanzaba. Responde EN ESPAÑOL, en no más de 200 palabras,
SOLO con estos resultados. Reglas:

1. Marca explícitamente que la respuesta proviene de fuentes externas de
   internet (no de pólizas del depósito).
2. Cada afirmación lleva su cita inline con este formato exacto:
   [fuente web: <url de la que salió esa afirmación>].
3. Sintetiza la información que SÍ aparece en los resultados, aunque sea
   parcial; si los resultados solo nombran planes o páginas sin cifras, decilo
   y detallá las fuentes. Solo si ninguno aporta nada a la pregunta, responde:
   "no está en las fuentes".
4. No inventes ni mezcles información que no esté en los resultados."""

SearchHit = dict[str, Any]
QueryResponse = dict[str, Any]

# Rutas posibles de una consulta (CONTRACTS §3). Se usan como metadata del span
# raiz en la observabilidad y coinciden con el "route" del trace de eval.
ROUTE_POLICY = "policy"
ROUTE_WEB = "web"
ROUTE_ABSTAIN = "abstain"
ROUTE_WEB_FAILED = "web_failed"


def _pasa_gate(hits: list[SearchHit], umbral: float) -> list[SearchHit]:
    """Hard gate (ADR-004): solo los hits con ``score >= umbral`` llegan al prompt."""
    return [h for h in hits if h["score"] >= umbral]


def _modelo(llm: BaseChatModel) -> str:
    """Nombre del modelo del LLM, para la metadata de la observabilidad."""
    for attr in ("model", "model_name", "model_id"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value:
            return value
    return "desconocido"


def _resumen_hits(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Resumen compacto de los hits (sin el texto) para la metadata del trace."""
    return [
        {
            "poliza": hit["metadata"].get("poliza"),
            "articulo": hit["metadata"].get("articulo"),
            "pagina": hit["metadata"].get("pagina"),
            "score": hit.get("score"),
        }
        for hit in hits
    ]


def _resumen_fuentes(sources: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta las fuentes por origen (poliza / web) de una respuesta."""
    return {
        "n_fuentes": len(sources),
        "n_fuentes_poliza": sum(1 for s in sources if s.get("origen") == "poliza"),
        "n_fuentes_web": sum(1 for s in sources if s.get("origen") == "web"),
    }


def es_del_dominio(question: str) -> bool:
    """Guardrail de dominio: habilita web_search solo para el rubro (ADR-005)."""
    q = question.lower()
    return any(kw in q for kw in DOMINIO_KEYWORDS)


def _format_fragment(index: int, hit: SearchHit) -> str:
    meta = hit["metadata"]
    pagina = meta.get("pagina", "-")
    return (
        f"[{index}] {meta['poliza']} · Art. {meta['articulo']} · pág. {pagina}:\n"
        f"{hit['page_content']}"
    )


def _build_fragments(hits: list[SearchHit]) -> str:
    return "\n\n".join(
        _format_fragment(index, hit) for index, hit in enumerate(hits, start=1)
    )


def _format_web_result(index: int, result: WebResult) -> str:
    return f"[{index}] {result.title} ({result.url}):\n{result.body}"


def _build_web_fragments(results: list[WebResult]) -> str:
    return "\n\n".join(
        _format_web_result(index, result)
        for index, result in enumerate(results, start=1)
    )


def _sources_poliza(hits: list[SearchHit]) -> list[dict[str, Any]]:
    return [
        {
            "origen": "poliza",
            "poliza": hit["metadata"]["poliza"],
            "ramo": hit["metadata"].get("ramo"),
            "articulo": hit["metadata"]["articulo"],
            "pagina": hit["metadata"].get("pagina"),
            "titulo": hit["metadata"].get("titulo_canonico"),
            "score": hit["score"],
            "fragmento": hit["page_content"][:300],
        }
        for hit in hits
    ]


def _sources_web(results: list[WebResult]) -> list[dict[str, Any]]:
    return [
        {"origen": "web", "url": r.url, "titulo": r.title, "fragmento": r.body[:300]}
        for r in results
    ]


def _primera_llamada(
    llm: BaseChatModel,
    question: str,
    hits: list[SearchHit],
    tracer: Tracer | None = None,
) -> tuple[str, bool]:
    """1.ª llamada grounded. Devuelve ``(texto, need_web)``."""
    user = f"Pregunta: {question}\n\nFragmentos:\n{_build_fragments(hits)}"
    tracer = tracer or get_tracer()
    with tracer.span(
        SPAN_LLM,
        as_type=TYPE_GENERATION,
        input=user,
        model=_modelo(llm),
        metadata={"n_fragmentos": len(hits), "llm": "1"},
    ) as span:
        msg = llm.invoke([SystemMessage(SYSTEM_1), HumanMessage(user)])
        answer = str(msg.content).strip()
        span.update(output=answer, metadata={"need_web": answer.upper().startswith(NEED_WEB)})
    return answer, answer.upper().startswith(NEED_WEB)


def _intento_web(
    llm: BaseChatModel,
    web_fn: Callable[[str, int], list[WebResult]],
    question: str,
    trace: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
    tracer: Tracer | None = None,
) -> tuple[QueryResponse, str]:
    """Búsqueda externa única (ADR-005). Falla degradada a sin-fuente-web.

    Devuelve ``(respuesta, ruta)``: la ruta es ``"web"`` o ``"web_failed"``.
    """
    tracer = tracer or get_tracer()
    try:
        if progress:
            progress("buscando fuentes web")
        with tracer.span(SPAN_WEB, as_type=TYPE_TOOL, input=question) as span:
            results = web_fn(question)
            span.update(
                output=[{"titulo": r.title, "url": r.url} for r in results],
                metadata={"n_resultados": len(results)},
            )
    except WebSearchError:
        if trace is not None:
            trace.update({"route": ROUTE_WEB_FAILED, "answer_contexts": []})
        return {"answer": NO_EN_WEB_DISPONIBLE, "sources": []}, ROUTE_WEB_FAILED
    if trace is not None:
        web_contexts = [
            _format_web_result(index, result)
            for index, result in enumerate(results, start=1)
        ]
        trace.update(
            {
                "route": ROUTE_WEB,
                "web_retrieved_contexts": web_contexts,
                # SYSTEM_2 recibe únicamente resultados web; la respuesta final
                # ya no se genera con los fragmentos de la primera llamada.
                "answer_contexts": web_contexts,
            }
        )
    if progress:
        progress("generando respuesta con fuentes web")
    respuesta = _segunda_llamada_web(llm, question, results, tracer)
    return {
        "answer": respuesta,
        "sources": _sources_web(results),
    }, ROUTE_WEB


def _segunda_llamada_web(
    llm: BaseChatModel,
    question: str,
    results: list[WebResult],
    tracer: Tracer | None = None,
) -> str:
    frags = _build_web_fragments(results)
    user = f"Pregunta: {question}\n\nResultados web:\n{frags}"
    tracer = tracer or get_tracer()
    with tracer.span(
        SPAN_LLM_WEB,
        as_type=TYPE_GENERATION,
        input=user,
        model=_modelo(llm),
        metadata={"n_resultados": len(results), "llm": "2"},
    ) as span:
        msg = llm.invoke([SystemMessage(SYSTEM_2), HumanMessage(user)])
        answer = str(msg.content).strip()
        span.update(output=answer)
    return answer


def _recupera(
    question: str,
    top_k: int,
    search_fn: Callable[..., list[SearchHit]],
    tracer: Tracer,
) -> tuple[list[SearchHit], list[SearchHit], float]:
    """Recuperacion + hard gate, trazada. Devuelve ``(candidatos, hits, umbral)``."""
    umbral = get_settings().umbral_score
    with tracer.span(
        SPAN_RETRIEVE,
        as_type=TYPE_RETRIEVER,
        input=question,
        metadata={"top_k": top_k},
    ) as span:
        candidates = search_fn(question, top_k=top_k)
        with tracer.span(
            SPAN_HARD_GATE,
            as_type=TYPE_SPAN,
            metadata={"umbral": umbral, "n_candidatos": len(candidates)},
        ) as gate:
            hits = _pasa_gate(candidates, umbral)
            gate.update(
                output=_resumen_hits(hits),
                metadata={"n_candidatos": len(candidates), "n_hits": len(hits)},
            )
        span.update(
            output=_resumen_hits(hits),
            metadata={"n_candidatos": len(candidates), "n_hits": len(hits)},
        )
    return candidates, hits, umbral


def query(
    question: str,
    *,
    top_k: int = 5,
    use_web: bool = True,
    llm: BaseChatModel | None = None,
    search_fn: Callable[..., list[SearchHit]] | None = None,
    web_fn: Callable[[str, int], list[WebResult]] | None = None,
    trace: dict[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
    tracer: Tracer | None = None,
    session_id: str | None = None,
) -> QueryResponse:
    """Responde una consulta con citas (≤2 llamadas LLM, ≤1 búsqueda web).

    Returns:
        ``{"answer": str, "sources": list}`` (CONTRACTS §3). ``sources`` con
        ``origen: "poliza"`` (poliza/articulo/pagina) y/o ``origen: "web"``
        (url/titulo).

    Args:
        tracer: tracer de observabilidad (Langfuse). Si es ``None`` se usa el
            global (``app.observability.get_tracer()``), que es noop cuando
            Langfuse no esta configurado.
        session_id: identificador de conversacion; agrupa los traces de la
            misma sesion en Langfuse (opcional, no afecta la respuesta).
    """
    tracer = tracer or get_tracer()
    search_fn = search_fn or _search
    web_fn = web_fn or _web_search
    llm = llm or get_llm()

    with tracer.span(
        SPAN_QUERY, as_type=TYPE_SPAN, input=question, session_id=session_id
    ) as root:
        resultado, ruta = _query_impl(
            question=question,
            top_k=top_k,
            use_web=use_web,
            llm=llm,
            search_fn=search_fn,
            web_fn=web_fn,
            trace=trace,
            progress=progress,
            tracer=tracer,
        )
        root.update(
            output=resultado["answer"],
            metadata={"route": ruta, **_resumen_fuentes(resultado["sources"])},
        )
        return resultado


def _query_impl(
    *,
    question: str,
    top_k: int,
    use_web: bool,
    llm: BaseChatModel,
    search_fn: Callable[..., list[SearchHit]],
    web_fn: Callable[[str, int], list[WebResult]],
    trace: dict[str, Any] | None,
    progress: Callable[[str], None] | None,
    tracer: Tracer,
) -> tuple[QueryResponse, str]:
    """Cuerpo de ``query()``. Devuelve ``(respuesta, ruta)``."""
    if progress:
        progress("recuperando documentos de Qdrant")
    candidates, hits, _umbral = _recupera(question, top_k, search_fn, tracer)
    if trace is not None:
        policy_contexts = [
            _format_fragment(index, hit) for index, hit in enumerate(hits, start=1)
        ]
        trace.clear()
        trace.update(
            {
                "route": ROUTE_POLICY,
                "retrieval_candidates": [
                    {"metadata": hit["metadata"], "score": hit["score"]}
                    for hit in candidates
                ],
                "retrieval_hits": [
                    {"metadata": hit["metadata"], "score": hit["score"]}
                    for hit in hits
                ],
                "policy_retrieved_contexts": policy_contexts,
                "web_retrieved_contexts": [],
                "answer_contexts": policy_contexts,
            }
        )
    if progress:
        progress(f"recuperación lista: {len(hits)} fragmentos pasan el umbral")
    if not hits:
        # Sin contexto certero: con pregunta del rubro se delega a la web
        # (CONTRACTS §3 paso 4); si no, respuesta curada de alcance.
        if use_web and es_del_dominio(question):
            return _intento_web(llm, web_fn, question, trace, progress, tracer)
        if trace is not None:
            trace.update({"route": ROUTE_ABSTAIN, "answer_contexts": []})
        return {"answer": NO_EN_FUENTES, "sources": []}, ROUTE_ABSTAIN

    if progress:
        progress("generando respuesta con el modelo")
    respuesta, need_web = _primera_llamada(llm, question, hits, tracer)
    if not need_web:
        return (
            {"answer": respuesta, "sources": _sources_poliza(hits)},
            ROUTE_POLICY,
        )

    # 1.ª llama pidió web: solo se consulta si corresponde al rubro (ADR-005).
    if not (use_web and es_del_dominio(question)):
        if trace is not None:
            trace.update({"route": ROUTE_ABSTAIN, "answer_contexts": []})
        return {"answer": NO_EN_FUENTES, "sources": []}, ROUTE_ABSTAIN

    web, ruta = _intento_web(llm, web_fn, question, trace, progress, tracer)
    return {
        "answer": web["answer"],
        "sources": _sources_poliza(hits) + web["sources"],
    }, ruta


def _chunk_text(chunk: Any) -> str:
    """Texto plano de un chunk de ``BaseChatModel.astream`` (str o AIMessageChunk)."""
    if isinstance(chunk, str):
        return chunk
    content = getattr(chunk, "content", chunk)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text"):
                parts.append(part["text"])
        return "".join(parts)
    return str(content or "")


async def _astream_tokens(
    llm: BaseChatModel,
    msgs: list,
    tracer: Tracer | None = None,
    *,
    name: str = SPAN_LLM,
    metadata: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Todos los tokens (evento ``token``) de una generación de chat, trazada."""
    tracer = tracer or get_tracer()
    prompt = str(getattr(msgs[-1], "content", "")) if msgs else ""
    with tracer.span(
        name,
        as_type=TYPE_GENERATION,
        input=prompt,
        model=_modelo(llm),
        metadata=metadata or {},
    ) as span:
        acumulado: list[str] = []
        async for chunk in llm.astream(msgs):
            tok = _chunk_text(chunk)
            if tok:
                acumulado.append(tok)
                yield {"type": "token", "text": tok}
        span.update(output="".join(acumulado))


def _frags_web(results: list[WebResult]) -> str:
    return "\n\n".join(
        f"[{i}] {r.title} ({r.url}):\n{r.body}" for i, r in enumerate(results, start=1)
    )


async def query_stream(
    question: str,
    *,
    top_k: int = 5,
    use_web: bool = True,
    llm: BaseChatModel | None = None,
    search_fn: Callable[..., list[SearchHit]] | None = None,
    web_fn: Callable[[str, int], list[WebResult]] | None = None,
    tracer: Tracer | None = None,
    session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Variante streaming de ``query()`` (mismo flujo y ≤2 llamadas LLM).

    Emite eventos dict por cada paso:
        {"type": "status", "kind": "searching" | "llm" | "web"}
        {"type": "token", "text": "<fragmento>"}
        {"type": "sources", "sources": [...]}
        {"type": "done"}

    La 1.ª generación grounded se emite en vivo por tokens; si los primeros
    tokens forman ``NEED_WEB`` se corta (no se muestra) y se regenera con la
    2.ª llamada (web). El cliente consume ``token`` como respuesta y ``sources``
    al final.

    Args:
        tracer: tracer de observabilidad (Langfuse). Si es ``None`` se usa el
            global (``app.observability.get_tracer()``), que es noop cuando
            Langfuse no esta configurado.
        session_id: identificador de conversacion; agrupa los traces de la
            misma sesion en Langfuse (opcional, no altera los eventos SSE).
    """
    tracer = tracer or get_tracer()
    with tracer.span(
        SPAN_QUERY, as_type=TYPE_SPAN, input=question, session_id=session_id
    ) as root:
        estado: dict[str, Any] = {"route": ROUTE_POLICY}
        respuesta: list[str] = []
        async for ev in _query_stream_impl(
            question=question,
            top_k=top_k,
            use_web=use_web,
            llm=llm,
            search_fn=search_fn,
            web_fn=web_fn,
            tracer=tracer,
            estado=estado,
        ):
            if ev.get("type") == "token":
                respuesta.append(str(ev.get("text", "")))
            yield ev
        root.update(
            output="".join(respuesta),
            metadata={"route": estado.get("route", ROUTE_POLICY)},
        )


async def _query_stream_impl(
    *,
    question: str,
    top_k: int,
    use_web: bool,
    llm: BaseChatModel | None,
    search_fn: Callable[..., list[SearchHit]] | None,
    web_fn: Callable[[str, int], list[WebResult]] | None,
    tracer: Tracer,
    estado: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    """Cuerpo de ``query_stream()``. La ruta tomada queda en ``estado["route"]``."""
    search_fn = search_fn or _search
    web_fn = web_fn or _web_search
    llm = llm or get_llm()

    yield {"type": "status", "kind": "searching"}
    _candidates, hits, _umbral = _recupera(question, top_k, search_fn, tracer)

    if not hits:
        # Sin contexto certero: rubro → web directo; si no, texto curado.
        if use_web and es_del_dominio(question):
            estado["route"] = ROUTE_WEB
            yield {"type": "status", "kind": "web"}
            try:
                with tracer.span(SPAN_WEB, as_type=TYPE_TOOL, input=question) as span:
                    results = web_fn(question)
                    span.update(
                        output=[{"titulo": r.title, "url": r.url} for r in results],
                        metadata={"n_resultados": len(results)},
                    )
            except WebSearchError:
                estado["route"] = ROUTE_WEB_FAILED
                yield {"type": "token", "text": NO_EN_WEB_DISPONIBLE}
                yield {"type": "sources", "sources": []}
                yield {"type": "done", "reason": "web_error"}
                return
            async for ev in _astream_tokens(
                llm,
                [
                    SystemMessage(SYSTEM_2),
                    HumanMessage(
                        f"Pregunta: {question}\n\nResultados web:\n{_frags_web(results)}"
                    ),
                ],
                tracer,
                name=SPAN_LLM_WEB,
                metadata={"n_resultados": len(results), "llm": "2"},
            ):
                yield ev
            yield {"type": "sources", "sources": _sources_web(results)}
            yield {"type": "done"}
            return

        estado["route"] = ROUTE_ABSTAIN
        yield {"type": "token", "text": NO_EN_FUENTES}
        yield {"type": "sources", "sources": []}
        yield {"type": "done"}
        return

    fuentes_poliza = _sources_poliza(hits)
    user1 = f"Pregunta: {question}\n\nFragmentos:\n{_build_fragments(hits)}"
    msgs1 = [SystemMessage(SYSTEM_1), HumanMessage(user1)]

    # 1.ª generación con peek: emitir en vivo salvo que arranque con NEED_WEB.
    yield {"type": "status", "kind": "llm"}
    pendiente: list[str] = []
    decidido = False
    pide_web = False
    with tracer.span(
        SPAN_LLM,
        as_type=TYPE_GENERATION,
        input=user1,
        model=_modelo(llm),
        metadata={"n_fragmentos": len(hits), "llm": "1"},
    ) as span:
        generado: list[str] = []
        async for chunk in llm.astream(msgs1):
            tok = _chunk_text(chunk)
            if not tok:
                continue
            generado.append(tok)
            if decidido:
                yield {"type": "token", "text": tok}
                continue
            prueba = "".join(pendiente) + tok
            if NEED_WEB.startswith(prueba):
                pendiente.append(tok)
                if prueba == NEED_WEB:
                    decidido = True
                    pide_web = True
                continue
            # Ya no puede ser NEED_WEB: esta generación grounded se muestra.
            decidido = True
            pide_web = False
            for t in pendiente:
                yield {"type": "token", "text": t}
            pendiente = []
            yield {"type": "token", "text": tok}
        span.update(output="".join(generado), metadata={"need_web": pide_web})

    if pide_web:
        # 1.ª llama pidió web: solo si corresponde al rubro (ADR-005).
        if use_web and es_del_dominio(question):
            estado["route"] = ROUTE_WEB
            yield {"type": "status", "kind": "web"}
            try:
                with tracer.span(SPAN_WEB, as_type=TYPE_TOOL, input=question) as span:
                    results = web_fn(question)
                    span.update(
                        output=[{"titulo": r.title, "url": r.url} for r in results],
                        metadata={"n_resultados": len(results)},
                    )
            except WebSearchError:
                estado["route"] = ROUTE_WEB_FAILED
                yield {"type": "token", "text": NO_EN_WEB_DISPONIBLE}
                yield {"type": "sources", "sources": fuentes_poliza}
                yield {"type": "done", "reason": "web_error"}
                return
            async for ev in _astream_tokens(
                llm,
                [
                    SystemMessage(SYSTEM_2),
                    HumanMessage(
                        f"Pregunta: {question}\n\nResultados web:\n{_frags_web(results)}"
                    ),
                ],
                tracer,
                name=SPAN_LLM_WEB,
                metadata={"n_resultados": len(results), "llm": "2"},
            ):
                yield ev
            yield {"type": "sources", "sources": fuentes_poliza + _sources_web(results)}
            yield {"type": "done"}
            return
        # Fuera del rubro: misma cobertura que la variante no-stream.
        estado["route"] = ROUTE_ABSTAIN
        yield {"type": "token", "text": NO_EN_FUENTES}
        yield {"type": "sources", "sources": []}
        yield {"type": "done"}
        return

    # Grounded: los tokens ya se emitieron en vivo.
    estado["route"] = ROUTE_POLICY
    yield {"type": "sources", "sources": fuentes_poliza}
    yield {"type": "done"}

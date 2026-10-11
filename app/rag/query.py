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
"""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

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


def _pasa_gate(hits: list[SearchHit], umbral: float) -> list[SearchHit]:
    """Hard gate (ADR-004): solo los hits con ``score >= umbral`` llegan al prompt."""
    return [h for h in hits if h["score"] >= umbral]


def es_del_dominio(question: str) -> bool:
    """Guardrail de dominio: habilita web_search solo para el rubro (ADR-005)."""
    q = question.lower()
    return any(kw in q for kw in DOMINIO_KEYWORDS)


def _build_fragments(hits: list[SearchHit]) -> str:
    frags = []
    for i, hit in enumerate(hits, start=1):
        meta = hit["metadata"]
        pagina = meta.get("pagina", "-")
        frags.append(
            f"[{i}] {meta['poliza']} · Art. {meta['articulo']} · pág. {pagina}:\n"
            f"{hit['page_content']}"
        )
    return "\n\n".join(frags)


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
    llm: BaseChatModel, question: str, hits: list[SearchHit]
) -> tuple[str, bool]:
    """1.ª llamada grounded. Devuelve ``(texto, need_web)``."""
    user = f"Pregunta: {question}\n\nFragmentos:\n{_build_fragments(hits)}"
    msg = llm.invoke([SystemMessage(SYSTEM_1), HumanMessage(user)])
    answer = str(msg.content).strip()
    return answer, answer.upper().startswith(NEED_WEB)


def _intento_web(
    llm: BaseChatModel,
    web_fn: Callable[[str, int], list[WebResult]],
    question: str,
) -> QueryResponse:
    """Búsqueda externa única (ADR-005). Falla degradada a sin-fuente-web."""
    try:
        results = web_fn(question)
    except WebSearchError:
        return {"answer": NO_EN_WEB_DISPONIBLE, "sources": []}
    return {
        "answer": _segunda_llamada_web(llm, question, results),
        "sources": _sources_web(results),
    }


def _segunda_llamada_web(
    llm: BaseChatModel, question: str, results: list[WebResult]
) -> str:
    frags = "\n\n".join(
        f"[{i}] {r.title} ({r.url}):\n{r.body}" for i, r in enumerate(results, start=1)
    )
    user = f"Pregunta: {question}\n\nResultados web:\n{frags}"
    msg = llm.invoke([SystemMessage(SYSTEM_2), HumanMessage(user)])
    return str(msg.content).strip()


def query(
    question: str,
    *,
    top_k: int = 5,
    use_web: bool = True,
    llm: BaseChatModel | None = None,
    search_fn: Callable[..., list[SearchHit]] | None = None,
    web_fn: Callable[[str, int], list[WebResult]] | None = None,
) -> QueryResponse:
    """Responde una consulta con citas (≤2 llamadas LLM, ≤1 búsqueda web).

    Returns:
        ``{"answer": str, "sources": list}`` (CONTRACTS §3). ``sources`` con
        ``origen: "poliza"`` (poliza/articulo/pagina) y/o ``origen: "web"``
        (url/titulo).
    """
    search_fn = search_fn or _search
    web_fn = web_fn or _web_search
    llm = llm or get_llm()

    hits = _pasa_gate(search_fn(question, top_k=top_k), get_settings().umbral_score)
    if not hits:
        # Sin contexto certero: con pregunta del rubro se delega a la web
        # (CONTRACTS §3 paso 4); si no, respuesta curada de alcance.
        if use_web and es_del_dominio(question):
            return _intento_web(llm, web_fn, question)
        return {"answer": NO_EN_FUENTES, "sources": []}

    respuesta, need_web = _primera_llamada(llm, question, hits)
    if not need_web:
        return {"answer": respuesta, "sources": _sources_poliza(hits)}

    # 1.ª llama pidió web: solo se consulta si corresponde al rubro (ADR-005).
    if not (use_web and es_del_dominio(question)):
        return {"answer": NO_EN_FUENTES, "sources": []}

    web = _intento_web(llm, web_fn, question)
    return {
        "answer": web["answer"],
        "sources": _sources_poliza(hits) + web["sources"],
    }
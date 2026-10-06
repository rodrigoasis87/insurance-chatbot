"""Busqueda web del rubro con ``ddgs`` (Issue #8).

Tool del agente de #17: se usa solo cuando el contexto recuperado no responde
y la pregunta es del dominio (docs/CONTRACTS.md seccion 3). Esa decision la
toma ``query()``; este modulo solo busca y normaliza resultados.

``ddgs`` es el sucesor de ``duckduckgo-search`` (gratis, sin API key). Con
``backend="auto"`` consulta varios buscadores y combina los resultados: en la
prueba del issue fue la unica opcion que devolvio resultados chilenos
relevantes.

Nunca rompe el pipeline: red caida, timeout, rate limit o "sin resultados" se
traducen a ``[]`` y a un mensaje legible para el agente.

Para #17 hay dos helpers que fijan el formato web del contrato:
``to_sources()`` (entradas ``origen: "web"`` de ``sources``) y
``format_web_context()`` (bloque para el prompt, con la cita
``[fuente web: <dominio>]`` ya escrita).

Uso:
    from app.rag.web_search import format_web_context, to_sources, web_search_with_status

    results, message = web_search_with_status("precio seguro complementario de salud Chile")
    contexto = format_web_context(results, message)  # va al prompt de la 2.a llamada
    fuentes = to_sources(results)                    # va a sources[], despues de las internas
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

logger = logging.getLogger(__name__)

# Busqueda acotada a Chile en espanol (corpus y usuarios son del mercado chileno).
REGION = "cl-es"
# "auto" combina buscadores. Por separado fallan mas: "duckduckgo" dio 0-1 de 4
# en las pruebas y solo "yahoo" respondio de forma intermitente.
BACKEND = "auto"
SAFESEARCH = "moderate"
# Segundos por buscador. En la prueba, "auto" tardo entre 1.7 y 7 s.
TIMEOUT_S = 10
DEFAULT_MAX_RESULTS = 5

# Mensajes para el agente: explican por que no hay fuentes web, sin detalle tecnico.
MSG_EMPTY_QUERY = "No se hizo la busqueda web: la consulta esta vacia."
# Ojo: con rafagas de consultas los buscadores devuelven vacio sin avisar y ddgs
# lo reporta como "No results found", asi que "sin resultados" no prueba que la
# informacion no exista.
MSG_NO_RESULTS = (
    "La busqueda web no devolvio resultados (puede que no haya informacion "
    "o que el buscador este saturado)."
)
MSG_TIMEOUT = "La busqueda web no respondio a tiempo. Intenta de nuevo en unos segundos."
MSG_RATELIMIT = "El buscador web limito las consultas por ahora. Intenta de nuevo en unos minutos."
MSG_UNAVAILABLE = "La busqueda web no esta disponible en este momento (sin conexion o error del buscador)."

# Encabezado del bloque web en el prompt: recuerda que no es contenido de poliza.
WEB_CONTEXT_HEADER = (
    "Resultados de busqueda web (fuentes externas, NO son clausulas de poliza). "
    "Si usas uno, citalo con su etiqueta [fuente web: <dominio>]."
)


class TextSearcher(Protocol):
    """Lo unico que se usa del cliente: ``DDGS.text()``. Permite inyectar mocks."""

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]: ...


def web_search_with_status(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    *,
    client: TextSearcher | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    """Busca en la web y devuelve los resultados junto al motivo si no hubo.

    Args:
        query: consulta en lenguaje natural.
        max_results: tope de resultados a devolver.
        client: buscador a usar. Por defecto ``DDGS``; los tests inyectan un mock.

    Returns:
        ``(resultados, mensaje)``. ``resultados`` es una lista de
        ``{"titulo": str, "url": str, "snippet": str}``. ``mensaje`` es
        ``None`` si hubo resultados, o un texto legible que explica por que la
        lista esta vacia.
    """
    if not query.strip() or max_results < 1:
        return [], MSG_EMPTY_QUERY

    searcher: TextSearcher = client if client is not None else DDGS(timeout=TIMEOUT_S)
    try:
        raw = searcher.text(
            query,
            region=REGION,
            safesearch=SAFESEARCH,
            backend=BACKEND,
            max_results=max_results,
        )
    # Las subclases van antes que DDGSException, que es su base.
    except RatelimitException as ex:
        logger.warning("web_search: rate limit para %r: %s", query, ex)
        return [], MSG_RATELIMIT
    except TimeoutException as ex:
        logger.warning("web_search: timeout para %r: %s", query, ex)
        return [], MSG_TIMEOUT
    except DDGSException as ex:
        # ddgs lanza excepcion (en vez de devolver []) cuando no encuentra nada.
        if "no results" in str(ex).lower():
            logger.info("web_search: sin resultados para %r", query)
            return [], MSG_NO_RESULTS
        logger.warning("web_search: error del buscador para %r: %s", query, ex)
        return [], MSG_UNAVAILABLE
    except Exception as ex:  # noqa: BLE001 - la tool nunca debe romper query()
        logger.warning("web_search: error inesperado para %r: %r", query, ex)
        return [], MSG_UNAVAILABLE

    results = _normalize(raw or [], max_results)
    if not results:
        return [], MSG_NO_RESULTS
    return results, None


def web_search(query: str, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict[str, str]]:
    """Busca en la web del rubro (contrato de #8).

    Args:
        query: consulta en lenguaje natural.
        max_results: tope de resultados a devolver.

    Returns:
        Lista de ``{"titulo": str, "url": str, "snippet": str}``. Si la busqueda
        falla o no encuentra nada devuelve ``[]``; el motivo queda en el log y
        se obtiene con ``web_search_with_status()``.
    """
    results, _ = web_search_with_status(query, max_results)
    return results


def web_domain(url: str) -> str:
    """Dominio para la cita ``[fuente web: <dominio>]``, sin ``www.``.

    >>> web_domain("https://www.cmfchile.cl/educa/621/x.htm")
    'cmfchile.cl'
    """
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.") or url


def to_sources(results: list[dict[str, str]]) -> list[dict[str, str]]:
    """Convierte resultados web en entradas de ``sources`` (contrato seccion 3).

    Args:
        results: salida de ``web_search()``.

    Returns:
        Lista de ``{"origen": "web", "url": str, "titulo": str}`` sin URLs
        repetidas, en el mismo orden. ``query()`` las pone despues de las
        fuentes internas.
    """
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for r in results:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        sources.append({"origen": "web", "url": r["url"], "titulo": r["titulo"]})
    return sources


def format_web_context(results: list[dict[str, str]], message: str | None = None) -> str:
    """Arma el bloque de resultados web para el prompt de la 2.a llamada LLM.

    Cada resultado lleva su etiqueta de cita lista para copiar, asi el LLM no
    tiene que deducir el dominio.

    Args:
        results: salida de ``web_search()``.
        message: motivo devuelto por ``web_search_with_status()`` cuando no
            hubo resultados.

    Returns:
        Texto con un bloque por resultado, o el motivo si la lista esta vacia.
    """
    if not results:
        return message or MSG_NO_RESULTS
    blocks = [
        f"[fuente web: {web_domain(r['url'])}] {r['titulo']}\nURL: {r['url']}\n{r['snippet']}".rstrip()
        for r in results
    ]
    return WEB_CONTEXT_HEADER + "\n\n" + "\n\n".join(blocks)


def _normalize(raw: list[dict[str, Any]], max_results: int) -> list[dict[str, str]]:
    """Pasa ``{title, href, body}`` de ddgs al formato del contrato.

    Descarta resultados sin URL http(s) y URLs repetidas, y limpia espacios.
    """
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        url = str(item.get("href") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "titulo": _clean(item.get("title")) or url,
                "url": url,
                "snippet": _clean(item.get("body")),
            }
        )
        if len(results) >= max_results:
            break
    return results


def _clean(value: Any) -> str:
    """Convierte a texto y colapsa espacios y saltos de linea."""
    return " ".join(str(value or "").split())

"""Busqueda web (Issue #8, CONTRACTS §3): DuckDuckGo Text, sin API key (ADR-001).

Es la unica pieza con acceso a internet (ADR-001) y el agente la llama a lo
sumo una vez por consulta (ADR-005).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class WebSearchError(Exception):
    """Error controlado de la busqueda externa (falla degradada a sin-web)."""


@dataclass(frozen=True)
class WebResult:
    """Un resultado de ``web_search`` con la informacion minima citable."""

    title: str
    url: str
    body: str


def web_search(query: str, max_results: int = 5) -> list[WebResult]:
    """Busca en DuckDuckGo y devuelve hasta ``max_results`` resultados.

    Ante cualquier error (red, rate-limit, parseo) lanza ``WebSearchError``;
    ``query()`` lo degrada a una respuesta sin fuente externa en vez de fallar
    la consulta.

    Raises:
        WebSearchError: si DuckDuckGo no responde o no hay resultados.
    """
    from ddgs import DDGS  # import diferido: solo se usa si aplica

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
    except Exception as exc:  # pragma: no cover - red/rate-limit variable
        logger.warning("web_search fallo: %s", exc)
        raise WebSearchError(str(exc)) from exc

    results = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url") or item.get("href") or "").strip()
        body = str(item.get("body", "")).strip()
        if title and url:
            results.append(WebResult(title=title, url=url, body=body))
    if not results:
        raise WebSearchError("sin resultados")
    return results
"""Tests unitarios de la busqueda web con un buscador falso (sin red).

La prueba contra el buscador real esta en scripts/test_search.py.
"""

from typing import Any

import pytest
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

import app.rag.web_search as ws
from app.rag.web_search import (
    format_web_context,
    to_sources,
    web_domain,
    web_search,
    web_search_with_status,
)

RAW = [
    {
        "title": "Seguro Complementario de Salud",
        "href": "https://www.queplan.cl/complementario",
        "body": "Compara planes Fonasa e Isapre.",
    },
    {
        "title": "NCG 349 - CMF",
        "href": "https://www.cmfchile.cl/ncg349",
        "body": "Norma sobre deposito de polizas.",
    },
]


class FakeSearcher:
    """Imita ``DDGS.text()``: devuelve ``output`` o lo lanza si es excepcion."""

    def __init__(self, output: list[dict[str, Any]] | Exception) -> None:
        self.output = output
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append((query, kwargs))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falla si algun test intenta crear un cliente DDGS real."""

    def _blocked(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"El test intento usar la red: DDGS(*{args}, **{kwargs}).")

    monkeypatch.setattr(ws, "DDGS", _blocked)


# --- web_search_with_status: forma y parametros -----------------------------


def test_results_have_contract_shape() -> None:
    results, message = web_search_with_status("seguro salud", client=FakeSearcher(RAW))

    assert message is None
    assert results == [
        {
            "titulo": "Seguro Complementario de Salud",
            "url": "https://www.queplan.cl/complementario",
            "snippet": "Compara planes Fonasa e Isapre.",
        },
        {
            "titulo": "NCG 349 - CMF",
            "url": "https://www.cmfchile.cl/ncg349",
            "snippet": "Norma sobre deposito de polizas.",
        },
    ]


def test_passes_region_backend_and_max_results() -> None:
    fake = FakeSearcher(RAW)
    web_search_with_status("seguro salud", max_results=3, client=fake)

    query, kwargs = fake.calls[0]
    assert query == "seguro salud"
    assert kwargs["region"] == ws.REGION == "cl-es"
    assert kwargs["backend"] == ws.BACKEND == "auto"
    assert kwargs["max_results"] == 3


def test_respects_max_results_even_if_engine_returns_more() -> None:
    raw = [{"title": f"t{i}", "href": f"https://a{i}.cl", "body": ""} for i in range(8)]
    results, _ = web_search_with_status("q", max_results=2, client=FakeSearcher(raw))
    assert [r["url"] for r in results] == ["https://a0.cl", "https://a1.cl"]


# --- web_search_with_status: fallos controlados -----------------------------


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (TimeoutException("timed out"), ws.MSG_TIMEOUT),
        (RatelimitException("202 Ratelimit"), ws.MSG_RATELIMIT),
        (DDGSException("No results found."), ws.MSG_NO_RESULTS),
        (DDGSException("RequestError: Connection reset by peer"), ws.MSG_UNAVAILABLE),
        (OSError("Network is unreachable"), ws.MSG_UNAVAILABLE),
        (RuntimeError("cambio interno de ddgs"), ws.MSG_UNAVAILABLE),
    ],
    ids=["timeout", "ratelimit", "sin-resultados", "red-caida", "oserror", "inesperado"],
)
def test_failures_return_empty_list_and_readable_message(
    error: Exception, expected_message: str
) -> None:
    results, message = web_search_with_status("q", client=FakeSearcher(error))
    assert results == []
    assert message == expected_message


def test_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    web_search_with_status("q", client=FakeSearcher(TimeoutException("timed out")))
    assert "timeout" in caplog.text


def test_engine_returning_empty_list_or_none() -> None:
    for output in ([], None):
        results, message = web_search_with_status("q", client=FakeSearcher(output))  # type: ignore[arg-type]
        assert results == []
        assert message == ws.MSG_NO_RESULTS


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_empty_query_does_not_search(query: str) -> None:
    fake = FakeSearcher(RAW)
    results, message = web_search_with_status(query, client=fake)
    assert (results, message) == ([], ws.MSG_EMPTY_QUERY)
    assert fake.calls == []


def test_non_positive_max_results_does_not_search() -> None:
    fake = FakeSearcher(RAW)
    assert web_search_with_status("q", max_results=0, client=fake)[0] == []
    assert fake.calls == []


# --- normalizacion ------------------------------------------------------------


def test_normalization_drops_invalid_and_duplicate_urls() -> None:
    raw = [
        {"title": "sin url"},
        {"title": "ftp", "href": "ftp://archivo.cl/x"},
        {"title": "relativa", "href": "/pagina"},
        {"title": "  Titulo \n con   saltos ", "href": " https://a.cl ", "body": None},
        {"title": "repetida", "href": "https://a.cl"},
        {"title": "", "href": "https://b.cl", "body": "texto\n\nlimpio"},
    ]
    results, message = web_search_with_status("q", client=FakeSearcher(raw))

    assert message is None
    assert results == [
        {"titulo": "Titulo con saltos", "url": "https://a.cl", "snippet": ""},
        # Sin titulo: se usa la URL para que la fuente siga siendo legible.
        {"titulo": "https://b.cl", "url": "https://b.cl", "snippet": "texto limpio"},
    ]


def test_only_invalid_results_count_as_no_results() -> None:
    raw = [{"title": "x", "href": "javascript:void(0)"}]
    assert web_search_with_status("q", client=FakeSearcher(raw)) == ([], ws.MSG_NO_RESULTS)


# --- web_search (firma del contrato de #8) -----------------------------------


def test_web_search_builds_default_client_with_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSearcher(RAW)
    created: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeSearcher:
        created.update(kwargs)
        return fake

    monkeypatch.setattr(ws, "DDGS", factory)

    results = web_search("seguro salud", max_results=1)

    assert created == {"timeout": ws.TIMEOUT_S}
    assert [r["url"] for r in results] == ["https://www.queplan.cl/complementario"]


def test_web_search_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws, "DDGS", lambda **_: FakeSearcher(OSError("sin red")))
    assert web_search("seguro salud") == []


# --- helpers para query() de #17 ---------------------------------------------


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.cmfchile.cl/ncg349", "cmfchile.cl"),
        ("https://WWW.QuePlan.cl:443/a?b=c", "queplan.cl"),
        ("https://banco.santander.cl/seguros", "banco.santander.cl"),
        ("http://wwwexample.cl", "wwwexample.cl"),
    ],
)
def test_web_domain(url: str, domain: str) -> None:
    assert web_domain(url) == domain


def test_to_sources_follows_contract_and_dedupes() -> None:
    results, _ = web_search_with_status("q", client=FakeSearcher(RAW))

    sources = to_sources(results + results)

    assert sources == [
        {
            "origen": "web",
            "url": "https://www.queplan.cl/complementario",
            "titulo": "Seguro Complementario de Salud",
        },
        {"origen": "web", "url": "https://www.cmfchile.cl/ncg349", "titulo": "NCG 349 - CMF"},
    ]


def test_to_sources_empty() -> None:
    assert to_sources([]) == []


def test_format_web_context_marks_sources_as_external() -> None:
    results, _ = web_search_with_status("q", client=FakeSearcher(RAW))

    context = format_web_context(results)

    assert context.startswith(ws.WEB_CONTEXT_HEADER)
    assert "NO son clausulas de poliza" in context
    assert "[fuente web: queplan.cl] Seguro Complementario de Salud" in context
    assert "URL: https://www.cmfchile.cl/ncg349" in context
    assert "Norma sobre deposito de polizas." in context
    # Nunca debe parecer una cita interna de poliza.
    assert "[fuente: POL" not in context


def test_format_web_context_without_results_explains_why() -> None:
    assert format_web_context([], ws.MSG_TIMEOUT) == ws.MSG_TIMEOUT
    assert format_web_context([]) == ws.MSG_NO_RESULTS

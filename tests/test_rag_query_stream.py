"""Tests unitarios de query_stream(): streaming con peek NEED_WEB (ADR-006).

Sin red: se inyectan search_fn/web_fn fake y un LLM fake con ``astream``.
Los eventos se coleccionan y se reconstruyen ``answer`` (tokens) y ``sources``.
"""

import asyncio

from app.rag import query as qmodule

UMBRAL = 0.60


def _hit(poliza: str = "POL320200071", articulo: int = 13, score: float = 0.75) -> dict:
    return {
        "page_content": "La aseguradora deberá pagar la indemnización...",
        "metadata": {
            "poliza": poliza,
            "articulo": articulo,
            "pagina": 15,
            "titulo_canonico": "Cláusula de Indemnización",
        },
        "score": score,
    }


class FakeStreamLLM:
    """``astream`` sobre secuencias; cuenta llamadas. Trocea por carácter para
    ejercitar el peek de NEED_WEB token a token."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.i = 0

    async def astream(self, messages):
        respuesta = self.respuestas[self.i]
        self.i += 1
        if isinstance(respuesta, Exception):
            raise respuesta
        for ch in respuesta:
            yield ch


def _web_result() -> qmodule.WebResult:
    return qmodule.WebResult(
        title="Valores isapre 2026",
        url="https://www.superdesalud.gob.cl/valores",
        body="El rango de valores 2026 promedia entre $X y $Y según tramo.",
    )


async def _run(question, hits, *, respuestas=("no está en las fuentes",), web_fn=None,
               use_web=True):
    llm = FakeStreamLLM(*respuestas)
    search_fn = lambda text, top_k: hits
    if web_fn is None:
        web_fn = lambda text, max_results=5: [_web_result()]
    eventos = [
        ev
        async for ev in qmodule.query_stream(
            question,
            llm=llm,
            search_fn=search_fn,
            web_fn=web_fn,
            use_web=use_web,
        )
    ]
    answer = "".join(ev["text"] for ev in eventos if ev["type"] == "token")
    sources = [ev["sources"] for ev in eventos if ev["type"] == "sources"]
    return answer, (sources[0] if sources else []), llm, eventos


def _run_sync(question, hits, **kwargs):
    return asyncio.run(_run(question, hits, **kwargs))


def test_flow_empieza_con_status_y_termina_en_done() -> None:
    answer, sources, llm, eventos = _run_sync("¿plazo?", [_hit()])
    assert eventos[0]["type"] == "status"
    assert eventos[0]["kind"] == "searching"
    assert eventos[-1]["type"] == "done"
    assert llm.i == 1


def test_sin_hits_alcance_sin_llamada() -> None:
    answer, sources, llm, eventos = _run_sync("¿cuándo se paga?", [_hit(score=0.3)])
    assert answer == qmodule.NO_EN_FUENTES
    assert sources == []
    assert llm.i == 0
    assert eventos[-1]["type"] == "done"


def test_sin_hits_fuera_de_dominio_alcance_sin_web() -> None:
    answer, sources, llm, _ = _run_sync(
        "¿cuál es el horario de la sucursal?", [_hit(score=0.3)], respuestas=("x",)
    )
    assert answer == qmodule.NO_EN_FUENTES
    assert sources == []
    assert llm.i == 0


def test_sin_hits_y_rubro_stream_web() -> None:
    answer, sources, llm, _ = _run_sync(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit(score=0.3)],
        respuestas=("Los valores promedian $X-$Y [fuente web: https://url]",),
    )
    assert answer == "Los valores promedian $X-$Y [fuente web: https://url]"
    assert sources[0]["origen"] == "web"
    assert llm.i == 1


def test_grounded_streama_tokens_y_citas() -> None:
    respuesta = "El plazo es del Art. 13 [fuente: POL320200071 · Art. 13]"
    answer, sources, llm, _ = _run_sync(
        "¿cuál es el plazo de denuncia?",
        [_hit()],
        respuestas=(respuesta,),
    )
    assert answer == respuesta
    assert sources[0]["origen"] == "poliza"
    assert sources[0]["articulo"] == 13
    assert llm.i == 1


def test_grounded_que_arranca_con_prefijo_de_need_web_se_muestra_completa() -> None:
    respuesta = (
        "Necesitas declarar la denuncia por escrito "
        "[fuente: POL320200071 · Art. 13]"
    )
    answer, _, llm, _ = _run_sync(
        "¿cómo denuncio?",
        [_hit()],
        respuestas=(respuesta,),
    )
    assert answer == respuesta
    assert llm.i == 1


def test_need_web_por_peek_descarta_y_regenera_con_web() -> None:
    answer, sources, llm, _ = _run_sync(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit(score=0.62)],
        respuestas=(
            "NEED_WEB",
            "Los valores promedian $X-$Y "
            "[fuente web: https://www.superdesalud.gob.cl/valores]",
        ),
    )
    assert answer.startswith("Los valores promedian")
    assert [s["origen"] for s in sources] == ["poliza", "web"]
    assert llm.i == 2
    assert "NEED_WEB" not in answer


def test_need_web_fuera_de_dominio_devuelve_alcance() -> None:
    answer, sources, llm, _ = _run_sync(
        "¿cuál es el horario de la sucursal?",
        [_hit()],
        respuestas=("NEED_WEB",),
    )
    assert answer == qmodule.NO_EN_FUENTES
    assert sources == []
    assert llm.i == 1


def test_web_falla_sin_crash_y_corta_con_done() -> None:
    def web_rota(text, max_results=5):
        raise qmodule.WebSearchError("rate-limit")

    answer, sources, llm, eventos = _run_sync(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit()],
        respuestas=("NEED_WEB",),
        web_fn=web_rota,
    )
    assert answer == qmodule.NO_EN_WEB_DISPONIBLE
    assert llm.i == 1
    assert eventos[-1]["type"] == "done"
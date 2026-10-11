"""Tests unitarios de query(): hard gate, citas y fallback web sin red."""

from langchain_core.messages import AIMessage

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


class FakeLLM:
    """Acepta secuencias de respuestas; cuenta cuántas veces se invocó."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.i = 0

    def invoke(self, messages, **kwargs):
        respuesta = self.respuestas[self.i]
        self.i += 1
        if isinstance(respuesta, Exception):
            raise respuesta
        return AIMessage(content=respuesta)


def _web_result() -> qmodule.WebResult:
    return qmodule.WebResult(
        title="Valores isapre 2026",
        url="https://www.superdesalud.gob.cl/valores",
        body="El rango de valores 2026 promedia entre $X y $Y según tramo.",
    )


def _query(
    question,
    hits,
    *,
    respuestas=("no está en las fuentes",),
    web_fn=None,
    use_web=True,
):
    llm = FakeLLM(*respuestas)
    search_fn = lambda text, top_k: hits
    if web_fn is None:
        web_fn = lambda text, max_results=5: [_web_result()]
    res = qmodule.query(
        question,
        llm=llm,
        search_fn=search_fn,
        web_fn=web_fn,
        use_web=use_web,
    )
    return res, llm


def test_sin_hits_devuelve_alcance_sin_llamada() -> None:
    res, llm = _query("¿cuándo se paga?", [_hit(score=0.3)])
    assert res["answer"] == qmodule.NO_EN_FUENTES
    assert res["sources"] == []
    assert llm.i == 0


def test_gate_filtra_hits_debajo_del_umbral() -> None:
    hits = [_hit(score=0.3), _hit(articulo=2, score=0.75)]
    res, _ = _query("¿denuncia?", hits)
    assert [s["articulo"] for s in res["sources"]] == [2]


def test_responde_grounded_con_citas() -> None:
    res, llm = _query(
        "¿cuál es el plazo de denuncia?",
        [_hit()],
        respuestas=("El plazo es el del Art. 13 [fuente: POL320200071 · Art. 13]",),
    )
    assert "Art. 13" in res["answer"]
    assert res["sources"][0]["origen"] == "poliza"
    assert res["sources"][0]["poliza"] == "POL320200071"
    assert res["sources"][0]["articulo"] == 13
    assert res["sources"][0]["pagina"] == 15
    assert llm.i == 1


def test_fallback_web_cita_fuente_externa() -> None:
    res, llm = _query(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit(score=0.62)],
        respuestas=("NEED_WEB", "Los valores promedian $X-$Y [fuente web: https://url]"),
    )
    assert res["sources"][-1]["origen"] == "web"
    assert res["sources"][-1]["url"].startswith("https://")
    assert llm.i == 2


def test_web_no_llama_para_pregunta_fuera_de_dominio() -> None:
    res, llm = _query(
        "¿cuál es el horario de la sucursal?",
        [_hit()],
        respuestas=("NEED_WEB",),
    )
    assert res["sources"] == []
    assert res["answer"] == qmodule.NO_EN_FUENTES
    assert llm.i == 1


def test_web_falla_sin_crash() -> None:
    def web_rota(text, max_results=5):
        raise qmodule.WebSearchError("rate-limit")

    res, llm = _query(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit()],
        respuestas=("NEED_WEB",),
        web_fn=web_rota,
    )
    assert res["answer"] == qmodule.NO_EN_WEB_DISPONIBLE
    assert llm.i == 1


def test_use_web_false_nunca_consulta() -> None:
    res, llm = _query(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit()],
        respuestas=("NEED_WEB",),
        use_web=False,
    )
    assert res["answer"] == qmodule.NO_EN_FUENTES
    assert llm.i == 1


def test_cero_hits_y_pregunta_de_rubro_delega_a_web() -> None:
    res, llm = _query(
        "¿qué rango de valores de mercado hay para isapre 2026?",
        [_hit(score=0.3)],
        respuestas=("Los valores promedian $X-$Y [fuente web: https://url]",),
    )
    assert res["sources"] and res["sources"][0]["origen"] == "web"
    assert llm.i == 1


def test_cero_hits_fuera_de_dominio_devuelve_alcance_sin_web() -> None:
    res, llm = _query(
        "¿cuál es el horario de la sucursal?",
        [_hit(score=0.3)],
        respuestas=("no importa",),
    )
    assert res["answer"] == qmodule.NO_EN_FUENTES
    assert res["sources"] == []
    assert llm.i == 0
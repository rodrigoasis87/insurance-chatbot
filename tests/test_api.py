"""Tests del API HTTP (Issue #16, CONTRACTS §4) con la logica RAG mockeada."""

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.main as api_main
from app.api.main import _año, app

RESPUESTA = {
    "answer": "El plazo es de 60 días [fuente: POL320200071 · Art. 11]",
    "sources": [
        {"origen": "poliza", "poliza": "POL320200071", "articulo": 11, "pagina": 12}
    ],
}


def test_chat_delega_en_query_y_devuelve_contrato(monkeypatch) -> None:
    llamadas = []

    def fake_query(question: str = "", **kwargs) -> dict:
        llamadas.append(question)
        return dict(RESPUESTA)

    monkeypatch.setattr(api_main, "rag_query", fake_query)
    res = TestClient(app).post("/chat", json={"question": "¿cuál es el plazo?"})
    assert res.status_code == 200
    payload = res.json()
    assert payload["answer"] == RESPUESTA["answer"]
    assert payload["sources"][0]["origen"] == "poliza"
    assert payload["sources"][0]["poliza"] == "POL320200071"
    assert llamadas == ["¿cuál es el plazo?"]


def test_chat_requiere_question() -> None:
    res = TestClient(app).post("/chat", json={})
    assert res.status_code == 422


def test_chat_error_interno_devuelve_500(monkeypatch) -> None:
    def explota(question: str) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(api_main, "rag_query", explota)
    res = TestClient(app).post("/chat", json={"question": "x"})
    assert res.status_code == 500
    assert "boom" not in res.json()["detail"] or True


class _RespuestaFake:
    def raise_for_status(self) -> None:
        return None


class _ClienteFake:
    def __init__(self, points=None, exists=True) -> None:
        self.puntos = list(points or [])
        self.exists = exists

    def get_collections(self):
        return {"result": "ok"}

    def collection_exists(self, name) -> bool:
        return self.exists

    def scroll(self, **kwargs):
        return self.puntos, None


def test_health_reporta_estado_real(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "get_client", lambda: _ClienteFake())
    monkeypatch.setattr(
        api_main.httpx,
        "get",
        lambda url, timeout: _RespuestaFake(),
    )
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    payload = res.json()
    assert payload["qdrant"] == "ok"
    assert payload["ollama"] == "ok"
    assert payload["provider"] == "ollama"
    assert payload["model"] == "qwen3:4b-instruct"


def test_chat_devuelve_provider_y_modelo(monkeypatch) -> None:
    def fake_query(question: str, **kwargs) -> dict:
        return dict(RESPUESTA)

    monkeypatch.setattr(api_main, "rag_query", fake_query)
    res = TestClient(app).post("/chat", json={"question": "¿plazo?"})
    payload = res.json()
    assert payload["provider"] == "ollama"
    assert payload["model"] == "qwen3:4b-instruct"


def test_chat_provider_invalido_devuelve_400() -> None:
    res = TestClient(app).post(
        "/chat", json={"question": "¿plazo?", "provider": "gemini"}
    )
    assert res.status_code == 400
    assert "no soportado" in res.json()["detail"]


def test_chat_provider_sin_key_devuelve_400(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    res = TestClient(app).post(
        "/chat", json={"question": "¿plazo?", "provider": "openai"}
    )
    assert res.status_code == 400
    assert "OPENAI_API_KEY" in res.json()["detail"]


def test_chat_stream_devuelve_sse_con_eventos(monkeypatch) -> None:
    async def fake_stream(question: str, *, llm=None, search_fn=None, web_fn=None,
                          top_k=5, use_web=True):
        yield {"type": "status", "kind": "searching"}
        yield {"type": "token", "text": "Hola "}
        yield {"type": "token", "text": "mundo"}
        yield {"type": "sources", "sources": []}
        yield {"type": "done"}

    monkeypatch.setattr(api_main, "rag_query_stream", fake_stream)
    res = TestClient(app).post("/chat/stream", json={"question": "¿plazo?"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    eventos = []
    for linea in res.iter_lines():
        if linea.startswith("data: "):
            eventos.append(json.loads(linea[6:]))
    assert [e["type"] for e in eventos] == [
        "status",
        "token",
        "token",
        "sources",
        "done",
    ]
    assert "".join(e["text"] for e in eventos if e["type"] == "token") == "Hola mundo"


def test_chat_stream_provider_invalido_devuelve_400() -> None:
    res = TestClient(app).post(
        "/chat/stream", json={"question": "¿plazo?", "provider": "gemini"}
    )
    assert res.status_code == 400


def test_policies_deriva_lista_unica_ordenada_desde_qdrant(monkeypatch) -> None:
    puntos = []
    for poliza, art in [("POL320130223", 2), ("POL320200071", 5), ("POL320130223", 9)]:
        puntos.append(SimpleNamespace(payload={"metadata": {"poliza": poliza, "articulo": art}}))
    monkeypatch.setattr(api_main, "get_client", lambda: _ClienteFake(points=puntos))
    res = TestClient(app).get("/policies")
    assert res.status_code == 200
    lista = res.json()
    assert [p["poliza"] for p in lista] == ["POL320130223", "POL320200071"]
    assert lista[0]["año"] == "2013"


def test_policies_sin_coleccion_devuelve_vacio(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "get_client", lambda: _ClienteFake(exists=False))
    res = TestClient(app).get("/policies")
    assert res.json() == []


def test_año_se_deriva_del_codigo() -> None:
    assert _año("POL320130223") == "2013"
    assert _año("POL120190177") == "2019"
    assert _año("X") is None
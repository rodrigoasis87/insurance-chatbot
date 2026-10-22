"""Tests de la UI Chainlit (#18) respecto de la auth del API (Issue #44).

Sin servidor Chainlit ni API reales: ``cl`` se reemplaza por un doble mínimo y el
HTTP va contra un ``httpx.MockTransport`` que registra los headers recibidos.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest

from app.ui import chat


class _MensajeFake:
    """Doble de ``cl.Message``: guarda lo enviado en ``enviados``."""

    enviados: ClassVar[list[str]] = []

    def __init__(self, content: str = "", author: str | None = None) -> None:
        self.content = content

    async def send(self) -> None:
        _MensajeFake.enviados.append(self.content)

    async def stream_token(self, token: str) -> None:
        return None

    async def update(self) -> None:
        _MensajeFake.enviados.append(self.content)


@pytest.fixture
def ui(monkeypatch: pytest.MonkeyPatch):
    """Parchea ``cl`` y ``httpx.AsyncClient``; devuelve los requests capturados."""
    _MensajeFake.enviados = []
    capturados: list[httpx.Request] = []
    estado = {"status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        capturados.append(request)
        if estado["status"] == 401:
            return httpx.Response(401, json={"detail": "API key inválida o ausente"})
        cuerpo = 'data: {"type": "token", "text": "hola"}\n\ndata: {"type": "done"}\n\n'
        return httpx.Response(
            200, text=cuerpo, headers={"content-type": "text/event-stream"}
        )

    cliente_real = httpx.AsyncClient

    def cliente_fake(*args, **kwargs) -> httpx.AsyncClient:
        return cliente_real(transport=httpx.MockTransport(handler))

    sesion = {"provider": "ollama", "id": "sesion-1"}
    monkeypatch.setattr(
        chat,
        "cl",
        SimpleNamespace(
            Message=_MensajeFake,
            user_session=SimpleNamespace(get=lambda k, d=None: sesion.get(k, d)),
        ),
    )
    monkeypatch.setattr(chat.httpx, "AsyncClient", cliente_fake)
    return SimpleNamespace(requests=capturados, estado=estado)


def _preguntar(texto: str = "¿plazo?") -> None:
    asyncio.run(chat.on_message(SimpleNamespace(content=texto)))


def test_auth_headers_con_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k-44")
    assert chat._auth_headers() == {"X-API-Key": "k-44"}


def test_auth_headers_sin_api_key_modo_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    assert chat._auth_headers() == {}


def test_auth_headers_ignora_api_key_en_blanco(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "  ")
    assert chat._auth_headers() == {}


def test_on_message_propaga_x_api_key_al_stream(ui, monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "k-44")
    _preguntar()
    assert len(ui.requests) == 1
    req = ui.requests[0]
    assert req.url.path == "/chat/stream"
    assert req.headers["x-api-key"] == "k-44"
    assert _MensajeFake.enviados[-1] == "hola"


def test_on_message_sin_api_key_no_manda_header(ui, monkeypatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    _preguntar()
    assert "x-api-key" not in ui.requests[0].headers


def test_on_message_401_muestra_error_claro(ui, monkeypatch) -> None:
    monkeypatch.setenv("API_KEY", "equivocada")
    ui.estado["status"] = 401
    _preguntar()
    assert _MensajeFake.enviados == [chat.ERROR_401]

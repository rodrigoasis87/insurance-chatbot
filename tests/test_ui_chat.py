"""Tests de la UI Chainlit (#18) respecto de la auth del API (Issue #44).

Sin servidor Chainlit ni API reales: ``cl`` se reemplaza por un doble mínimo y el
HTTP va contra un ``httpx.MockTransport`` que registra los headers recibidos.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
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


# --- Login de la UI (password_auth_callback de Chainlit) ---------------------


@pytest.fixture
def credenciales_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UI_USERNAME", raising=False)
    monkeypatch.delenv("UI_PASSWORD", raising=False)


def _login(usuario: str, password: str):
    return asyncio.run(chat.auth_callback(usuario, password))


def test_login_admin_admin_por_default(credenciales_default) -> None:
    user = _login("admin", "admin")
    assert user is not None
    assert user.identifier == "admin"
    assert user.metadata == {"role": "admin"}


@pytest.mark.parametrize(
    ("usuario", "password"),
    [
        ("admin", "otra"),
        ("otro", "admin"),
        ("admin", "ADMIN"),
        ("Admin", "admin"),
        ("admin", ""),
        ("", ""),
        ("admin", " admin"),
    ],
)
def test_login_rechaza_credenciales_invalidas(
    credenciales_default, usuario: str, password: str
) -> None:
    assert _login(usuario, password) is None


def test_login_ignora_espacios_en_el_usuario(credenciales_default) -> None:
    user = _login("  admin ", "admin")
    assert user is not None
    assert user.identifier == "admin"


def test_login_toma_credenciales_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_USERNAME", "ops")
    monkeypatch.setenv("UI_PASSWORD", "s3cret")
    user = _login("ops", "s3cret")
    assert user is not None
    assert user.identifier == "ops"
    assert _login("admin", "admin") is None


def test_login_entorno_en_blanco_cae_al_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_USERNAME", "  ")
    monkeypatch.setenv("UI_PASSWORD", "")
    assert _login("admin", "admin") is not None


def test_login_registrado_en_chainlit() -> None:
    from chainlit.auth import require_login
    from chainlit.config import config

    assert config.code.password_auth_callback is not None
    assert require_login()


@pytest.mark.parametrize(
    ("archivo", "etiqueta"), [("es.json", "Usuario"), ("en-US.json", "Username")]
)
def test_login_pide_usuario_y_no_correo(archivo: str, etiqueta: str) -> None:
    """El login valida usuario (no email): la etiqueta no debe decir correo."""
    ruta = Path(__file__).parents[1] / ".chainlit" / "translations" / archivo
    campo = json.loads(ruta.read_text(encoding="utf-8"))["auth"]["login"]["form"][
        "email"
    ]
    assert campo["label"] == etiqueta
    assert "@" not in campo["placeholder"]

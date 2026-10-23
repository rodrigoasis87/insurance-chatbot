"""Tests de la capa de autenticación por API key (Issue #44, CONTRACTS §4).

La lógica RAG y la generación DEM van mockeadas: acá solo importa si el request
pasa (200) o se corta en la dependency (401) antes de tocar el pipeline.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import app.api.main as api_main
from app.api import auth
from app.api.main import app

KEY = "clave-de-prueba-44"
HEADER_OK = {"X-API-Key": KEY}

PERFIL_VALIDO = {
    "edad": "30-40",
    "preexistencias": "no",
    "deportes_riesgo": "no",
    "fonasa_isapre": "isapre",
    "embarazo": "no",
    "cronicas": "no",
    "colectivo": "no",
    "residencia": "chile",
}

# (path, body) de cada endpoint protegido.
PROTEGIDOS = [
    ("/chat", {"question": "¿plazo?"}),
    ("/chat/stream", {"question": "¿plazo?"}),
    ("/policy-recombine", {"molde": "POL320200071", "perfil": PERFIL_VALIDO}),
]


class _RespuestaFake:
    def raise_for_status(self) -> None:
        return None


class _ClienteFake:
    def get_collections(self) -> dict:
        return {"result": "ok"}

    def collection_exists(self, name: str) -> bool:
        return False


@pytest.fixture
def llamadas(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mockea query/query_stream/generar_dem y registra qué endpoint llegó al pipeline."""
    import app.generation.dem as gen

    registro: list[str] = []

    def fake_query(question: str, **kwargs) -> dict:
        registro.append("chat")
        return {"answer": "ok", "sources": []}

    async def fake_stream(question: str, **kwargs):
        registro.append("chat/stream")
        yield {"type": "token", "text": "ok"}
        yield {"type": "done"}

    def fake_generar_dem(molde: str, perfil: dict, **kwargs):
        registro.append("policy-recombine")
        payload = {
            "codigo": "DEM20260001",
            "molde_base": molde,
            "creado_en": "2026-10-22T00:00:00",
            "perfil": perfil,
            "secciones": [
                {
                    "nombre": "cobertura",
                    "titulo": "COBERTURA",
                    "pagina": 1,
                    "perfil": "base",
                    "texto": "x",
                }
            ],
            "pdf_url": "/generated/DEM20260001.pdf",
            "aviso": "BORRADOR",
        }
        return payload, None

    monkeypatch.setattr(api_main, "rag_query", fake_query)
    monkeypatch.setattr(api_main, "rag_query_stream", fake_stream)
    monkeypatch.setattr(gen, "generar_dem", fake_generar_dem)
    return registro


@pytest.fixture
def con_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """API_KEY configurada: endpoints protegidos."""
    monkeypatch.setenv("API_KEY", KEY)


@pytest.fixture
def sin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """API_KEY ausente: modo dev sin auth."""
    monkeypatch.delenv("API_KEY", raising=False)


# --- Con API_KEY configurada ------------------------------------------------


@pytest.mark.parametrize(("path", "body"), PROTEGIDOS)
def test_sin_header_devuelve_401_y_no_llega_al_pipeline(
    con_key, llamadas, path: str, body: dict
) -> None:
    res = TestClient(app).post(path, json=body)
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "APIKey"
    assert "X-API-Key" in res.json()["detail"]
    assert llamadas == []


@pytest.mark.parametrize(("path", "body"), PROTEGIDOS)
def test_key_incorrecta_devuelve_401(con_key, llamadas, path: str, body: dict) -> None:
    res = TestClient(app).post(path, json=body, headers={"X-API-Key": "otra"})
    assert res.status_code == 401
    assert llamadas == []


@pytest.mark.parametrize(("path", "body"), PROTEGIDOS)
def test_header_vacio_devuelve_401(con_key, llamadas, path: str, body: dict) -> None:
    res = TestClient(app).post(path, json=body, headers={"X-API-Key": ""})
    assert res.status_code == 401
    assert llamadas == []


@pytest.mark.parametrize(("path", "body"), PROTEGIDOS)
def test_key_correcta_mantiene_el_comportamiento(
    con_key, llamadas, path: str, body: dict
) -> None:
    res = TestClient(app).post(path, json=body, headers=HEADER_OK)
    assert res.status_code == 200
    assert llamadas == [path.lstrip("/")]


def test_key_correcta_en_chat_devuelve_contrato(con_key, llamadas) -> None:
    res = TestClient(app).post("/chat", json={"question": "¿plazo?"}, headers=HEADER_OK)
    assert res.json()["answer"] == "ok"
    assert set(res.json()) == {"answer", "sources", "provider", "model"}


def test_key_correcta_en_stream_emite_sse(con_key, llamadas) -> None:
    res = TestClient(app).post(
        "/chat/stream", json={"question": "¿plazo?"}, headers=HEADER_OK
    )
    assert res.headers["content-type"].startswith("text/event-stream")
    assert 'data: {"type": "done"}' in res.text


def test_nombre_del_header_no_distingue_mayusculas(con_key, llamadas) -> None:
    res = TestClient(app).post(
        "/chat", json={"question": "¿plazo?"}, headers={"x-api-key": KEY}
    )
    assert res.status_code == 200


def test_auth_corre_antes_que_la_validacion_del_body(con_key, llamadas) -> None:
    """Sin key, un body inválido también es 401 (no filtra el schema con un 422)."""
    res = TestClient(app).post("/chat", json={})
    assert res.status_code == 401


def test_api_key_no_ascii_compara_sin_error(monkeypatch, llamadas) -> None:
    """``compare_digest`` sobre bytes: una key con tildes no rompe con 500."""
    monkeypatch.setenv("API_KEY", "contraseña-ñandú")
    res = TestClient(app).post(
        "/chat", json={"question": "¿plazo?"}, headers={"X-API-Key": "contrasena"}
    )
    assert res.status_code == 401


def test_health_sigue_publico_con_key_configurada(con_key, monkeypatch) -> None:
    monkeypatch.setattr(api_main, "get_client", lambda: _ClienteFake())
    monkeypatch.setattr(api_main.httpx, "get", lambda url, timeout: _RespuestaFake())
    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json()["qdrant"] == "ok"


def test_policies_no_cambia_con_key_configurada(con_key, monkeypatch) -> None:
    """Fuera del alcance de #44: /policies sigue como antes (público)."""
    monkeypatch.setattr(api_main, "get_client", lambda: _ClienteFake())
    res = TestClient(app).get("/policies")
    assert res.status_code == 200
    assert res.json() == []


# --- Modo dev (API_KEY vacío) -----------------------------------------------


@pytest.mark.parametrize(("path", "body"), PROTEGIDOS)
def test_modo_dev_sin_key_no_exige_header(
    sin_key, llamadas, path: str, body: dict
) -> None:
    res = TestClient(app).post(path, json=body)
    assert res.status_code == 200


def test_api_key_solo_espacios_cuenta_como_vacia(monkeypatch, llamadas) -> None:
    monkeypatch.setenv("API_KEY", "   ")
    assert auth.auth_habilitada() is False
    res = TestClient(app).post("/chat", json={"question": "¿plazo?"})
    assert res.status_code == 200


def test_modo_dev_avisa_en_logs(sin_key, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        assert auth.avisar_si_modo_dev() is True
    assert "modo dev SIN autenticación" in caplog.text


def test_con_key_no_avisa_modo_dev(con_key, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api.auth"):
        assert auth.avisar_si_modo_dev() is False
    assert caplog.text == ""


def test_arranque_del_api_sin_key_loguea_advertencia(sin_key, caplog) -> None:
    """El lifespan del API emite la advertencia al levantar (``with TestClient``)."""
    with caplog.at_level(logging.WARNING, logger="app.api.auth"), TestClient(app):
        pass
    assert auth.MODO_DEV_AVISO in caplog.text


def test_la_key_nunca_aparece_en_logs_ni_en_la_respuesta(
    con_key, llamadas, caplog
) -> None:
    with caplog.at_level(logging.DEBUG):
        res = TestClient(app).post("/chat", json={"question": "x"})
    assert KEY not in res.text
    assert KEY not in caplog.text


# --- OpenAPI ----------------------------------------------------------------


def test_openapi_documenta_el_esquema_solo_en_endpoints_protegidos() -> None:
    spec = TestClient(app).get("/openapi.json").json()
    esquema = spec["components"]["securitySchemes"]["APIKeyHeader"]
    assert esquema == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API key del despliegue (variable API_KEY del .env).",
    }
    for path, _ in PROTEGIDOS:
        assert spec["paths"][path]["post"]["security"] == [{"APIKeyHeader": []}]
    assert "security" not in spec["paths"]["/health"]["get"]
    assert "security" not in spec["paths"]["/policies"]["get"]

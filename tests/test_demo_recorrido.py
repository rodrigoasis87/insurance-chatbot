"""Tests del paso 6 de ``scripts/demo_recorrido.py`` frente a la auth (Issue #44).

``httpx.post`` va mockeado: se verifica que el script mande ``X-API-Key`` cuando
hay ``API_KEY`` y que un 401 se explique sin tirar traceback.
"""

from __future__ import annotations

import httpx
import pytest

import scripts.demo_recorrido as demo

PAYLOAD_DEM = {
    "codigo": "DEM20260001",
    "molde_base": "POL320200071",
    "creado_en": "2026-10-22T00:00:00",
    "perfil": demo.PERFIL_DEM,
    "secciones": [{"titulo": "COBERTURA", "perfil": "base", "pagina": 1}],
    "pdf_url": "/generated/DEM20260001.pdf",
    "aviso": "BORRADOR",
}


@pytest.fixture
def post_fake(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Reemplaza ``httpx.post``; devuelve el registro de la llamada y el status."""
    registro: dict = {"status": 200}

    def fake_post(url: str, **kwargs) -> httpx.Response:
        registro["url"] = url
        registro["headers"] = kwargs.get("headers") or {}
        status = registro["status"]
        cuerpo = PAYLOAD_DEM if status == 200 else {"detail": "API key inválida"}
        return httpx.Response(status, json=cuerpo, request=httpx.Request("POST", url))

    monkeypatch.setattr(demo.httpx, "post", fake_post)
    return registro


def test_auth_headers_con_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "k-44")
    assert demo._auth_headers() == {"X-API-Key": "k-44"}


def test_auth_headers_sin_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    assert demo._auth_headers() == {}


def test_paso_generacion_manda_x_api_key(post_fake, monkeypatch, capsys) -> None:
    monkeypatch.setenv("API_KEY", "k-44")
    demo.paso_generacion()
    assert post_fake["url"].endswith("/policy-recombine")
    assert post_fake["headers"] == {"X-API-Key": "k-44"}
    assert "DEM20260001" in capsys.readouterr().out


def test_paso_generacion_modo_dev_sin_header(post_fake, monkeypatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    demo.paso_generacion()
    assert post_fake["headers"] == {}


def test_paso_generacion_401_explica_la_key(post_fake, monkeypatch, capsys) -> None:
    monkeypatch.setenv("API_KEY", "equivocada")
    post_fake["status"] = 401
    demo.paso_generacion()
    salida = capsys.readouterr().out
    assert "ERROR 401" in salida
    assert "API_KEY" in salida
    assert "equivocada" not in salida


def test_docstring_trae_curl_con_header() -> None:
    assert '-H "X-API-Key: $API_KEY"' in demo.__doc__

"""Tests de los helpers puros de la generación DEM en la UI (Issue #58).

No testean Chainlit (callbacks delgados); cubren la lógica extraíble en
``app.ui.dem_form``: traducción del vocabulario curado, body del endpoint y
formateo del resultado.
"""

from __future__ import annotations

from app.generation import PERFIL_SCHEMA
from app.ui.dem_form import (
    PERFIL_ORDER,
    build_dem_body,
    dem_pdf_name,
    opciones_perfil,
    perfil_default,
    public_pdf_url,
    render_dem_result,
)


def test_opciones_perfil_cubre_los_8_campos_ordenados() -> None:
    tripletas = opciones_perfil()
    assert [t[0] for t in tripletas] == list(PERFIL_ORDER)
    assert len(tripletas) == 8


def test_opciones_perfil_respeta_vocabulario_curado_sin_si_duplicado() -> None:
    for campo, _, opciones in opciones_perfil():
        permitidos = PERFIL_SCHEMA[campo]
        for opcion in opciones:
            # "si" se normaliza a "sí" y no debe aparecer el alias.
            assert opcion in permitidos or (opcion == "sí" and "si" in permitidos)
            assert opcion != "si"
        # Sin duplicados y ordenadas.
        assert opciones == sorted(set(opciones))


def test_perfil_default_tiene_todos_los_campos_validos() -> None:
    perfil = perfil_default()
    assert set(perfil.keys()) == set(PERFIL_ORDER)
    for campo, valor in perfil.items():
        assert valor in PERFIL_SCHEMA[campo]


def test_build_dem_body() -> None:
    body = build_dem_body("  POL320200071  ", {"edad": "30-40"})
    assert body == {"molde": "POL320200071", "perfil": {"edad": "30-40"}}
    # No muta el perfil de entrada.
    perfil = perfil_default()
    build_dem_body("POL320200071", perfil)
    assert perfil == perfil_default()


def test_public_pdf_url_concatena_sin_duplicar_barra() -> None:
    assert public_pdf_url("http://localhost:8000", "/generated/DEM20260001.pdf") == (
        "http://localhost:8000/generated/DEM20260001.pdf"
    )
    assert public_pdf_url("http://localhost:8000/", "/generated/X.pdf") == (
        "http://localhost:8000/generated/X.pdf"
    )
    assert public_pdf_url("http://localhost:8000", "generated/X.pdf") == (
        "http://localhost:8000/generated/X.pdf"
    )


def test_dem_pdf_name_usa_codigo() -> None:
    assert dem_pdf_name({"codigo": "DEM20260001"}) == "DEM20260001"
    assert dem_pdf_name({}) == "DEM"


def test_render_dem_result_incluye_codigo_secciones_y_aviso() -> None:
    payload = {
        "codigo": "DEM20260001",
        "molde_base": "POL320200071",
        "secciones": [
            {"titulo": "COBERTURA", "nombre": "cobertura", "pagina": 1, "perfil": "base"},
        ],
        "aviso": "BORRADOR · no emitida",
    }
    texto = render_dem_result(payload)
    assert "DEM20260001" in texto
    assert "POL320200071" in texto
    assert "COBERTURA" in texto
    assert "BORRADOR · no emitida" in texto

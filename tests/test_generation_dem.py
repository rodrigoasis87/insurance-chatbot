"""Tests unitarios para la recombinación DEM demo v0 (#36).

Valida el cumplimiento riguroso de:
- docs/CONTRACTS.md §4.1 (Payload, aviso de borrador, código DEM, citas de origen)
- docs/ONTOLOGIA.md §8 (Perfil sin PII, vocabulario controlado de rating)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.generation.dem import (
    AVISO_DEM,
    armar_payload_dem,
    filtrar_articulos_molde,
    generar_codigo_dem,
    generar_dem,
    generar_dem_pdf,
    recombinar_secciones,
    validar_perfil,
)


@pytest.fixture
def perfil_valido() -> dict[str, str]:
    return {
        "edad": "30-40",
        "preexistencias": "no",
        "deportes_riesgo": "no",
        "fonasa_isapre": "isapre",
        "embarazo": "no",
        "cronicas": "no",
        "colectivo": "no",
        "residencia": "chile",
    }


@pytest.fixture
def articulos_mock() -> list[dict[str, Any]]:
    return [
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 1,
            "canonico": "reglas",
            "pagina": 1,
            "texto": "Reglas aplicables al contrato de seguro.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 2,
            "canonico": "cobertura",
            "pagina": 2,
            "texto": "La compañía indemnizará las prestaciones hospitalarias y ambulatorias.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 3,
            "canonico": "definiciones",
            "pagina": 3,
            "texto": "Definiciones para los efectos de la presente póliza.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 4,
            "canonico": "exclusiones",
            "pagina": 5,
            "texto": "Quedan expresamente excluidas del seguro las enfermedades preexistentes no declaradas.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 5,
            "canonico": "carencia",
            "pagina": 7,
            "texto": "Período de carencia de 10 meses para cobertura de maternidad y parto.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 6,
            "canonico": "limitaciones",
            "pagina": 8,
            "texto": "Limitaciones respecto a la práctica de deportes de alta montaña y paracaidismo.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 7,
            "canonico": "vigencia",
            "pagina": 9,
            "texto": "La vigencia de la póliza comenzará a las doce horas del día acordado.",
        },
        {
            "poliza": "POL320200071",
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "salud",
            "articulo": 8,
            "canonico": "domicilio",
            "pagina": 10,
            "texto": "Para todos los efectos legales las partes fijan domicilio en Santiago.",
        },
    ]


def test_validar_perfil_valido(perfil_valido: dict[str, str]) -> None:
    resultado = validar_perfil(perfil_valido)
    assert resultado["edad"] == "30-40"
    assert resultado["preexistencias"] == "no"
    assert resultado["fonasa_isapre"] == "isapre"


def test_validar_perfil_normaliza_si_con_tilde(perfil_valido: dict[str, str]) -> None:
    perfil_valido["preexistencias"] = "si"
    resultado = validar_perfil(perfil_valido)
    assert resultado["preexistencias"] == "sí"


def test_validar_perfil_faltan_campos() -> None:
    perfil_incompleto = {"edad": "30-40"}
    with pytest.raises(ValueError, match="Faltan campos obligatorios"):
        validar_perfil(perfil_incompleto)


def test_validar_perfil_valor_invalido(perfil_valido: dict[str, str]) -> None:
    perfil_valido["edad"] = "100-120"
    with pytest.raises(ValueError, match="no permitido para 'edad'"):
        validar_perfil(perfil_valido)


def test_validar_perfil_rechaza_pii_y_campos_desconocidos(perfil_valido: dict[str, str]) -> None:
    perfil_con_pii = {**perfil_valido, "nombre": "Juan Perez", "rut": "12345678-9"}
    with pytest.raises(ValueError, match="Campos no permitidos en el perfil"):
        validar_perfil(perfil_con_pii)


def test_generar_codigo_dem_formato() -> None:
    codigo_seq1 = generar_codigo_dem(seq=1)
    # Formato DEM{YYYY}{seq:04d} ej DEM20260001
    assert re.match(r"^DEM\d{6,8}$", codigo_seq1)
    assert codigo_seq1.endswith("0001")

    codigo_auto = generar_codigo_dem()
    assert re.match(r"^DEM\d{6,8}$", codigo_auto)


def test_filtrar_articulos_molde_existente(articulos_mock: list[dict[str, Any]]) -> None:
    filtrados = filtrar_articulos_molde("POL320200071", articulos_mock)
    assert len(filtrados) == len(articulos_mock)


def test_filtrar_articulos_molde_inexistente(articulos_mock: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="no encontrado"):
        filtrar_articulos_molde("POL_FANTASMA", articulos_mock)


def test_recombinar_secciones_base(articulos_mock: list[dict[str, Any]], perfil_valido: dict[str, str]) -> None:
    secciones = recombinar_secciones(articulos_mock, perfil_valido)
    nombres = [s["nombre"] for s in secciones]

    assert "cobertura" in nombres
    assert "definiciones" in nombres
    assert "vigencia" in nombres
    assert "domicilio" in nombres

    # Como preexistencias es "no", exclusiones tiene tag "base"
    sec_exclusiones = next(s for s in secciones if s["nombre"] == "exclusiones")
    assert sec_exclusiones["perfil"] == "base"

    # Como embarazo es "no", carencia no se activa
    assert "carencia" not in nombres


def test_recombinar_secciones_con_preexistencias_y_embarazo(
    articulos_mock: list[dict[str, Any]],
    perfil_valido: dict[str, str],
) -> None:
    perfil_valido["preexistencias"] = "sí"
    perfil_valido["embarazo"] = "sí"

    secciones = recombinar_secciones(articulos_mock, perfil_valido)

    # Exclusiones debe estar etiquetada con preexistencias
    sec_exclusiones = next(s for s in secciones if s["nombre"] == "exclusiones")
    assert sec_exclusiones["perfil"] == "preexistencias"

    # Carencia debe estar incluida con perfil embarazo
    sec_carencia = next(s for s in secciones if s["nombre"] == "carencia")
    assert sec_carencia["perfil"] == "embarazo"


def test_contrato_4_1_payload_schema(
    articulos_mock: list[dict[str, Any]],
    perfil_valido: dict[str, str],
) -> None:
    secciones = recombinar_secciones(articulos_mock, perfil_valido)
    payload = armar_payload_dem(
        molde="POL320200071",
        perfil=perfil_valido,
        secciones=secciones,
        codigo="DEM260001",
    )

    # Verificación de claves requeridas por docs/CONTRACTS.md §4.1
    assert payload["codigo"] == "DEM260001"
    assert payload["molde_base"] == "POL320200071"
    assert "creado_en" in payload
    assert payload["perfil"] == perfil_valido
    assert isinstance(payload["secciones"], list)
    assert payload["pdf_url"] == "/generated/DEM260001.pdf"
    assert "BORRADOR · no emitida" in payload["aviso"]
    assert "estándar de la corredora" in payload["aviso"]

    # Verificación de que DEM nunca se rotula como póliza POL emitida
    assert not payload["codigo"].startswith("POL")


def test_secciones_conservan_citas_de_origen(
    articulos_mock: list[dict[str, Any]],
    perfil_valido: dict[str, str],
) -> None:
    secciones = recombinar_secciones(articulos_mock, perfil_valido)
    for s in secciones:
        assert "nombre" in s
        assert "titulo" in s
        assert "pagina" in s
        assert isinstance(s["pagina"], int)
        assert s["pagina"] > 0
        assert "perfil" in s
        assert "texto" in s
        assert len(s["texto"]) > 0


def test_generar_dem_pdf_crea_archivo(
    articulos_mock: list[dict[str, Any]],
    perfil_valido: dict[str, str],
    tmp_path: Path,
) -> None:
    salida_pdf = tmp_path / "test_dem.pdf"
    payload, pdf_path = generar_dem(
        molde="POL320200071",
        perfil=perfil_valido,
        articulos=articulos_mock,
        ruta_salida_pdf=salida_pdf,
        seq=1,
    )

    assert pdf_path.exists()
    assert pdf_path.is_file()
    assert pdf_path.stat().st_size > 0

    # Validar que es un PDF legítimo leyendo los bytes de cabecera
    with open(pdf_path, "rb") as f:
        cabecera = f.read(5)
        assert cabecera == b"%PDF-"


def test_cli_runner(articulos_mock: list[dict[str, Any]], tmp_path: Path) -> None:
    from app.generation.__main__ import main
    from unittest.mock import patch

    perfil_json = json.dumps(
        {
            "edad": "30-40",
            "preexistencias": "no",
            "deportes_riesgo": "no",
            "fonasa_isapre": "isapre",
            "embarazo": "no",
            "cronicas": "no",
            "colectivo": "no",
            "residencia": "chile",
        }
    )

    args = [
        "--molde",
        "POL320200071",
        "--perfil",
        perfil_json,
        "--output-dir",
        str(tmp_path),
        "--seq",
        "42",
        "--json",
    ]

    with patch("app.generation.dem.cargar_articulos", return_value=articulos_mock):
        exit_code = main(args)
        assert exit_code == 0

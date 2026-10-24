"""Helpers puros para la generación DEM desde la UI (Issue #58).

Sin Chainlit ni red: funciones testeables que traducen el vocabulario curado
(``app.generation.dem.PERFIL_SCHEMA``) a opciones de formulario, arman el body
de ``POST /policy-recombine`` y formatean el resultado (código, secciones y
URL pública del PDF).
"""

from __future__ import annotations

from typing import Any

from app.generation import AVISO_DEM, PERFIL_SCHEMA

# Orden de presentación de los 8 campos del perfil en el panel derecho.
PERFIL_ORDER: tuple[str, ...] = (
    "edad",
    "preexistencias",
    "deportes_riesgo",
    "fonasa_isapre",
    "embarazo",
    "cronicas",
    "colectivo",
    "residencia",
)

# Etiquetas legibles por campo (para el ``label`` del Select).
PERFIL_LABELS: dict[str, str] = {
    "edad": "Edad",
    "preexistencias": "Preexistencias",
    "deportes_riesgo": "Deportes de riesgo",
    "fonasa_isapre": "Fonasa / Isapre",
    "embarazo": "Embarazo",
    "cronicas": "Enfermedades crónicas",
    "colectivo": "Contrato colectivo",
    "residencia": "Residencia",
}

# Perfil por defecto (demo, sin PII; coincide con scripts/demo_recorrido.py).
PERFIL_DEFAULT: dict[str, str] = {
    "edad": "30-40",
    "preexistencias": "no",
    "deportes_riesgo": "no",
    "fonasa_isapre": "isapre",
    "embarazo": "no",
    "cronicas": "no",
    "colectivo": "no",
    "residencia": "chile",
}

# Molde base por defecto si /policies no responde (demo v0).
MOLDE_DEFAULT = "POL320200071"


def _opciones_canonicas(opciones: set[str]) -> list[str]:
    """Ordena y normaliza las opciones: ``si`` → ``sí`` y elimina duplicados."""
    resultado: list[str] = []
    for opcion in sorted(opciones):
        canonica = "sí" if opcion == "si" else opcion
        if canonica not in resultado:
            resultado.append(canonica)
    return resultado


def opciones_perfil() -> list[tuple[str, str, list[str]]]:
    """``[(id, label, opciones_ordenadas)]`` de los 8 campos del perfil curado.

    Única fuente de verdad: ``PERFIL_SCHEMA`` de ``app.generation.dem``.
    """
    return [
        (campo, PERFIL_LABELS[campo], _opciones_canonicas(PERFIL_SCHEMA[campo]))
        for campo in PERFIL_ORDER
    ]


def perfil_default() -> dict[str, str]:
    """Copia del perfil demo por defecto (sin PII)."""
    return dict(PERFIL_DEFAULT)


def build_dem_body(molde: str, perfil: dict[str, Any]) -> dict[str, Any]:
    """Body de ``POST /policy-recombine`` (CONTRACTS §4.1)."""
    return {"molde": molde.strip(), "perfil": dict(perfil)}


def public_pdf_url(base: str, pdf_path: str) -> str:
    """URL absoluta del PDF alcanzable desde el navegador.

    ``pdf_path`` es relativo al API (ej. ``/generated/DEM20260001.pdf``);
    ``base`` es ``API_PUBLIC_URL`` (ej. ``http://localhost:8000``). Evita
    duplicar la barra separadora.
    """
    base_ok = base.rstrip("/")
    path_ok = pdf_path if pdf_path.startswith("/") else f"/{pdf_path}"
    return f"{base_ok}{path_ok}"


def dem_pdf_name(payload: dict[str, Any]) -> str:
    """Nombre del elemento PDF (código DEM)."""
    return str(payload.get("codigo") or "DEM")


def render_dem_result(payload: dict[str, Any]) -> str:
    """Mensaje de confirmación: código, molde, secciones con cita y aviso."""
    lineas = [
        f"**Borrador DEM generado:** `{payload.get('codigo', '-')}`",
        f"Molde base: `{payload.get('molde_base', '-')}`",
        "",
    ]
    secciones = payload.get("secciones", [])
    if secciones:
        lineas.append(f"Cláusulas recombinadas ({len(secciones)}):")
        for s in secciones:
            titulo = s.get("titulo") or s.get("nombre") or "?"
            perfil_tag = s.get("perfil", "-")
            lineas.append(
                f"- **{titulo}** · pág. {s.get('pagina', '-')} · perfil: `{perfil_tag}`"
            )
    lineas.append("")
    aviso = payload.get("aviso") or AVISO_DEM
    lineas.append(f"> {aviso}")
    return "\n".join(lineas)

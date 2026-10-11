"""Módulo de generación y recombinación de pólizas (DEM demo v0 · #36)."""

from typing import Any

__all__ = [
    "AVISO_DEM",
    "PERFIL_SCHEMA",
    "armar_payload_dem",
    "cargar_articulos",
    "filtrar_articulos_molde",
    "generar_codigo_dem",
    "generar_dem",
    "generar_dem_pdf",
    "recombinar_secciones",
    "validar_perfil",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        import app.generation.dem as _dem

        return getattr(_dem, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

"""Módulo de generación y recombinación de pólizas (DEM demo v0 · #36)."""

from app.generation.dem import (
    AVISO_DEM,
    PERFIL_SCHEMA,
    armar_payload_dem,
    cargar_articulos,
    filtrar_articulos_molde,
    generar_codigo_dem,
    generar_dem,
    generar_dem_pdf,
    recombinar_secciones,
    validar_perfil,
)

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

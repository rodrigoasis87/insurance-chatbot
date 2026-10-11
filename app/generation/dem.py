"""Módulo de recombinación de pólizas DEM demo v0 (#36).

Ensambla bloques de cláusulas canónicas de un molde base del catálogo
y un perfil de cliente curado (sin PII) para generar un borrador estándar
en formato JSON y PDF.

Cumple con:
- docs/CONTRACTS.md §4.1 (Contrato de Generación · Recombinación DEM)
- docs/ONTOLOGIA.md §8 (Perfil del cliente sin PII)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pymupdf as fitz

from app.paths import ARTICULOS_JSONL, DATA_DIR

GENERATED_DIR = DATA_DIR / "generated"

# ---------------------------------------------------------------------------
# Dominio canónico de condiciones de perfil (docs/ONTOLOGIA.md §8)
# ---------------------------------------------------------------------------
PERFIL_SCHEMA: dict[str, set[str]] = {
    "edad": {"0-18", "19-29", "30-40", "41-50", "51-60", "61-70", "71+"},
    "preexistencias": {"no", "sí", "si"},
    "deportes_riesgo": {"no", "sí", "si"},
    "fonasa_isapre": {"fonasa", "isapre"},
    "embarazo": {"no", "sí", "si"},
    "cronicas": {"no", "sí", "si"},
    "colectivo": {"individual", "colectivo", "no", "sí", "si"},
    "residencia": {"chile", "extranjero"},
}

# Aviso legal obligatorio según docs/CONTRACTS.md §4.1
AVISO_DEM: str = (
    "BORRADOR · no emitida · estándar de la corredora (código DEM); "
    "la aseguradora puede adoptarlo y depositarlo como POL."
)

# Secciones base que siempre se incorporan si existen en el molde
SECCIONES_BASE: tuple[str, ...] = (
    "reglas",
    "cobertura",
    "descripcion de coberturas",
    "riesgos cubiertos",
    "definiciones",
    "exclusiones",
    "primas",
    "vigencia",
    "denuncia de siniestro",
    "domicilio",
)


def normalizar_valor_perfil(clave: str, valor: Any) -> str:
    """Normaliza y valida un valor individual del perfil."""
    if not isinstance(valor, str):
        raise ValueError(f"El campo '{clave}' debe ser texto, se recibió: {type(valor).__name__}")

    val = valor.strip().lower()
    # Normalizar guiones en rango de edad (en-dash a hyphen)
    if clave == "edad":
        val = val.replace("–", "-")

    valores_permitidos = PERFIL_SCHEMA.get(clave)
    if valores_permitidos is None:
        raise ValueError(f"Campo de perfil desconocido: '{clave}'. Campos válidos: {list(PERFIL_SCHEMA.keys())}")

    if val not in valores_permitidos:
        raise ValueError(
            f"Valor '{valor}' no permitido para '{clave}'. Opciones válidas: {sorted(valores_permitidos)}"
        )

    # Devolver formato canónico consistente
    if val == "si":
        return "sí"
    return val


def validar_perfil(perfil: dict[str, Any]) -> dict[str, str]:
    """Valida que el perfil contenga solo opciones curadas del vocabulario controlado.

    Reglas de diseño (docs/ONTOLOGIA.md §8):
    1. Opciones curadas: solo valores del dominio canónico.
    2. No persiste: vive en memoria durante la ejecución.
    3. Sin PII: solo rating factors sin nombres ni identificadores.
    """
    if not isinstance(perfil, dict):
        raise ValueError("El perfil debe ser un diccionario.")

    campos_faltantes = [campo for campo in PERFIL_SCHEMA if campo not in perfil]
    if campos_faltantes:
        raise ValueError(
            f"Faltan campos obligatorios en el perfil: {campos_faltantes}. "
            f"Campos requeridos: {list(PERFIL_SCHEMA.keys())}"
        )

    campos_sobrantes = [campo for campo in perfil if campo not in PERFIL_SCHEMA]
    if campos_sobrantes:
        raise ValueError(
            f"Campos no permitidos en el perfil: {campos_sobrantes}. No se permite PII ni texto libre."
        )

    perfil_normalizado: dict[str, str] = {}
    for clave, valor in perfil.items():
        perfil_normalizado[clave] = normalizar_valor_perfil(clave, valor)

    return perfil_normalizado


def cargar_articulos(ruta_articulos: Path | None = None) -> list[dict[str, Any]]:
    """Carga los artículos parseados desde articulos.jsonl."""
    ruta = ruta_articulos or ARTICULOS_JSONL
    if not ruta.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de artículos en '{ruta}'. "
            "Asegúrese de haber ejecutado el pipeline de datos (app.data.build_articulos)."
        )

    articulos: list[dict[str, Any]] = []
    with open(ruta, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                articulos.append(json.loads(linea))
    return articulos


def filtrar_articulos_molde(molde: str, articulos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra y agrupa los artículos pertenecientes a una póliza molde base."""
    molde_upper = molde.strip().upper()
    articulos_molde = [
        art for art in articulos if str(art.get("poliza", "")).strip().upper() == molde_upper
    ]

    if not articulos_molde:
        moldes_disponibles = sorted({str(art.get("poliza")) for art in articulos if art.get("poliza")})
        raise ValueError(
            f"Molde '{molde}' no encontrado. Moldes disponibles en el catálogo: {moldes_disponibles}"
        )

    return articulos_molde


def recombinar_secciones(
    articulos_molde: list[dict[str, Any]],
    perfil: dict[str, str],
) -> list[dict[str, Any]]:
    """Selecciona y etiqueta los bloques canónicos del molde según el perfil.

    El perfil NO modifica el texto legal de las cláusulas; únicamente determina
    cuáles bloques se incluyen y qué etiqueta de trazabilidad de perfil reciben.
    """
    # Mapear artículos por clave canónica (conservando el primero o de mayor jerarquía)
    por_canonico: dict[str, dict[str, Any]] = {}
    for art in articulos_molde:
        canon = art.get("canonico", "").strip().lower()
        if canon and canon not in por_canonico:
            por_canonico[canon] = art

    secciones: list[dict[str, Any]] = []
    vistos: set[str] = set()

    def agregar_seccion(canon: str, tag_perfil: str) -> None:
        if canon in por_canonico and canon not in vistos:
            art = por_canonico[canon]
            titulo = art.get("canonico", canon).upper()
            secciones.append(
                {
                    "nombre": canon,
                    "titulo": titulo,
                    "pagina": int(art.get("pagina", 1)),
                    "perfil": tag_perfil,
                    "texto": str(art.get("texto", "")).strip(),
                }
            )
            vistos.add(canon)

    # 1. Secciones base estándar
    for sec_base in SECCIONES_BASE:
        if sec_base == "exclusiones" and perfil.get("preexistencias") == "sí":
            # Si tiene preexistencias, exclusiones se etiqueta para resaltar ese factor
            agregar_seccion("exclusiones", "preexistencias")
        else:
            agregar_seccion(sec_base, "base")

    # 2. Secciones condicionales por perfil
    if perfil.get("embarazo") == "sí":
        agregar_seccion("carencia", "embarazo")

    if perfil.get("deportes_riesgo") == "sí":
        agregar_seccion("limitaciones", "deportes_riesgo")

    if perfil.get("colectivo") in ("colectivo", "sí"):
        agregar_seccion("incorporacion", "colectivo")

    if perfil.get("residencia") == "extranjero":
        agregar_seccion("pais de residencia", "residencia")

    if perfil.get("cronicas") == "sí":
        agregar_seccion("agravacion del riesgo", "cronicas")

    if perfil.get("edad") in ("61-70", "71+"):
        agregar_seccion("terminacion", "edad")

    # Si aún no se agregó exclusiones (porque no entró arriba), asegurar que esté
    if "exclusiones" in por_canonico and "exclusiones" not in vistos:
        agregar_seccion("exclusiones", "base")

    return secciones


def generar_codigo_dem(seq: int | None = None) -> str:
    """Genera un código correlativo estándar DEM según docs/CONTRACTS.md §4.1.

    Formato: DEM{YY}{seq:04d} (ej. DEM260001).
    """
    anio_yy = datetime.now().strftime("%y")
    if seq is None:
        # Para demo v0 sin base de datos persistente: correlativo pseudo-único
        seq = int(datetime.now().timestamp()) % 10000 or 1
    return f"DEM{anio_yy}{seq:04d}"


def armar_payload_dem(
    molde: str,
    perfil: dict[str, str],
    secciones: list[dict[str, Any]],
    codigo: str,
    creado_en: str | None = None,
) -> dict[str, Any]:
    """Construye el payload JSON estandarizado conforme a CONTRACTS.md §4.1."""
    timestamp = creado_en or datetime.now().isoformat()
    return {
        "codigo": codigo,
        "molde_base": molde.strip().upper(),
        "creado_en": timestamp,
        "perfil": perfil,
        "secciones": secciones,
        "pdf_url": f"/generated/{codigo}.pdf",
        "aviso": AVISO_DEM,
    }


def generar_dem_pdf(
    payload: dict[str, Any],
    ruta_salida: Path | None = None,
) -> Path:
    """Genera un documento PDF con marca de borrador y citas de origen.

    Utiliza PyMuPDF para crear un PDF A4 limpio con encabezado,
    citas de origen por sección y aviso de borrador no emitida.
    """
    codigo = payload["codigo"]
    molde_base = payload["molde_base"]
    creado_en = payload.get("creado_en", datetime.now().isoformat())
    aviso = payload.get("aviso", AVISO_DEM)
    secciones = payload.get("secciones", [])

    if ruta_salida is None:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        ruta_salida = GENERATED_DIR / f"{codigo}.pdf"
    else:
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()

    # Dimensiones A4 en puntos (72 dpi): 595 x 842
    ancho, alto = 595.0, 842.0
    margen_x = 50.0
    margen_y_top = 60.0
    margen_y_bottom = 780.0
    line_height = 13.0

    pagina_actual = doc.new_page(width=ancho, height=alto)
    y = margen_y_top

    def dibujar_encabezado(page: fitz.Page) -> float:
        """Dibuja encabezado formal y aviso de borrador."""
        # Franja superior de borrador
        page.draw_rect(
            fitz.Rect(margen_x, 30, ancho - margen_x, 48),
            color=(0.85, 0.2, 0.2),
            fill=(0.98, 0.92, 0.92),
        )
        page.insert_text(
            fitz.Point(margen_x + 10, 43),
            "BORRADOR · NO EMITIDA · ESTÁNDAR DEM CORREDORA",
            fontsize=10,
            fontname="helv",
            color=(0.8, 0.1, 0.1),
        )

        # Metadatos del documento
        page.insert_text(
            fitz.Point(margen_x, 70),
            f"Propuesta Técnica DEM: {codigo}",
            fontsize=15,
            fontname="hebo",
            color=(0.1, 0.1, 0.2),
        )
        page.insert_text(
            fitz.Point(margen_x, 86),
            f"Molde Base CMF: {molde_base}   |   Fecha de Generación: {creado_en[:19]}",
            fontsize=9,
            fontname="helv",
            color=(0.3, 0.3, 0.3),
        )

        # Caja de advertencia de aviso legal
        page.draw_rect(
            fitz.Rect(margen_x, 96, ancho - margen_x, 126),
            color=(0.8, 0.8, 0.8),
            fill=(0.96, 0.96, 0.96),
        )
        page.insert_textbox(
            fitz.Rect(margen_x + 8, 98, ancho - margen_x - 8, 124),
            f"Aviso legal: {aviso}",
            fontsize=7.5,
            fontname="helv",
            color=(0.25, 0.25, 0.25),
        )
        page.draw_line(
            fitz.Point(margen_x, 134),
            fitz.Point(ancho - margen_x, 134),
            color=(0.7, 0.7, 0.7),
            width=0.7,
        )
        return 148.0

    y = dibujar_encabezado(pagina_actual)

    def envolver_texto(texto: str, max_chars: int = 92) -> list[str]:
        lineas_salida: list[str] = []
        for parrafo in texto.split("\n"):
            parrafo = parrafo.strip()
            if not parrafo:
                lineas_salida.append("")
                continue
            palabras = parrafo.split(" ")
            linea_act = ""
            for p in palabras:
                if not p:
                    continue
                if len(linea_act) + len(p) + 1 <= max_chars:
                    linea_act = f"{linea_act} {p}".strip()
                else:
                    lineas_salida.append(linea_act)
                    linea_act = p
            if linea_act:
                lineas_salida.append(linea_act)
        return lineas_salida

    for idx, sec in enumerate(secciones, start=1):
        titulo_sec = f"CLÁUSULA {idx}: {sec['titulo']}"
        cita_origen = f"[Fuente de origen: {molde_base} · Pág. {sec['pagina']} · Perfil activador: {sec['perfil']}]"

        # Verificar espacio para título y cabecera de sección
        if y + 45 > margen_y_bottom:
            pagina_actual = doc.new_page(width=ancho, height=alto)
            y = margen_y_top

        # Título de la sección
        pagina_actual.insert_text(
            fitz.Point(margen_x, y),
            titulo_sec,
            fontsize=11,
            fontname="hebo",
            color=(0.1, 0.15, 0.35),
        )
        y += 14.0

        # Cita de origen
        pagina_actual.insert_text(
            fitz.Point(margen_x, y),
            cita_origen,
            fontsize=8,
            fontname="helv",
            color=(0.4, 0.4, 0.4),
        )
        y += 16.0

        # Líneas de cuerpo
        lineas = envolver_texto(sec.get("texto", ""))
        for linea in lineas:
            if y + line_height > margen_y_bottom:
                pagina_actual = doc.new_page(width=ancho, height=alto)
                y = margen_y_top

            if linea:
                pagina_actual.insert_text(
                    fitz.Point(margen_x, y),
                    linea,
                    fontsize=8.5,
                    fontname="helv",
                    color=(0.15, 0.15, 0.15),
                )
            y += line_height

        y += 10.0  # Separación entre cláusulas

    # Agregar números de página y pie en todas las páginas
    total_paginas = len(doc)
    for num_p, page in enumerate(doc, start=1):
        pie = f"Página {num_p} de {total_paginas}   |   {codigo} · Borrador DEM no emitida   |   Corredora de Seguros"
        page.draw_line(
            fitz.Point(margen_x, alto - 35),
            fitz.Point(ancho - margen_x, alto - 35),
            color=(0.8, 0.8, 0.8),
            width=0.5,
        )
        page.insert_text(
            fitz.Point(margen_x, alto - 22),
            pie,
            fontsize=7.5,
            fontname="helv",
            color=(0.4, 0.4, 0.4),
        )

    doc.save(str(ruta_salida))
    doc.close()
    return ruta_salida


def generar_dem(
    molde: str,
    perfil: dict[str, Any],
    articulos: list[dict[str, Any]] | None = None,
    ruta_salida_pdf: Path | None = None,
    seq: int | None = None,
) -> tuple[dict[str, Any], Path]:
    """Flujo completo de generación y recombinación DEM demo v0.

    1. Valida el perfil curado (sin PII).
    2. Carga y filtra los artículos canónicos del molde base.
    3. Recombina y etiqueta las secciones pertinentes.
    4. Genera el código DEM y arma el payload conforme a CONTRACTS.md §4.1.
    5. Renderiza y guarda el borrador PDF con PyMuPDF.

    Returns:
        tuple[dict, Path]: (payload_json, ruta_pdf_generado)
    """
    perfil_val = validar_perfil(perfil)

    if articulos is None:
        articulos = cargar_articulos()

    articulos_molde = filtrar_articulos_molde(molde, articulos)
    secciones = recombinar_secciones(articulos_molde, perfil_val)

    codigo = generar_codigo_dem(seq=seq)
    payload = armar_payload_dem(
        molde=molde,
        perfil=perfil_val,
        secciones=secciones,
        codigo=codigo,
    )

    ruta_pdf = generar_dem_pdf(payload, ruta_salida=ruta_salida_pdf)
    return payload, ruta_pdf


DEMO_ARTICULOS: list[dict[str, Any]] = [
    {
        "poliza": "POL320200071",
        "documento": 1,
        "ramo": "salud",
        "año": "2020",
        "familia": "salud",
        "articulo": 1,
        "canonico": "reglas",
        "pagina": 1,
        "texto": "Reglas aplicables al contrato de seguro de salud complementario.",
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
        "texto": "La compañía aseguradora indemnizará las prestaciones ambulatorias y hospitalarias cubiertas.",
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
        "texto": "Para los efectos de esta póliza se establecen las definiciones técnicas y contractuales aplicables.",
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
        "texto": "Quedan expresamente excluidas del seguro las enfermedades o dolencias preexistentes no declaradas.",
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
        "texto": "Se establece un período de carencia de 10 meses para las coberturas asociadas a embarazo y maternidad.",
    },
    {
        "poliza": "POL320200071",
        "documento": 1,
        "ramo": "salud",
        "año": "2020",
        "familia": "salud",
        "articulo": 6,
        "canonico": "vigencia",
        "pagina": 9,
        "texto": "La vigencia de la póliza comenzará a las 12:00 horas del día de inicio pactado.",
    },
    {
        "poliza": "POL320200071",
        "documento": 1,
        "ramo": "salud",
        "año": "2020",
        "familia": "salud",
        "articulo": 7,
        "canonico": "domicilio",
        "pagina": 10,
        "texto": "Para todos los efectos legales que emanen de este contrato las partes fijan domicilio especial en Santiago.",
    },
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recombinación de cláusulas canónicas DEM demo v0 (docs/CONTRACTS.md §4.1)."
    )
    parser.add_argument(
        "--molde",
        type=str,
        required=True,
        help="Código de la póliza molde base del catálogo (ej. POL320200071).",
    )
    parser.add_argument(
        "--perfil",
        type=str,
        required=True,
        help="Perfil del cliente curado en formato JSON string o ruta a archivo JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directorio donde guardar el PDF generado (por defecto: data/generated).",
    )
    parser.add_argument(
        "--articulos",
        type=Path,
        default=None,
        help="Ruta alternativa a articulos.jsonl (por defecto: data/processed/articulos.jsonl).",
    )
    parser.add_argument(
        "--seq",
        type=int,
        default=None,
        help="Correlativo numérico opcional para el código DEM (ej. 1 -> DEM260001).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime el payload JSON completo en la salida estándar.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Usa artículos de muestra en memoria para demostración sin requerir articulos.jsonl.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Cargar perfil desde JSON string o archivo
    perfil_str = args.perfil.strip()
    if Path(perfil_str).is_file():
        with open(perfil_str, "r", encoding="utf-8") as f:
            perfil = json.load(f)
    else:
        try:
            perfil = json.loads(perfil_str)
        except json.JSONDecodeError as err:
            print(f"Error al parsear el JSON de perfil: {err}", file=sys.stderr)
            return 1

    ruta_pdf_salida = None
    if args.output_dir:
        ruta_pdf_salida = args.output_dir / f"temp.pdf"

    articulos = None
    if args.demo:
        articulos = DEMO_ARTICULOS
    elif args.articulos:
        articulos = cargar_articulos(args.articulos)
    elif not ARTICULOS_JSONL.exists():
        # Modo fallback para demostración si articulos.jsonl aún no ha sido generado
        articulos = DEMO_ARTICULOS

    try:
        payload, pdf_path = generar_dem(
            molde=args.molde,
            perfil=perfil,
            articulos=articulos,
            ruta_salida_pdf=ruta_pdf_salida,
            seq=args.seq,
        )
    except Exception as err:
        print(f"Error en la recombinación DEM: {err}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("  RECOMBINACIÓN DEM · DEMO V0 (#36)")
    print("=" * 60)
    print(f"Código DEM   : {payload['codigo']}")
    print(f"Molde Base   : {payload['molde_base']}")
    print(f"PDF Generado : {pdf_path}")
    print(f"Secciones    : {len(payload['secciones'])} cláusulas recombinadas:")
    for s in payload["secciones"]:
        print(f"  - [{s['nombre']:<20}] pág. {s['pagina']:<2} (perfil: {s['perfil']}) -> {s['titulo']}")
    print("-" * 60)
    print(f"Aviso legal  : {payload['aviso']}")
    print("=" * 60)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())

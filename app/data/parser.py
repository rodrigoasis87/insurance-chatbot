"""Parsing reutilizable de polizas (PDF -> articulos estructurados).

Extrae la estructura de una poliza de seguro a partir de los PDFs en
``data/raw_pdfs``: detecta las cabeceras ``ARTICULO``, las normaliza a
claves canonicas y permite recuperar el texto de cada articulo.

Lo usan tanto el EDA (``app/data/eda.py``) como el pipeline de datos
(Issue #4) para generar ``data/processed/articulos.jsonl``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.paths import RAW_PDFS_DIR

_ACCENT_PAIRS = {}
for _src, _dst in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n")):
    _ACCENT_PAIRS[_src] = _dst
    _ACCENT_PAIRS[_src.upper()] = _dst.upper()
UNACCENT = str.maketrans(_ACCENT_PAIRS)


def unaccent(text: str) -> str:
    """Devuelve ``text`` sin tildes (util para matchear titulos)."""
    return text.translate(UNACCENT).lower()


# Titulo canonico -> keywords (sin acentos) que lo identifican.
# Orden importa: lo mas especifico va primero (antes de "cobertura", que es
# substring de "coberturas" en otras cabeceras).
TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "reglas": ("reglas aplicables",),
    "descripcion de coberturas": ("descripcion de las coberturas", "descripcion de coberturas"),
    "limitaciones": ("limitaciones",),
    "otros seguros": ("otros seguros",),
    "riesgos cubiertos": ("riesgos cubiertos",),
    "cobertura": ("cobertura",),
    "definiciones": ("definiciones",),
    "exclusiones": ("exclusiones",),
    "obligaciones": ("obligaciones",),
    "declaraciones": ("declaraciones",),
    "primas": ("no pago de la prima", "no pago de las primas", "prima del seguro", "primas"),
    "denuncia de siniestro": ("siniestro",),
    "vigencia": ("vigencia",),
    "terminacion": ("terminacion", "termino"),
    "domicilio": ("domicilio",),
    "clausulas adicionales": ("clausulas adicionales",),
    "beneficiarios": ("beneficiarios",),
    "monto maximo de reembolso": ("monto maximo de reembolso",),
    "liquidacion de gastos": ("liquidacion de los gastos", "formula de liquidacion"),
    "calculo de gastos": ("calculo de los gastos reembolsables",),
    "deducible": ("deducible",),
    "copago": ("copago",),
    "ajuste de la prima": ("ajuste de la prima",),
    "unidad del contrato": ("unidad del contrato", "unidad de la poliza", "moneda o unidad"),
    "carencia": ("carencia",),
    "comunicaciones": ("comunicacion",),
    "controversias": ("controversias",),
    "retracto": ("retracto",),
    "agravacion del riesgo": ("agravacion",),
    "rehabilitacion": ("rehabilitacion",),
    "impuestos": ("impuestos", "contribuciones"),
    "modificaciones": ("modificaciones",),
    "pais de residencia": ("pais de residencia",),
    "incorporacion": ("incorporacion",),
    "duplicacion de beneficios": ("duplicacion",),
}

# Tokens que delatan referencias inline dentro del texto (no cabeceras).
INLINE_TOKENS = ("de estas", "letra", "numeral", "inciso")

HDR_RE = re.compile(
    r"^\s*ART\s*[ÍI]CULO\s+"
    r"(?:N[º°]?\s*\.?\s*)?"
    r"(\d{1,2})\s*[º°]?\s*\.?\s*[:.\-—–]?\s*"
    r"(.+?)\s*[.\-—–]*\.?\s*$",
    re.IGNORECASE,
)


def canonical_title(raw: str) -> tuple[str, str] | None:
    """Normaliza el titulo de un articulo a su clave canonica.

    Devuelve ``(clave, titulo_limpio)`` o ``None`` si la linea es una
    referencia inline (no una cabecera de articulo). Reglas:

    * Si matchea una keyword canonica → se acepta (aun en estilos con
      continuacion de oracion, como la poliza COVID).
    * Si la linea es MAYÚSCULA y corta → se acepta como cabecera generica.
    * Caso contrario (referencias ``Artículo N° ...`` en mixta/minúscula)
      → ``None``.
    """
    title = raw.strip().rstrip(r".:\-—– ").strip()
    if not title:
        return None
    is_upper = title.replace(" ", "").isupper()
    sentence = re.match(r"^(.{1,64})\.\s", title)
    head = sentence.group(1).strip() if sentence else title
    low = unaccent(head)
    if any(tok in low for tok in INLINE_TOKENS):
        return None
    for key, kws in TITLE_KEYWORDS.items():
        if any(kw in low for kw in kws):
            if is_upper and head == title and len(title) <= 70:
                return key, title
            return key, key.capitalize()
    if is_upper and head == title and len(title) <= 70:
        return title.title(), title
    return None


@dataclass
class Article:
    """Un articulo detectado dentro de una poliza."""

    number: int
    title: str
    canonical: str
    page: int
    start_idx: int
    end_page: int
    end_idx: int
    chars: int = 0


def page_text(doc: pymupdf.Document, pno: int) -> str:
    """Texto plano (sin objetos dibujo) de la pagina ``pno`` (0-based)."""
    return doc[pno].get_text()


def extract_articles(path: Path) -> list[Article]:
    """Segmenta una poliza en articulos usando sus cabeceras ``ARTICULO``.

    Cada articulo abarca desde su cabecera hasta la siguiente cabecera (o el
    final del documento). Se descartan las referencias inline a otros
    articulos (p. ej. ``Artículo 2°, letra A, numeral 4...``).
    """
    doc = pymupdf.open(path)
    texts = [page_text(doc, i) for i in range(doc.page_count)]
    bounds: list[tuple[int, int]] = []
    for pno, text in enumerate(texts):
        for line in text.splitlines():
            m = HDR_RE.match(line)
            if not m:
                continue
            parsed = canonical_title(m.group(2))
            if parsed is None:
                continue
            key, title = parsed
            idx = text.find(line)
            bounds.append((pno + 1, idx, int(m.group(1)), title, key))

    articles: list[Article] = []
    for i, (page, idx, number, title, key) in enumerate(bounds):
        if i + 1 < len(bounds):
            end_page, end_idx = bounds[i + 1][:2]
        else:
            end_page, end_idx = doc.page_count, len(texts[-1])
        start_p, start_i = page, idx
        if end_page == start_p:
            chars = end_idx - start_i
        else:
            chars = len(texts[start_p - 1]) - start_i
            chars += sum(len(t) for t in texts[start_p : end_page - 1])
            chars += end_idx
        articles.append(
            Article(
                number=number,
                title=title,
                canonical=key,
                page=start_p,
                start_idx=start_i,
                end_page=end_page,
                end_idx=end_idx,
                chars=chars,
            )
        )
    doc.close()
    return articles


def segment_text(doc: pymupdf.Document, a: Article) -> str:
    """Extrae el texto completo del segmento delimitado por el articulo ``a``."""
    if a.page == a.end_page:
        return page_text(doc, a.page - 1)[a.start_idx : a.end_idx]
    parts: list[str] = [page_text(doc, a.page - 1)[a.start_idx :]]
    for pno in range(a.page, a.end_page - 1):
        parts.append(page_text(doc, pno))
    parts.append(page_text(doc, a.end_page - 1)[: a.end_idx])
    return "".join(parts)
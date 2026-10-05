"""Parsing reutilizable de polizas (PDF -> articulos estructurados).

Extrae la estructura de una poliza de seguro a partir de los PDFs en
``data/raw_pdfs``: detecta las cabeceras ``ARTICULO``, las normaliza a
claves canonicas y permite recuperar el texto de cada articulo.

Ojo con un supuesto que NO se cumple en este corpus: **un PDF no es una póliza**.
Los archivos del Depósito traen varios documentos de depósito pegados y cada uno
reinicia su numeración de artículos, así que hay 9 archivos pero 10 códigos de
depósito reales y ``(poliza, articulo)`` **no es clave**. La clave única es
``(poliza, documento, articulo)``; ver :func:`subdocumentos` y
:func:`asignar_documentos`, y ``docs/CONTRACTS.md`` sección 1.1.

Lo usan tanto el EDA (``app/data/eda.py``) como el pipeline de datos
(Issue #4) para generar ``data/processed/articulos.jsonl``.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


# Un PDF del Deposito puede traer VARIOS documentos de deposito pegados, cada
# uno con su propio codigo y su propia numeracion de articulos que reinicia en
# 1. Ejemplo real: ``POL320190074.pdf`` contiene ``POL320190074`` (pag 1-15) y
# ``POL320130223`` (pag 16-72). Por eso ``(poliza, articulo)`` NO es clave.
DEPOSITO_RE = re.compile(
    r"Incorporada al Dep[oó]sito de P[oó]lizas bajo el c[oó]digo\s+(POL\d+)",
    re.IGNORECASE,
)


@dataclass
class Subdocumento:
    """Un documento de deposito real dentro de un PDF del corpus.

    ``codigo`` es el codigo REAL (puede diferir del nombre del archivo) y
    ``ordinal`` lo identifica univocamente dentro del archivo (``documento`` en
    el contrato).
    """

    codigo: str
    ordinal: int
    pagina_inicio: int


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


# --------------------------------------------------------------------------
# Limpieza de texto (Issue #4)
#
# Los 5 casos de abajo NO son teoricos: cada uno se implemento porque se
# observo en el corpus de 9 polizas (ver ``scripts/test_parser.py`` para los
# asserts que los fijan) y no para cumplir la checklist de la issue.
# --------------------------------------------------------------------------

# (a) No imprimibles. NO incluye \n (0x0a) ni \t (0x09): el salto de pagina de
# PyMuPDF llega como \x0c y lo necesitamos para no pegar palabras entre paginas.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES_RE = re.compile(r"[ \t]{2,}")
_BLANK_RUN_RE = re.compile(r"\n{3,}")

# (b) Palabras duplicadas por la conversion PDF->texto ("de de"). Solo
# stopwords: unir cualquier palabra repetida seria destructivo ("diez diez" es
# legitimo).
_DUP_STOPWORDS_RE = re.compile(
    r"\b(de|del|la|el|los|las|un|una|unos|unas|y|o|en|con|por|para|es|son|que)\s+\1\b",
    re.IGNORECASE,
)

# (c) Guion colgante al final de linea ("... - \nLa"): se elimina el guion pero
# se conserva el salto. Solo aplica a guiones SOLOS al final de la linea, con
# blanco antes; por eso nunca toca un compuesto real ("alto-costo",
# "temporo-mandibulares", "pre-autorizacion") ni una palabra partida de verdad al
# final de linea.
_DANGLING_DASH_RE = re.compile(r"[ \t]*[-\u2013\u2014][ \t]*\n[ \t]*")

# Prefijo de cabecera SIN ancla de fin de linea, para cuando el PDF mete el
# cuerpo en la misma linea que la cabecera (``Artículo 15. Vigencia del seguro.
# El plazo de vigencia…``): en ese caso ``HDR_RE`` no matchea y hay que quitar
# solo el prefijo, no la linea entera.
_HDR_PREFIX_RE = re.compile(
    r"^\s*ART\s*[ÍI]CULO\s+(?:N[º°]?\s*\.?\s*)?\d{1,2}\s*[º°]?\s*[.:\-—–]?\s*",
    re.IGNORECASE,
)


def _strip_header(line: str) -> str:
    """Quita la cabecera ``ARTICULO N: TITULO`` del inicio de ``line``.

    Devuelve ``""`` si la linea es **solo** una cabecera (caso normal: la
    cabecera ocupa su linea y el cuerpo viene despues). Si el PDF puso el cuerpo
    en la misma linea, devuelve lo que quede tras el prefijo: se descarta tambien
    el titulo cuando viene en mayusculas, pero nunca se toca el cuerpo, porque
    borrarlo dejaba articulos vacios (asi se perdia ``POL320210063`` art. 15,
    que es de una sola linea).
    """
    m = _HDR_PREFIX_RE.match(line)
    if not m:
        return line
    resto = line[m.end():]
    # La linea era SOLO cabecera si lo que queda no parece una frase del cuerpo:
    # sin punto final, en mayusculas, o de menos de 3 palabras.
    if not resto or (resto == resto.upper() and len(resto) <= 70) or len(resto.split()) < 3:
        return ""
    return resto


def clean_article_text(raw: str) -> str:
    """Limpia el texto crudo de un articulo y devuelve su cuerpo.

    Casos cubiertos (orden importa):

    1. Normaliza ``\\r\\n`` / ``\\r`` a ``\\n``.
    2. Reemplaza no imprimibles por **espacio** (nunca los borra: borrarlos
       pegaria palabras de paginas distintas). Solo aparece en
       ``POL320200214`` art. 20 (domicilio), que ademas trae una linea
       100% basura binaria de una tabla: el texto queda inservible y eso es un
       problema del PDF de origen, no del parser.
    3. Elimina la cabecera ``ARTICULO N° X: ...`` (ya vive en la metadata).
    4. Colapsa espacios multiples, tabs y lineas en blanco (preserva una linea
       en blanco entre parrafos).
    5. Quita el guion colgante de fin de linea.
    6. Dedup de stopwords ("de de" -> "de").
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL_RE.sub(" ", text)

    lines = text.split("\n")
    lines[0] = _strip_header(lines[0]) if lines else ""
    if lines and not lines[0]:
        lines = lines[1:]

    text = "\n".join(_SPACES_RE.sub(" ", line).strip() for line in lines)
    text = _DANGLING_DASH_RE.sub("\n", text)
    text = _DUP_STOPWORDS_RE.sub(r"\1", text)
    return _BLANK_RUN_RE.sub("\n\n", text).strip()


# --------------------------------------------------------------------------
# Clasificacion de poliza (Issue #4)
# --------------------------------------------------------------------------

# Familia de producto -> keywords del titulo de portada (sin acentos).
# El orden importa: lo mas especifico va primero. Ojo con "enfermedades graves"
# antes que "accidente": ``POL320160108`` dice "SEGURO INDIVIDUAL DE ENFERMEDADES
# GRAVES" y matchearia la familia equivocada con la keyword suelta "enfermedad".
FAMILY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("covid", ("covid",)),
    ("enfermedades_graves", ("enfermedades graves",)),
    ("catastrofico_individual", ("catastrofico",)),
    ("alto_costo", ("alto costo",)),
    ("hospitalizacion_accidente_enfermedad", ("accidente",)),
    ("hospitalizacion_quirurgica_emergencia", ("quirurgic",)),
    ("colectivo_complementario", ("colectivo", "complementario")),
)
FALLBACK_FAMILY = "otra"


def poliza_ramo(codigo: str) -> str:
    """Ramo del molde a partir del codigo de deposito (``POL320130223`` -> ``salud``)."""
    return "salud" if codigo[3:5] == "32" else "accidentes"


def poliza_anio(codigo: str) -> str:
    """Anio del molde a partir del codigo de deposito (``POL320130223`` -> ``2013``)."""
    return "20" + codigo[6:8]


def titulo_portada(path: Path, pagina: int = 1) -> str:
    """Titulo de portada: lineas de la pagina ``pagina`` (1-based) hasta la primera
    cabecera de articulo o la marca de deposito.

    El default es la pagina 1, que es la portada del documento principal.
    """
    doc = pymupdf.open(path)
    text = page_text(doc, pagina - 1)
    doc.close()
    cover: list[str] = []
    for line in text.splitlines():
        if HDR_RE.match(line) or DEPOSITO_RE.search(line):
            break
        cover.append(line)
    return " ".join(cover).strip()


def subdocumentos(path: Path) -> list[Subdocumento]:
    """Detecta los documentos de deposito REALES dentro de un PDF del corpus.

    Recorre las paginas buscando la marca ``Incorporada al Depósito de Pólizas
    bajo el código POL…``. Cada aparicion abre un sub-documento nuevo con su
    propio codigo y ordinal (1-based).

    Devuelve siempre al menos un elemento: si el PDF no trae la marca (p. ej.
    una poliza emitida, no de deposito) se cae al nombre del archivo como codigo
    y todo el PDF es un unico sub-documento.
    """
    doc = pymupdf.open(path)
    found: list[Subdocumento] = []
    for pno in range(doc.page_count):
        for m in DEPOSITO_RE.finditer(page_text(doc, pno)):
            codigo = m.group(1).upper()
            if not found or found[-1].codigo != codigo:
                found.append(Subdocumento(codigo, len(found) + 1, pno + 1))
    doc.close()
    if not found:
        return [Subdocumento(path.stem.upper(), 1, 1)]
    # El primer sub-documento arranca en la pagina 1 aunque su marca se detecte
    # mas abajo: la portada siempre precede a la numeracion de articulos.
    found[0].pagina_inicio = 1
    return found


def subdocumento_de(subdocs: list[Subdocumento], pagina: int) -> Subdocumento:
    """Ultimo sub-documento cuyo inicio es ``<= pagina`` (los arts no empiezan antes)."""
    actual = subdocs[0]
    for sub in subdocs:
        if sub.pagina_inicio <= pagina:
            actual = sub
        else:
            break
    return actual


def poliza_familia(titulo: str, ramo: str) -> str:
    """Familia de producto del molde (``docs/ONTOLOGIA.md`` seccion 4.2).

    Para el ramo ``accidentes`` la familia es directa (solo hay una linea de
    accidentes personales en el corpus). Para salud se decide por keyword del
    titulo de portada, no del cuerpo: el cuerpo nombra "accidente" en articulos
    de cualquier poliza y contaminaria la clasificacion.

    Devuelve :data:`FALLBACK_FAMILY` si no hay match.
    """
    if ramo == "accidentes":
        return "accidentes_personales"
    low = unaccent(titulo)
    for familia, keywords in FAMILY_KEYWORDS:
        if any(unaccent(kw) in low for kw in keywords):
            return familia
    return FALLBACK_FAMILY


@dataclass
class SubdocumentoResuelto:
    """Un sub-documento con su metadata de clasificacion ya resuelta."""

    codigo: str
    ordinal: int
    pagina_inicio: int
    ramo: str
    anio: str
    familia: str
    titulo: str


def resolver_subdocumentos(path: Path) -> list[SubdocumentoResuelto]:
    """Detecta los sub-documentos de un PDF y resuelve su metadata.

    Un sub-documento arranca en cada marca ``Incorporada al Depósito de Pólizas
    bajo el código POL…``. El codigo asignado es el **real**, que puede diferir
    del nombre del archivo: en ``POL320190074.pdf`` desde la pag 16 el documento
    real es ``POL320130223``.

    Los articulos se asignan despues por :func:`asignar_documentos`, que ademas
    parte un sub-documento nuevo en cada reinicio de numeracion.
    """
    resueltos: list[SubdocumentoResuelto] = []
    for sub in subdocumentos(path):
        titulo = titulo_portada(path, sub.pagina_inicio)
        ramo = poliza_ramo(sub.codigo)
        resueltos.append(
            SubdocumentoResuelto(
                codigo=sub.codigo,
                ordinal=sub.ordinal,
                pagina_inicio=sub.pagina_inicio,
                ramo=ramo,
                anio=poliza_anio(sub.codigo),
                familia=poliza_familia(titulo, ramo),
                titulo=titulo,
            )
        )
    return resueltos


def asignar_documentos(
    arts: list[Article], subdocs: list[SubdocumentoResuelto]
) -> list[SubdocumentoResuelto]:
    """Devuelve un sub-documento POR ARTICULO, partiendo en los reinicios.

    Un sub-documento arranca cuando pasa cualquiera de estas dos señales:

    1. Una **marca de deposito** (codigo real distinto): el articulo pasa al
       sub-documento real que esa marca abre.
    2. Un **reinicio de numeracion** (el numero de articulo no crece respecto del
       anterior): las clausulas adicionales del Depósito reinician en 1 sin
       traer codigo propio (p. ej. ``POL320190074.pdf`` pag 11 "EXONERACIÓN DE
       PAGO DE PRIMAS…"). El sub-documento implicito **hereda** el codigo del
       anterior y sigue vigente para los articulos que le siguen, hasta que se
       cruce otra marca.

    Al final los ordinales se renumeran 1..n en orden de aparicion, para que
    ``documento`` sea estable y comparable entre archivos. La garantia que
    importa es que ``(poliza, documento, articulo)`` queda **unico**.
    """
    if not arts:
        return []

    segmentos: list[SubdocumentoResuelto] = []
    actual: SubdocumentoResuelto | None = None
    base_vigente: SubdocumentoResuelto | None = None
    numero_previo = 0

    for art in arts:
        base: SubdocumentoResuelto | None = None
        for sub in subdocs:
            if sub.pagina_inicio <= art.page:
                base = sub
            else:
                break
        cambio_base = base is not None and (
            base_vigente is None or base.ordinal != base_vigente.ordinal
        )
        if cambio_base:
            actual = base
            base_vigente = base  # type: ignore[assignment]
        elif actual is None:
            actual = base if base is not None else subdocs[0]
            base_vigente = actual
        if not cambio_base and art.number <= numero_previo:
            actual = SubdocumentoResuelto(
                codigo=actual.codigo,  # type: ignore[union-attr]
                ordinal=0,  # renumerado despues
                pagina_inicio=art.page,
                ramo=actual.ramo,  # type: ignore[union-attr]
                anio=actual.anio,  # type: ignore[union-attr]
                familia=actual.familia,  # type: ignore[union-attr]
                titulo=actual.titulo,  # type: ignore[union-attr]
            )
        segmentos.append(actual)  # type: ignore[arg-type]
        numero_previo = art.number

    # Renumerar en orden de aparicion: misma identidad -> mismo ordinal.
    ordinales: dict[int, int] = {}
    for sub in segmentos:
        if id(sub) not in ordinales:
            ordinales[id(sub)] = len(ordinales) + 1
    return [
        SubdocumentoResuelto(
            codigo=s.codigo,
            ordinal=ordinales[id(s)],
            pagina_inicio=s.pagina_inicio,
            ramo=s.ramo,
            anio=s.anio,
            familia=s.familia,
            titulo=s.titulo,
        )
        for s in segmentos
    ]


def parse_corpus(pdf_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """Parsea el corpus de ``pdf_dir`` a registros de articulo.

    Un registro por articulo, con las claves de ``docs/CONTRACTS.md`` seccion 1.1:
    ``poliza``, ``documento``, ``ramo``, ``anio``, ``familia``, ``articulo``,
    ``titulo``, ``canonico``, ``pagina``, ``chars`` y ``texto``.

    - ``poliza`` es el **codigo de deposito real** del sub-documento, que puede
      diferir del nombre del PDF (``POL320190074.pdf`` contiene ``POL320130223``).
    - ``documento`` es el ordinal del sub-documento dentro del PDF (1..n).
    - ``(poliza, documento, articulo)`` es **unico**: es la clave que consume el
      ``point_id`` de ``app/rag/indexer.py``. Con ``(poliza, articulo)`` NO lo es,
      porque los PDFs traen varios documentos pegados y la numeracion reinicia.
    - ``chars`` es SIEMPRE ``len(texto)`` del texto ya limpio (asi el vector de
      features y el payload no pueden desincronizarse).
    """
    directory = Path(pdf_dir) if pdf_dir is not None else RAW_PDFS_DIR
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.pdf")):
        subdocs = resolver_subdocumentos(path)
        arts = extract_articles(path)
        asignados = asignar_documentos(arts, subdocs)
        warned: set[str] = set()
        doc = pymupdf.open(path)
        try:
            for article, sub in zip(arts, asignados, strict=True):
                if sub.familia == FALLBACK_FAMILY and sub.codigo not in warned:
                    warned.add(sub.codigo)
                    warnings.warn(
                        f"{path.name} doc{sub.ordinal} ({sub.codigo}): sin match en "
                        f"FAMILY_KEYWORDS, familia={FALLBACK_FAMILY}. Revisar el titulo "
                        "de portada o agregar la keyword.",
                        stacklevel=2,
                    )
                texto = clean_article_text(segment_text(doc, article))
                records.append(
                    {
                        "poliza": sub.codigo,
                        "documento": sub.ordinal,
                        "ramo": sub.ramo,
                        "anio": sub.anio,
                        "familia": sub.familia,
                        "articulo": article.number,
                        "titulo": article.title,
                        "canonico": article.canonical,
                        "pagina": article.page,
                        "chars": len(texto),
                        "texto": texto,
                    }
                )
        finally:
            doc.close()
    return records
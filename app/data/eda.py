"""EDA del corpus de polizas de seguros (Issue #3).

Analiza los PDFs descargados en ``data/raw_pdfs`` y genera:

* ``docs/eda/polizas_estructura.csv`` y ``.json``: matriz poliza x articulo
  (numero, titulo, titulo canonico, pagina, cantidad de caracteres).
* ``docs/eda/cobertura_articulo2.md``: deep-dive del Artículo 2 (Cobertura)
  de las polizas de salud.
* ``docs/EDA.md``: reporte final con corpus, esqueleto estandar, hallazgos
  y recomendaciones para las issues #4, #7 y #9.

Uso:
    uv run python -m app.data.eda
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pymupdf

from app.paths import PROJECT_ROOT

RAW_PDFS_DIR = PROJECT_ROOT / "data" / "raw_pdfs"
REPORT_PATH = PROJECT_ROOT / "docs" / "EDA.md"
EDA_DIR = PROJECT_ROOT / "docs" / "eda"
STRUCTURE_CSV = EDA_DIR / "polizas_estructura.csv"
STRUCTURE_JSON = EDA_DIR / "polizas_estructura.json"
COBERTURA_MD = EDA_DIR / "cobertura_articulo2.md"

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


def corpus_profile() -> pd.DataFrame:
    """Genera la tabla de perfil para cada poliza."""
    rows: list[dict[str, Any]] = []
    for path in sorted(RAW_PDFS_DIR.glob("*.pdf")):
        doc = pymupdf.open(path)
        pages, images, chars, tables = doc.page_count, 0, 0, 0
        n_arts = len(extract_articles(path))
        for page in doc:
            chars += len(page.get_text())
            images += len(page.get_images())
            tables += len(page.find_tables().tables)
        code = path.stem
        cod_ramo = code[3:5]
        head = page_text(doc, 0).splitlines()
        rows.append(
            {
                "poliza": code,
                "ramo": "salud" if cod_ramo == "32" else "accidentes",
                "año": f"20{code[6:8]}",
                "paginas": pages,
                "chars": chars,
                "tablas": tables,
                "imagenes": images,
                "articulos": n_arts,
                "productor": (doc.metadata.get("producer") or "").strip(),
                "titulo_portada": head[0][:64] if head else "",
            }
        )
        doc.close()
    return pd.DataFrame(rows)


def build_structure() -> list[dict[str, Any]]:
    """Extrae la estructura articulo x poliza de todo el corpus."""
    records: list[dict[str, Any]] = []
    for path in sorted(RAW_PDFS_DIR.glob("*.pdf")):
        for a in extract_articles(path):
            records.append(
                {
                    "poliza": path.stem,
                    "articulo": a.number,
                    "titulo": a.title,
                    "canonico": a.canonical,
                    "pagina": a.page,
                    "chars": a.chars,
                }
            )
    return records


def cobertura_stats(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-dive del Articulo 2 (Cobertura) en polizas de salud."""
    rows: list[dict[str, Any]] = []
    for path in sorted(RAW_PDFS_DIR.glob("*.pdf")):
        if not path.stem.startswith("POL32"):
            continue
        doc = pymupdf.open(path)
        cover = next((a for a in extract_articles(path) if a.canonical == "cobertura"), None)
        if cover is None:
            doc.close()
            continue
        text = segment_text(doc, cover)
        low = unaccent(text)
        pct_matches = re.findall(r"\b\d{1,3}(?:[.,]\d{1,3})?\s*%", text)[:8]
        rows.append(
            {
                "poliza": path.stem,
                "chars": len(text),
                "condiciones_particulares": "condiciones particulares" in low,
                "carencia": "carencia" in low,
                "uf": bool(re.search(r"\bUF\b", text)),
                "porcentajes": "; ".join(pct_matches) or "-",
                "listas_letra": len(re.findall(r"^\s*[A-ZÁÉÍÓÚÑ]\s*[.:)\-]", text, re.M)),
                "listas_numeral": len(re.findall(r"^\s*\d{1,2}\s*[.:)\-]", text, re.M)),
                "incipit": re.sub(r"\s+", " ", text)[:120],
            }
        )
        doc.close()
    return rows


def md_table(df: pd.DataFrame) -> str:
    """Renderiza un DataFrame como tabla Markdown (sin dependencias extra)."""
    if df.empty:
        return "_sin datos_"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v).replace("|", "/").replace("\n", " ") for v in row) + " |")
    return "\n".join(lines)


def matriz_esqueleto(records: list[dict[str, Any]]) -> str:
    """Matriz poliza x posicion de cada articulo canonico."""
    df = pd.DataFrame(records)
    pols = sorted(df["poliza"].unique())
    widths = {p: df.loc[df["poliza"] == p, "canonico"].tolist() for p in pols}
    max_w = max(len(v) for v in widths.values())
    lines = ["| pos | " + " | ".join(p for p in pols) + " |"]
    lines.append("| --- | " + " | ".join(["---"] * len(pols)) + " |")
    for i in range(max_w):
        lines.append("| " + str(i + 1) + " | " + " | ".join(widths[p][i] if i < len(widths[p]) else "—" for p in pols) + " |")
    return "\n".join(lines)


def render_report(
    profile: pd.DataFrame,
    records: list[dict[str, Any]],
    cover: list[dict[str, Any]],
) -> str:
    """Arma el reporte final ``docs/EDA.md``."""
    size = pd.DataFrame(records)["chars"]
    stats = f"min **{int(size.min())}** · mediana **{int(size.median())}** · max **{int(size.max())}** (n={len(size)})"
    return f"""# EDA · Corpus de Pólizas (Issue #3)

Reporte generado con `uv run python -m app.data.eda`.
- PDFs de origen: `data/raw_pdfs/` (no versionados).
- Script: `app/data/eda.py` · estructura por póliza: `docs/eda/polizas_estructura.csv` + `.json` · deep-dive del Artículo 2: `docs/eda/cobertura_articulo2.md`.

## 1. Perfil del corpus

{md_table(profile)}

## 2. Esqueleto estándar de artículos

Las pólizas comparten el mismo esqueleto de artículos (reglas → cobertura →
definiciones → … → cláusulas adicionales). Matriz de posiciones:

{matriz_esqueleto(records)}

## 3. Deep-dive · Artículo 2: Cobertura (pólizas de salud)

{md_table(pd.DataFrame(cover))}

## 4. Tamaño de los artículos (insumo #7)

Longitud por artículo (chars): {stats}

## 5. Hallazgos

- Cabeceras `ARTÍCULO` consistentes entre pólizas, con variantes de formato
  (`°`/`º`, `Nº`, `:` vs `.`, tilde opcional) → normalizables por regex.
- `pymupdf.find_tables()` detecta **0 tablas**: planes/saldos están en prosa
  corrida; `POL320200214` aporta 4 imágenes (logos/sellos).
- El Artículo 2 de salud es prosa legal densa: referencias constantes a
  "Condiciones Particulares", porcentajes de reembolso, carencia y UF.
- Casos borde: `POL320190074` (dos series de artículos 1..N anidadas dentro
  de Cláusulas Adicionales) y `POL320210063` (póliza COVID con sintaxis de
  cabecera distinta, ~2 artículos detectados).

## 6. Recomendaciones para el pipeline

- **#4 (parser):** segmentar por cabecera `ARTÍCULO` normalizada (sin
  acentos, soportando `Nº`/`°`/`:`); tratar serie anidada y COVID aparte.
- **#7 (chunking):** el "artículo" es la unidad natural; el tamaño base de
  chunk se puede calibrar contra la mediana por artículo (ver sección 4).
- **#9 (metadata):** cada chunk debería llevar `poliza`, `ramo`, `año`,
  `articulo`, `titulo_canonico` y `pagina` → permite filtrar por tipo de
  cláusula (cobertura, exclusiones, definiciones…).

## 7. Metodología

Segmentación por regex `ARTÍCULO Nº NN: TÍTULO` tolerante a variantes; cada
artículo = texto entre su cabecera y la siguiente. Títulos mapeados a claves
canónicas por keywords. Deep-dive del Artículo 2 en pólizas ramo 32 (salud).
Solo se versionan este reporte y las tablas de estructura (los PDFs no).
"""


def main() -> None:
    EDA_DIR.mkdir(parents=True, exist_ok=True)
    print("Perfil del corpus...")
    profile = corpus_profile()
    print("Estructura de artículos...")
    records = build_structure()
    pd.DataFrame(records).to_csv(STRUCTURE_CSV, index=False)
    STRUCTURE_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Deep-dive Artículo 2 (salud)...")
    cover = cobertura_stats(records)
    cover_df = pd.DataFrame(cover)
    COBERTURA_MD.write_text(cover_df.to_string(index=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render_report(profile, records, cover), encoding="utf-8")
    print("Listo:")
    print(f"  {REPORT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"  {STRUCTURE_CSV.relative_to(PROJECT_ROOT)}")
    print(f"  {STRUCTURE_JSON.relative_to(PROJECT_ROOT)}")
    print(f"  {COBERTURA_MD.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
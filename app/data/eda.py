"""EDA del corpus de polizas de seguros (Issue #3).

Analiza los PDFs descargados en ``data/raw_pdfs`` y genera:

* ``docs/eda/polizas_estructura.csv`` y ``.json``: matriz poliza x articulo
  (numero, titulo, titulo canonico, pagina, cantidad de caracteres).
* ``docs/eda/cobertura_articulo2.md``: deep-dive del Articulo 2 (Cobertura)
  de las polizas de salud.
* ``docs/EDA.md``: reporte final con corpus, esqueleto estandar, hallazgos
  y recomendaciones para las issues #4, #7 y #9.

El parsing de los PDFs (segmentacion en articulos) vive en
``app/data/parser.py``; este modulo importa esas funciones y produce
los reportes.

Uso:
    uv run python -m app.data.eda
"""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
import pymupdf

from app.data.parser import RAW_PDFS_DIR, extract_articles, page_text, parse_corpus, segment_text, unaccent
from app.paths import COBERTURA_MD, EDA_DIR, PROJECT_ROOT, REPORT_PATH, STRUCTURE_CSV, STRUCTURE_JSON


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
    """Extrae la estructura articulo x poliza de todo el corpus.

    Reusa ``app.data.parser`` (no reimplementa parsing): ``poliza`` es el codigo
    de deposito REAL y ``documento`` el sub-documento, porque los PDFs traen
    varias polizas pegadas y la numeracion de articulos reinicia en cada una.
    """
    return [
        {
            "poliza": r["poliza"],
            "documento": r["documento"],
            "articulo": r["articulo"],
            "titulo": r["titulo"],
            "canonico": r["canonico"],
            "pagina": r["pagina"],
            "chars": r["chars"],
        }
        for r in parse_corpus(RAW_PDFS_DIR)
    ]


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
    """Matriz poliza x posicion de cada articulo canonico.

    Una columna por **codigo de deposito**, no por PDF: como un PDF puede traer
    varias polizas pegadas (``POL320130223`` esta tanto en su archivo como dentro
    de ``POL320190074.pdf``), se muestran los articulos del **primer**
    sub-documento de cada codigo. Para el detalle completo por sub-documento
    esta ``docs/eda/polizas_estructura.csv``.
    """
    df = pd.DataFrame(records)
    primeros = df.sort_values(["poliza", "documento"]).groupby("poliza", as_index=False).first()
    pols = sorted(df["poliza"].unique())
    widths = {p: primeros.loc[primeros["poliza"] == p, "canonico"].tolist() for p in pols}
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
definiciones → … → cláusulas adicionales). Matriz de posiciones, **una columna
por código de depósito** (el corpus son 9 PDFs pero 10 códigos reales, y
`POL320130223` aparece tanto en su archivo como dentro de `POL320190074.pdf`; cada
columna muestra el primer sub-documento del código). Detalle por sub-documento:
`docs/eda/polizas_estructura.csv`.

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
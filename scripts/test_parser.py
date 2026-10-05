"""Tests de extraccion y limpieza de articulos (Issue #4).

 corre: ``uv run python scripts/test_parser.py``
"""

from __future__ import annotations

import re
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.parser import (  # noqa: E402
    FALLBACK_FAMILY,
    HDR_RE,
    clean_article_text,
    extract_articles,
    parse_corpus,
    poliza_anio,
    poliza_ramo,
    resolver_subdocumentos,
)
from app.paths import RAW_PDFS_DIR, STRUCTURE_CSV  # noqa: E402

ESPERADOS = 227

# codigo real -> familia esperada (codigos REALES de deposito, no nombres de archivo)
FAMILIAS_ESPERADAS = {
    "POL120190177": "accidentes_personales",
    "POL320130223": "colectivo_complementario",
    "POL320150503": "hospitalizacion_accidente_enfermedad",
    "POL320160108": "enfermedades_graves",
    "POL320180100": "hospitalizacion_quirurgica_emergencia",
    "POL320190074": "alto_costo",
    "POL320200071": "catastrofico_individual",
    "POL320200214": "alto_costo",
    "POL320210063": "covid",
    "POL320210210": "alto_costo",
}

# articulos por (codigo real) en todo el corpus, incluyendo los sub-documentos
# clonado que vienen pegados dentro de otros PDFs.
POR_POLIZA = {
    "POL120190177": 23,
    "POL320130223": 50,
    "POL320150503": 23,
    "POL320160108": 20,
    "POL320180100": 23,
    "POL320190074": 21,
    "POL320200071": 20,
    "POL320200214": 20,
    "POL320210063": 12,
    "POL320210210": 15,
}

fallos: list[str] = []
ok = 0


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    global ok
    if condicion:
        ok += 1
        print(f"  ok   {nombre}")
    else:
        fallos.append(nombre)
        print(f"  FAIL {nombre}" + (f" -> {detalle}" if detalle else ""))


def main() -> int:
    import csv

    print("== Contrato ==")
    records = parse_corpus(RAW_PDFS_DIR)
    check(f"{ESPERADOS} registros", len(records) == ESPERADOS, f"hay {len(records)}")

    claves = {
        "poliza", "documento", "ramo", "anio", "familia", "articulo",
        "titulo", "canonico", "pagina", "chars", "texto",
    }
    check("todas las claves del contrato", all(claves <= set(r) for r in records))
    check("chars == len(texto)", all(r["chars"] == len(r["texto"]) for r in records))
    check(
        "articulo, pagina y documento son int",
        all(isinstance(r["articulo"], int) and isinstance(r["pagina"], int) and isinstance(r["documento"], int) for r in records),
    )
    check("sin texto vacio (salvo el que ver abajo)",
          sum(1 for r in records if not r["texto"].strip()) == 0,
          f"vacias: {[(r['poliza'], r['articulo']) for r in records if not r['texto'].strip()]}")
    check("sin cabecera ARTICULO al inicio del cuerpo", all(not HDR_RE.match(r["texto"]) for r in records))

    print("\n== Unicidad: la clave que consume el point_id de #9 ==")
    clave = Counter((r["poliza"], r["documento"], r["articulo"]) for r in records)
    check("(poliza, documento, articulo) UNICO", len(clave) == ESPERADOS,
          f"{len(clave)} unicos de {ESPERADOS}")
    viejo = Counter((r["poliza"], r["articulo"]) for r in records)
    check("el contrato viejo (poliza, articulo) colisiona (motivo del fix)",
          len(viejo) < ESPERADOS, f"{len(viejo)} unicos")
    ids_nuevo = {uuid.uuid5(uuid.NAMESPACE_URL, f"{r['poliza']}|{r['documento']}|{r['articulo']}|0") for r in records}
    check("point_id con documento: sin colisiones", len(ids_nuevo) == ESPERADOS, f"{len(ids_nuevo)}/{ESPERADOS}")
    ids_viejo = {uuid.uuid5(uuid.NAMESPACE_URL, f"{r['poliza']}|{r['articulo']}|0") for r in records}
    check("point_id sin documento: pierdo articulos (por eso el fix)",
          len(ids_viejo) < ESPERADOS, f"{len(ids_viejo)}/{ESPERADOS}")

    print("\n== Consistencia con la matriz EDA ==")
    with STRUCTURE_CSV.open(encoding="utf-8") as fh:
        eda = {(r["poliza"], int(r["documento"]), int(r["articulo"]), r["canonico"]) for r in csv.DictReader(fh)}
    check("matriz EDA tiene 227 filas unicas", len(eda) == ESPERADOS, f"{len(eda)}")
    parser_set = {(r["poliza"], r["documento"], r["articulo"], r["canonico"]) for r in records}
    check("(poliza, documento, articulo, canonico) identico a la matriz EDA",
          parser_set == eda, f"diff: {sorted(parser_set ^ eda)[:5]}")

    print("\n== Clasificacion (ramo / anio / familia) ==")
    check("sin fallback de familia", all(r["familia"] != FALLBACK_FAMILY for r in records))
    for code, fam in FAMILIAS_ESPERADAS.items():
        rows = [r for r in records if r["poliza"] == code]
        check(f"{code}: familia={fam}", rows and all(r["familia"] == fam for r in rows),
              f"obtenidas: {sorted({r['familia'] for r in rows})}")
    check("10 codigos de deposito reales", len({r["poliza"] for r in records}) == 10,
          f"{sorted({r['poliza'] for r in records})}")
    check("POL320160108 (sub-doc, sin archivo propio) presente",
          len([r for r in records if r["poliza"] == "POL320160108"]) == 20)
    check("ramo por codigo[3:5]",
          all(r["ramo"] == ("salud" if r["poliza"][3:5] == "32" else "accidentes") for r in records))
    check("anio desde codigo[6:8]", all(r["anio"] == "20" + r["poliza"][6:8] for r in records))
    check("POL320130223 -> 2013", poliza_anio("POL320130223") == "2013")
    check("cobertura por poliza", Counter(r["poliza"] for r in records) == Counter(POR_POLIZA),
          f"{Counter(r['poliza'] for r in records)}")

    print("\n== Limpieza: caso (a) no imprimibles ==")
    sucios = [r for r in records if any(ch in r["texto"] for ch in "\x00\x0b\x0c\x0e\x08")]
    check("0 articulos con no imprimibles", not sucios, f"{len(sucios)} sucios")
    art20 = next(r for r in records if r["poliza"] == "POL320200214" and r["articulo"] == 20)
    check("POL320200214 art.20 conserva el texto legible", art20["chars"] > 400,
          f"chars={art20['chars']}")
    check("POL320200214 art.20: la basura binaria del PDF queda como ruido, "
          "pero el texto legible sobrevive", "domicilio especial" in art20["texto"])

    print("\n== Limpieza: caso (b) lineas vacias y espacios ==")
    check("sin 3+ saltos seguidos", all("\n\n\n" not in r["texto"] for r in records))
    check("sin espacios multiples", not any("  " in line for r in records for line in r["texto"].split("\n")))
    check("sin lineas solo-espacios", not any(line != line.strip() for r in records for line in r["texto"].split("\n")))

    print("\n== Limpieza: caso (c) guiones de fin de linea ==")
    colgantes = [r for r in records if any(line.rstrip().endswith("-") for line in r["texto"].split("\n"))]
    check("0 guiones colgantes", not colgantes, f"{len(colgantes)}")
    compuestos = ["temporo-mandibulares", "dermo-cosméticos", "COVID-19", "temporomandibular", "auto-provocadas"]
    faltan = [c for c in compuestos if not any(c in r["texto"] for r in records)]
    check("compuestos reales preservados", not faltan, f"faltan {faltan}")

    print("\n== Limpieza: caso (d) palabras duplicadas ==")
    dup = re.compile(r"\b(de|del|la|el|los|las|un|una|y|en|que|con|por|para)\s+\1\b", re.IGNORECASE)
    con_dup = [r for r in records if dup.search(r["texto"])]
    check("sin stopwords duplicadas", not con_dup,
          f"{len(con_dup)} arts, ej {[(r['poliza'], r['articulo']) for r in con_dup[:3]]}")
    check("'deducible' no se parte en 'de'+'de' (borde del dedup)",
          not dup.search("un tipo de deducible, la compañía"))
    check("'diez diez' legitimo no se toca",
          clean_article_text("La suma de diez diez es veinte.") == "La suma de diez diez es veinte.")

    print("\n== Casos sinteticos de clean_article_text ==")
    check("normaliza CRLF", clean_article_text("a\r\nb\rc") == "a\nb\nc")
    check("no imprimible -> espacio (no borra)", clean_article_text("antes\x0cdespues") == "antes despues")
    check("quita cabecera de articulo", clean_article_text("ARTÍCULO N° 2: COBERTURA\ncuerpo") == "cuerpo")
    check("colapsa espacios y tabs", clean_article_text("a   \t  b") == "a b")
    check("quita guion colgante y conserva salto", clean_article_text("lista -\nLa siguiente") == "lista\nLa siguiente")
    check("no toca compuesto con guion", "temporo-mandibulares" in clean_article_text("x temporo-mandibulares\ny"))
    check("dedup stopword", clean_article_text("caso de de prueba") == "caso de prueba")
    check("texto vacio -> vacio", clean_article_text("   \n  \n") == "")
    check("no toca URL", "treasury.gov" in next(r["texto"] for r in records if r["poliza"] == "POL320200214" and r["articulo"] == 4))

    print("\n== Bordes ==")
    check("POL320210063 (COVID, cabecera distinta): 12 articulos",
          len([r for r in records if r["poliza"] == "POL320210063"]) == 12)
    check("POL320120190177 (ramo no-32) presente", len([r for r in records if r["poliza"] == "POL120190177"]) == 23)
    check("subdocumentos detectados en POL320190074.pdf",
          len(resolver_subdocumentos(RAW_PDFS_DIR / "POL320190074.pdf")) == 2)
    check("subdocumentos detectados en POL320200071.pdf",
          len(resolver_subdocumentos(RAW_PDFS_DIR / "POL320200071.pdf")) == 2)
    check("POL320150503.pdf es un solo documento",
          len(resolver_subdocumentos(RAW_PDFS_DIR / "POL320150503.pdf")) == 1)

    print(f"\n{'=' * 60}")
    if fallos:
        print(f"{ok} ok, {len(fallos)} FAIL: {fallos}")
        return 1
    print(f"{ok} ok, 0 fallos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Genera ``data/processed/articulos.jsonl`` desde los PDFs crudos (Issue #4).

Espejo de ``app/rag/indexer.py``: logica en ``app/data/parser.py``, aqui solo
la capa CLI (lectura de argumentos, escritura y resumen).

Uso:

    uv run python -m app.data.build_articulos
    uv run python -m app.data.build_articulos --pdf-dir data/raw_pdfs --out data/processed/articulos.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.data.parser import parse_corpus
from app.paths import ARTICULOS_JSONL, RAW_PDFS_DIR, ensure_data_dirs


def write_jsonl(records: list[dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_summary(records: list[dict[str, Any]]) -> str:
    polizas = Counter(r["poliza"] for r in records)
    familias = Counter(r["familia"] for r in records)
    canonicos = Counter(r["canonico"] for r in records)
    chars = sum(r["chars"] for r in records)

    lines = [
        f"{len(records)} articulos de {len(polizas)} polizas | {chars:,} chars de texto",
        "",
        "Por poliza:",
        *(f"  {p}  {n:>3} articulos" for p, n in sorted(polizas.items())),
        "",
        "Por familia:",
        *(f"  {f:<40} {n:>3} articulos" for f, n in sorted(familias.items())),
        "",
        f"Canonicos distintos: {len(canonicos)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf-dir", type=Path, default=RAW_PDFS_DIR, help="directorio de PDFs")
    ap.add_argument("--out", type=Path, default=ARTICULOS_JSONL, help="salida JSONL")
    args = ap.parse_args(argv)

    ensure_data_dirs()
    records = parse_corpus(args.pdf_dir)
    write_jsonl(records, args.out)
    print(build_summary(records))
    print(f"\nEscrito: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""CLI para recombinación DEM demo v0 (#36).

Permite ejecutar la recombinación desde la terminal:
    uv run python -m app.generation.dem --molde POL320200071 --perfil '{"edad":"30-40",...}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.generation.dem import generar_dem


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

    try:
        payload, pdf_path = generar_dem(
            molde=args.molde,
            perfil=perfil,
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

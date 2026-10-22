"""Mide la distribucion de scores de ``search()`` para fijar el hard gate.

Corre las queries de ``QUERIES`` contra la coleccion indexada (requiere Qdrant
+ Ollama arriba) y vuelca el detalle crudo a ``data/processed/`` (gitignored):
``umbral_raw.json`` en modo denso, ``umbral_raw_hybrid.json`` en modo hibrido
(#42) y ``umbral_raw_hybrid_sin_piso.json`` para la fusion RRF sin piso
semantico. El resumen numerico (distribucion del top-1 por clase y barrido de
umbrales) se imprime en consola y la interpretacion vive en
``docs/umbral_score.md``.

Uso:

    uv run python scripts/analisis_umbral.py                    # RETRIEVAL_MODE (default dense)
    uv run python scripts/analisis_umbral.py --mode hybrid      # UMBRAL_SCORE_HYBRID
    uv run python scripts/analisis_umbral.py --mode hybrid --sin-piso
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paths import PROCESSED_DIR  # noqa: E402
from app.rag.bm25 import get_bm25_index  # noqa: E402
from app.rag.config import SUPPORTED_RETRIEVAL_MODES, get_settings  # noqa: E402
from app.rag.vectordb import _get_search_store, hybrid_search, search  # noqa: E402

OUT = PROCESSED_DIR / "umbral_raw.json"
CLASES = ("dominio", "adyacente", "ajena")

# Umbrales que se barren por modo: coseno en denso, RRF normalizado en hibrido.
SWEEP: dict[str, tuple[float, ...]] = {
    "dense": (0.50, 0.55, 0.58, 0.60, 0.62, 0.64, 0.66),
    "hybrid": (0.0, 0.30, 0.40, 0.45, 0.50, 0.60, 0.80, 0.90),
}

# Clase "dominio": pregunta contestable con las polizas, con el canonico que
# deberia ganar (ground truth). Clase "adyacente": del rubro salud/seguros pero
# NO contestable con el corpus. Clase "ajena": sin relacion con seguros.
QUERIES: list[dict] = [
    # --- dominio (relevante, con ground truth por canonico) ---
    {"clase": "dominio", "q": "¿Qué gastos médicos me reembolsa el seguro?", "canonico": "cobertura"},
    {"clase": "dominio", "q": "¿Cuánto tengo que esperar para que me cubran un parto?", "canonico": "carencia"},
    {"clase": "dominio", "q": "¿Qué operaciones estéticas no cubre la póliza?", "canonico": "exclusiones"},
    {"clase": "dominio", "q": "¿Dentro de qué plazo debo denunciar un siniestro?", "canonico": "denuncia de siniestro"},
    {"clase": "dominio", "q": "¿Cómo se calcula el monto que me van a reembolsar?", "canonico": "calculo de gastos"},
    {"clase": "dominio", "q": "¿Qué pasa si no pago la prima a tiempo?", "canonico": "primas"},
    {"clase": "dominio", "q": "¿A quién se le paga la indemnización si el asegurado muere?", "canonico": "beneficiarios"},
    {"clase": "dominio", "q": "¿Cuánto dura vigente el contrato de seguro?", "canonico": "vigencia"},
    {"clase": "dominio", "q": "¿Puede la compañía darme por terminada la póliza?", "canonico": "terminacion"},
    {"clase": "dominio", "q": "¿Qué obligaciones tiene el asegurado con la compañía?", "canonico": "obligaciones"},
    {"clase": "dominio", "q": "¿Qué pasa si el asegurado tiene otra póliza que cubre lo mismo?", "canonico": "otros seguros"},
    {"clase": "dominio", "q": "¿Me pagan dos veces si tengo dos seguros?", "canonico": "duplicacion de beneficios"},
    {"clase": "dominio", "q": "¿Cuál es la unidad monetaria en que está pactada la póliza?", "canonico": "unidad del contrato"},
    {"clase": "dominio", "q": "¿Qué debo hacer si quiero agregar a mi hijo a la póliza?", "canonico": "incorporacion"},
    {"clase": "dominio", "q": "¿Puedo retractarme después de firmar el contrato?", "canonico": "retracto"},
    {"clase": "dominio", "q": "¿Se puede rehabilitar la póliza después de un impago?", "canonico": "rehabilitacion"},
    {"clase": "dominio", "q": "¿Hay tope máximo de gastos que me reembolsan en el año?", "canonico": "monto maximo de reembolso"},
    {"clase": "dominio", "q": "¿Qué gastos no son reembolsables según el contrato?", "canonico": "exclusiones"},
    {"clase": "dominio", "q": "¿Qué pasa si mi estado de salud empeora y no lo aviso?", "canonico": "agravacion del riesgo"},
    {"clase": "dominio", "q": "¿Cómo se notifican las comunicaciones entre las partes?", "canonico": "comunicaciones"},
    {"clase": "dominio", "q": "¿Dónde debo vivir para que aplique el seguro?", "canonico": "pais de residencia"},
    {"clase": "dominio", "q": "¿Qué moneda se usa para calcular y pagar?", "canonico": "unidad del contrato"},
    {"clase": "dominio", "q": "¿Cuándo empieza a correr la cobertura para un asegurado nuevo?", "canonico": "cobertura"},
    {"clase": "dominio", "q": "¿Qué significan los términos usados en la póliza?", "canonico": "definiciones"},
    {"clase": "dominio", "q": "¿Qué pasa si el asegurado no dice toda la verdad al contratar?", "canonico": "declaraciones"},
    {"clase": "dominio", "q": "¿El seguro se hace cargo de los impuestos que genera?", "canonico": "impuestos"},
    # --- adyacente: del rubro, pero injuntable con el corpus ---
    {"clase": "adyacente", "q": "¿Cuál es el color del auto del asegurado?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué número de teléfono tengo que marcar para el servicio de urgencias?", "canonico": None},
    {"clase": "adyacente", "q": "¿Dónde queda la sucursal más cercana de la compañía?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuánto cuesta sacar turno con el cardiólogo que recomiendan?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuál es el nombre del médico de cabecera asignado a mi plan?", "canonico": None},
    {"clase": "adyacente", "q": "¿La póliza cubre a mi perro?", "canonico": None},
    {"clase": "adyacente", "q": "¿Me hacen descuento si pago todo el año por adelantado?", "canonico": None},
    {"clase": "adyacente", "q": "¿Puedo pagar con tarjeta de crédito americana?", "canonico": None},
    {"clase": "adyacente", "q": "¿Cuánto tarda la ambulancia?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué pasa con mi cobertura si me cambio de trabajo?", "canonico": None},
    {"clase": "adyacente", "q": "¿El seguro cubre los gimnasios?", "canonico": None},
    {"clase": "adyacente", "q": "¿Qué médico de urgencias atiende los domingos de madrugada?", "canonico": None},
    # --- ajena: sin relacion ---
    {"clase": "ajena", "q": "¿Quién ganó el mundial de 2022?", "canonico": None},
    {"clase": "ajena", "q": "¿Cómo se prepara un pan casero?", "canonico": None},
    {"clase": "ajena", "q": "¿Cuál es la capital de Australia?", "canonico": None},
    {"clase": "ajena", "q": "¿Qué es un agujero negro?", "canonico": None},
    {"clase": "ajena", "q": "¿Cuántos planetas hay en el sistema solar?", "canonico": None},
    {"clase": "ajena", "q": "¿Quién escribió Cien años de soledad?", "canonico": None},
]


SearchFn = Callable[[str], list[dict[str, Any]]]


def output_path(mode: str, sin_piso: bool = False) -> Path:
    """Archivo crudo por modo; el denso conserva el nombre historico."""
    if mode == "dense":
        return OUT
    return PROCESSED_DIR / f"umbral_raw_{mode}{'_sin_piso' if sin_piso else ''}.json"


def measure(queries: Sequence[dict[str, Any]], search_fn: SearchFn) -> list[dict[str, Any]]:
    """Corre ``search_fn`` sobre cada query y arma un registro por pregunta.

    Una pregunta sin hits (posible en hibrido: el piso semantico descarta todo)
    queda con ``scores=[]`` y ``top1=None``.
    """
    records: list[dict[str, Any]] = []
    for spec in queries:
        hits = search_fn(spec["q"])
        top = hits[0] if hits else None
        records.append(
            {
                "clase": spec["clase"],
                "q": spec["q"],
                "canonico_esperado": spec["canonico"],
                "scores": [h["score"] for h in hits],
                "top5_canonicos": [h["metadata"]["titulo_canonico"] for h in hits],
                "top1": (
                    {
                        "canonico": top["metadata"]["titulo_canonico"],
                        "poliza": top["metadata"]["poliza"],
                        "articulo": top["metadata"]["articulo"],
                    }
                    if top
                    else None
                ),
            }
        )
    return records


def top1(record: dict[str, Any]) -> float:
    """Score del top-1; ``0.0`` si la busqueda no devolvio nada."""
    return record["scores"][0] if record["scores"] else 0.0


def stats(vals: list[float]) -> str:
    """Resumen ``n/min/p10/p50/p90/max`` (percentil por indice, sin interpolar)."""
    if not vals:
        return "—"
    v = sorted(vals)
    n = len(v)

    def p(q: float) -> float:
        return v[min(n - 1, max(0, int(q * (n - 1))))]

    return (
        f"n={n:>2} min={v[0]:.3f} p10={p(.1):.3f} p50={p(.5):.3f} "
        f"p90={p(.9):.3f} max={v[-1]:.3f}"
    )


def sweep(records: list[dict[str, Any]], umbral: float) -> dict[str, int]:
    """Efecto de un umbral sobre el top-1 de cada clase.

    Returns:
        ``dominio_pasa`` (preguntas de dominio con top-1 >= umbral),
        ``dominio_hit1`` (de esas, cuantas con el canonico esperado en top-1),
        ``adyacente_bloquea`` y ``ajena_bloquea`` (top-1 < umbral o sin hits).
    """
    def bloquea(r: dict[str, Any]) -> bool:
        return not r["scores"] or top1(r) < umbral

    dom = [r for r in records if r["clase"] == "dominio"]
    pasa = [r for r in dom if not bloquea(r)]
    return {
        "dominio_pasa": len(pasa),
        "dominio_hit1": sum(
            1 for r in pasa if r["top1"]["canonico"] == r["canonico_esperado"]
        ),
        "adyacente_bloquea": sum(
            1 for r in records if r["clase"] == "adyacente" and bloquea(r)
        ),
        "ajena_bloquea": sum(1 for r in records if r["clase"] == "ajena" and bloquea(r)),
    }


def hit_rates(records: list[dict[str, Any]]) -> tuple[int, int, int]:
    """``(hit@1, hit@5, n)`` del canonico esperado sobre la clase dominio."""
    rel = [r for r in records if r["clase"] == "dominio"]
    hit1 = sum(
        1 for r in rel if r["top1"] and r["canonico_esperado"] == r["top1"]["canonico"]
    )
    hit5 = sum(1 for r in rel if r["canonico_esperado"] in r["top5_canonicos"])
    return hit1, hit5, len(rel)


def _search_fn(mode: str, sin_piso: bool) -> SearchFn:
    """``search()`` del modo pedido; ``sin_piso`` fusiona sin piso semantico."""
    if mode == "hybrid" and sin_piso:
        store = _get_search_store()
        index = get_bm25_index()
        return lambda q: hybrid_search(
            q, top_k=5, store=store, bm25_index=index, dense_floor=None
        )
    return lambda q: search(q, top_k=5, mode=mode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mode",
        choices=SUPPORTED_RETRIEVAL_MODES,
        default=None,
        help="modo de retrieval a medir (default: RETRIEVAL_MODE del entorno)",
    )
    parser.add_argument(
        "--sin-piso",
        action="store_true",
        help="hibrido sin piso semantico: union RRF pura (solo para analisis)",
    )
    args = parser.parse_args(argv)
    args.mode = args.mode or get_settings().retrieval_mode
    if args.sin_piso and args.mode != "hybrid":
        parser.error("--sin-piso solo aplica a --mode hybrid")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    records = measure(QUERIES, _search_fn(args.mode, args.sin_piso))
    out = output_path(args.mode, args.sin_piso)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    por_clase = {c: sum(1 for r in records if r["clase"] == c) for c in CLASES}
    modo = args.mode + (" (sin piso semantico)" if args.sin_piso else "")
    print(
        f"Modo: {modo} | Escrito: {out} | dominio={por_clase['dominio']} "
        f"adyacente={por_clase['adyacente']} ajena={por_clase['ajena']}"
    )
    print("\nTop-1 score por clase (sin hits = 0.0):")
    for clase in CLASES:
        print(f"  {clase:<10} {stats([top1(r) for r in records if r['clase'] == clase])}")
    print("\nMax score (lo peor que un umbral tendria que dejar pasar):")
    for clase in CLASES:
        print(
            f"  {clase:<10} "
            f"{stats([max(r['scores'], default=0.0) for r in records if r['clase'] == clase])}"
        )

    hit1, hit5, n = hit_rates(records)
    print(f"\nHit@1 (canonico esperado en top-1): {hit1}/{n}")
    print(f"Hit@5 (canonico esperado en top-5): {hit5}/{n}")

    print("\nBarrido de umbrales sobre el top-1:")
    print("  umbral | dominio pasa | hit@1 que pasa | adyacente bloq. | ajena bloq.")
    for umbral in SWEEP[args.mode]:
        r = sweep(records, umbral)
        print(
            f"  {umbral:>6.2f} | {r['dominio_pasa']:>5}/{por_clase['dominio']:<6} "
            f"| {r['dominio_hit1']:>14} | {r['adyacente_bloquea']:>8}/{por_clase['adyacente']:<6} "
            f"| {r['ajena_bloquea']:>5}/{por_clase['ajena']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

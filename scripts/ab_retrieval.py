"""A/B de retrieval denso vs. hibrido sobre el golden set (#42), sin LLM.

Complementa a ``scripts/evaluate_ragas.py`` (que mide Context Recall/Precision
con un juez LLM) con metricas deterministicas y baratas sobre las filas
``answer_from_policy`` y ``abstain_*`` del golden set (#19):

* ``recall@1/3/5`` y ``MRR`` del articulo de referencia en el top-5 de
  ``search()`` (antes del hard gate);
* ``recall post-gate``: misma definicion que ``expected_context_retrieved`` del
  runner RAGAS (``app.rag.eval.expected_hit``), tras el hard gate del modo;
* ``hits/pregunta`` que pasan el gate y ``abstencion``: filas ``abstain_*`` sin
  ningun hit sobre el gate (llegarian a la respuesta curada sin LLM).

Requiere Qdrant + Ollama arriba. Escribe el detalle en
``data/evaluation/results/ab_retrieval_<ts>.json`` (gitignored).

Uso:
    uv run python scripts/ab_retrieval.py
    uv run python scripts/ab_retrieval.py --modes dense hybrid
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.config import SUPPORTED_RETRIEVAL_MODES, get_settings  # noqa: E402
from app.rag.eval import POLICY_BEHAVIOR, expected_hit, load_golden  # noqa: E402
from app.rag.vectordb import search  # noqa: E402

GOLDEN_PATH = ROOT / "data/evaluation/ragas_golden.jsonl"
RESULTS_ROOT = ROOT / "data/evaluation/results"
TOP_K = 5

SearchFn = Callable[[str], list[dict[str, Any]]]


def _article(hit: dict[str, Any]) -> tuple[Any, Any, Any]:
    meta = hit["metadata"]
    return meta.get("poliza"), meta.get("documento"), meta.get("articulo")


def reference_rank(row: dict[str, Any], hits: Sequence[dict[str, Any]]) -> int | None:
    """Posicion 1-based del primer hit que es un ``reference_context``; ``None`` si no esta."""
    wanted = {
        (ref.get("poliza"), ref.get("documento"), ref.get("articulo"))
        for ref in row.get("reference_contexts", [])
    }
    for rank, hit in enumerate(hits, start=1):
        if _article(hit) in wanted:
            return rank
    return None


def evaluate_mode(
    rows: Sequence[dict[str, Any]], search_fn: SearchFn, umbral: float
) -> dict[str, Any]:
    """Corre ``search_fn`` sobre las filas y agrega las metricas del modo.

    Args:
        rows: filas del golden set (``answer_from_policy`` y ``abstain_*``).
        search_fn: ``pregunta -> hits`` del modo a medir (top-5, colapsado).
        umbral: hard gate del modo (el que aplicaria ``query()``).

    Returns:
        ``{"summary": {...}, "rows": [...]}`` con una fila por pregunta.
    """
    detail: list[dict[str, Any]] = []
    for row in rows:
        hits = search_fn(row["question"])
        gated = [hit for hit in hits if hit["score"] >= umbral]
        detail.append(
            {
                "id": row["id"],
                "expected_behavior": row["expected_behavior"],
                "rank": reference_rank(row, hits),
                "hit_post_gate": expected_hit(row, {"retrieval_hits": gated}),
                "n_post_gate": len(gated),
                "scores": [hit["score"] for hit in hits],
            }
        )

    policy = [d for d in detail if d["expected_behavior"] == POLICY_BEHAVIOR]
    abstain = [d for d in detail if d["expected_behavior"].startswith("abstain_")]

    def recall_at(k: int) -> float | None:
        if not policy:
            return None
        return sum(1 for d in policy if d["rank"] and d["rank"] <= k) / len(policy)

    summary = {
        "umbral": umbral,
        "n_policy": len(policy),
        "n_abstain": len(abstain),
        "recall@1": recall_at(1),
        "recall@3": recall_at(3),
        "recall@5": recall_at(5),
        "mrr": (
            sum(1 / d["rank"] for d in policy if d["rank"]) / len(policy)
            if policy
            else None
        ),
        "recall_post_gate": (
            sum(1 for d in policy if d["hit_post_gate"]) / len(policy) if policy else None
        ),
        "hits_post_gate_policy": (
            sum(d["n_post_gate"] for d in policy) / len(policy) if policy else None
        ),
        "abstencion": (
            sum(1 for d in abstain if d["n_post_gate"] == 0) / len(abstain)
            if abstain
            else None
        ),
    }
    return {"summary": summary, "rows": detail}


def select_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filas con sentido para retrieval: poliza y abstencion (las web no tienen contexto)."""
    return [
        row
        for row in rows
        if row["expected_behavior"] == POLICY_BEHAVIOR
        or row["expected_behavior"].startswith("abstain_")
    ]


def _fmt(value: Any) -> str:
    return "—" if value is None else f"{value:.3f}"


def render_table(results: dict[str, dict[str, Any]]) -> str:
    """Tabla Markdown ``modo x metrica`` con el delta respecto del primer modo."""
    metrics = (
        "recall@1",
        "recall@3",
        "recall@5",
        "mrr",
        "recall_post_gate",
        "hits_post_gate_policy",
        "abstencion",
    )
    modes = list(results)
    header = "| Métrica | " + " | ".join(modes)
    if len(modes) == 2:
        header += f" | Δ ({modes[1]} − {modes[0]})"
    lines = [header + " |", "|---" * (len(modes) + 1 + (len(modes) == 2)) + "|"]
    for metric in metrics:
        values = [results[mode]["summary"][metric] for mode in modes]
        cells = [_fmt(v) for v in values]
        if len(modes) == 2:
            a, b = values
            cells.append("—" if a is None or b is None else f"{b - a:+.3f}")
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _umbral(mode: str) -> float:
    settings = get_settings()
    return settings.umbral_score_hybrid if mode == "hybrid" else settings.umbral_score_dense


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=SUPPORTED_RETRIEVAL_MODES,
        default=list(SUPPORTED_RETRIEVAL_MODES),
    )
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = select_rows(load_golden(args.golden))
    results = {
        mode: evaluate_mode(
            rows,
            lambda question, mode=mode: search(question, top_k=TOP_K, mode=mode),
            _umbral(mode),
        )
        for mode in args.modes
    }
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_ROOT / f"ab_retrieval_{stamp}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Detalle en {out.relative_to(ROOT)}")
    print(f"Filas: {len(rows)} (póliza + abstención) · top_k={TOP_K}\n")
    print(render_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

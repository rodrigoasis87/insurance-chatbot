"""A/B determinista de retrieval: denso vs. hibrido actual vs. hibrido con metadata.

Mide sobre tres conjuntos:

* ``data/evaluation/retrieval_literal.jsonl``: 60 consultas literales (codigos
  de poliza, numeros de articulo, terminos raros y frases unicas) con articulo
  de referencia exacto;
* el control de parafrasis ``answer_from_policy`` del golden set;
* las filas ``abstain_*`` del golden set + las consultas adyacentes/ajenas de
  ``scripts/analisis_umbral.py`` (abstencion del hard gate).

Variantes:

* ``dense``: produccion densa; gate ``UMBRAL_SCORE``.
* ``hybrid_current``: hibrido de produccion (BM25 sobre ``page_content``);
  piso denso ``UMBRAL_SCORE`` y gate ``UMBRAL_SCORE_HYBRID``.
* ``hybrid_meta``: mismo hibrido, pero el indice BM25 tambien indexa
  ``poliza``, ``documento``, ``articulo`` y ``titulo_canonico``. Es un
  prototipo de evaluacion: no cambia el indice de produccion.
* ``hybrid_current_sin_piso`` y ``hybrid_meta_sin_piso``: diagnostico de la
  fusion RRF sin piso semantico (para separar el efecto del indice del efecto
  del piso).

No usa LLM, RAGAS ni red de LLM. Requiere Qdrant + Ollama arriba. Escribe el
detalle en ``data/evaluation/results/ab_literal_<ts>.json`` (gitignored).

Uso:
    uv run python scripts/ab_retrieval_literal.py
    uv run python scripts/ab_retrieval_literal.py --variants dense hybrid_meta
    uv run python scripts/ab_retrieval_literal.py --bootstrap 5000 --seed 7
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_core.documents import Document  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

from app.paths import CHUNKS_JSONL  # noqa: E402
from app.rag.bm25 import (  # noqa: E402
    BM25Index,
    LexicalHit,
    chunk_key,
    get_bm25_index,
    tokenize,
)
from app.rag.config import get_settings  # noqa: E402
from app.rag.eval import POLICY_BEHAVIOR, load_golden  # noqa: E402
from app.rag.retrieval_eval import (  # noqa: E402
    bootstrap_mean_delta,
    hit_key,
    mcnemar_exact,
    paired_comparison,
    post_gate_hits,
    reference_keys,
    render_metric,
    summarize,
)
from app.rag.vectordb import (  # noqa: E402
    HYBRID_CANDIDATES_FACTOR,
    RRF_K,
    _dense_hits,
    _get_search_store,
    _lexical_hits,
    colapsar_por_articulo,
    rrf_fuse,
)

LITERAL_PATH = ROOT / "data/evaluation/retrieval_literal.jsonl"
GOLDEN_PATH = ROOT / "data/evaluation/ragas_golden.jsonl"
RESULTS_ROOT = ROOT / "data/evaluation/results"
TOP_K = 5
OOD_BEHAVIOR = "abstain_out_of_domain"

ARTICULO_RE = re.compile(r"\b(?:art[ií]culo|art)\.?\s*(\d+)", re.IGNORECASE)


class MetadataBM25Index(BM25Index):
    """BM25 que indexa tambien la metadata del chunk (prototipo de evaluacion).

    El indice de produccion solo indexa ``page_content``; como los codigos de
    poliza y los numeros de articulo viven en la metadata, esa variante no
    puede recuperarlos. Este indice agrega ``poliza``, ``documento``,
    ``articulo``, ``artN`` y ``titulo_canonico`` al texto indexado. Devuelve los
    ``Document`` originales, sin alterar el ``page_content`` de los hits.

    No se usa en produccion: vive aca para medir el potencial antes de decidir
    un cambio de esquema.
    """

    def __init__(self, documents: list[Document]) -> None:
        if not documents:
            raise ValueError("No se puede construir un indice BM25 sin documentos.")
        self.documents = list(documents)
        self._bm25 = BM25Okapi(
            [tokenize(_metadata_text(doc)) for doc in self.documents]
        )

    def search(self, query: str, k: int) -> list[LexicalHit]:
        if k <= 0:
            return []
        terms = tokenize(query)
        match = ARTICULO_RE.search(query)
        if match:
            terms.append(f"art{int(match.group(1))}")
        if not terms:
            return []
        scores = self._bm25.get_scores(terms)
        order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
        return [
            LexicalHit(self.documents[index], float(scores[index]))
            for index in order[:k]
            if scores[index] > 0
        ]


def _metadata_text(document: Document) -> str:
    """Texto indexado por :class:`MetadataBM25Index`, con los campos del contrato."""
    metadata = document.metadata
    articulo = metadata.get("articulo", "")
    return " ".join(
        part
        for part in (
            str(metadata.get("poliza", "")),
            f"documento {metadata.get('documento', '')}",
            f"articulo {articulo}",
            f"art{articulo}",
            str(metadata.get("titulo_canonico", "")),
            document.page_content,
        )
        if part.strip()
    )


@lru_cache(maxsize=1)
def get_metadata_bm25_index(path: Path = CHUNKS_JSONL) -> MetadataBM25Index:
    """Indice BM25 con metadata, construido una vez por proceso."""
    from app.rag.indexer import load_chunks

    return MetadataBM25Index(load_chunks(path))


@dataclass(frozen=True)
class Variant:
    """Configuracion de una variante de retrieval."""

    name: str
    mode: str
    gate: float
    index_kind: str | None = None
    dense_floor: float | None = None


@dataclass
class RetrievalResult:
    """Hits y candidatos crudos de una variante para una pregunta."""

    hits: list[dict[str, Any]]
    dense_candidates: list[dict[str, Any]]
    lexical_candidates: list[dict[str, Any]]
    dense_ms: float
    lexical_ms: float
    extra_ms: float

    @property
    def elapsed_ms(self) -> float:
        return self.dense_ms + self.lexical_ms + self.extra_ms


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _ood_rows() -> list[dict[str, Any]]:
    from scripts.analisis_umbral import QUERIES

    rows: list[dict[str, Any]] = []
    for index, query in enumerate(QUERIES, start=1):
        if query["clase"] == "dominio":
            continue
        rows.append(
            {
                "id": f"ood-{query['clase']}-{index:02d}",
                "question": query["q"],
                "reference_answer": "",
                "expected_behavior": OOD_BEHAVIOR,
                "reference_contexts": [],
                "query_type": query["clase"],
            }
        )
    return rows


def _fuse_hits(
    dense: Sequence[dict[str, Any]],
    lexical: Sequence[dict[str, Any]],
    *,
    dense_floor: float | None,
    top_k: int,
) -> list[dict[str, Any]]:
    """Filtra el piso denso y fusiona con RRF, igual que ``hybrid_search``."""
    eligible_dense = list(dense)
    eligible_lexical = list(lexical)
    if dense_floor is not None:
        eligible_dense = [hit for hit in dense if hit["score"] >= dense_floor]
        eligible = {chunk_key(hit["metadata"]) for hit in eligible_dense}
        eligible_lexical = [
            hit for hit in lexical if chunk_key(hit["metadata"]) in eligible
        ]
    return colapsar_por_articulo(
        rrf_fuse([eligible_dense, eligible_lexical], k=RRF_K)
    )[:top_k]


def retrieve(
    query: str,
    variant: Variant,
    *,
    store: Any,
    current_index: BM25Index,
    metadata_index: BM25Index,
    top_k: int,
) -> RetrievalResult:
    """Corre una variante y devuelve hits, candidatos crudos y latencia desglosada."""
    n_candidates = top_k * HYBRID_CANDIDATES_FACTOR
    start = time.perf_counter()
    dense = _dense_hits(query, n_candidates, store)
    dense_ms = (time.perf_counter() - start) * 1000

    lexical: list[dict[str, Any]] = []
    lexical_ms = 0.0
    if variant.mode == "hybrid":
        index = metadata_index if variant.index_kind == "meta" else current_index
        start = time.perf_counter()
        lexical = _lexical_hits(query, n_candidates, index)
        lexical_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    if variant.mode == "dense":
        hits = colapsar_por_articulo(dense[: top_k * 2])[:top_k]
        dense_candidates = dense[: top_k * 2]
    else:
        hits = _fuse_hits(
            dense,
            lexical,
            dense_floor=variant.dense_floor,
            top_k=top_k,
        )
        dense_candidates = dense
    extra_ms = (time.perf_counter() - start) * 1000

    return RetrievalResult(
        hits=hits,
        dense_candidates=dense_candidates,
        lexical_candidates=lexical,
        dense_ms=dense_ms,
        lexical_ms=lexical_ms,
        extra_ms=extra_ms,
    )


def _has_reference(row: dict[str, Any], hits: Sequence[dict[str, Any]]) -> bool | None:
    wanted = reference_keys(row)
    if not wanted:
        return None
    return bool(wanted & {hit_key(hit) for hit in hits})


def _hit_summary(hit: dict[str, Any]) -> dict[str, Any]:
    metadata = hit["metadata"]
    return {
        "poliza": metadata.get("poliza"),
        "documento": metadata.get("documento"),
        "articulo": metadata.get("articulo"),
        "score": round(float(hit["score"]), 6),
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(percentile * (len(ordered) - 1)))))
    return ordered[index]


def _latency_summary(details: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [detail["latency_ms"] for detail in details]
    return {
        "mean_ms": mean(values) if values else None,
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "max_ms": max(values) if values else None,
    }


def evaluate_dataset(
    rows: Sequence[dict[str, Any]],
    variants: Sequence[Variant],
    *,
    store: Any,
    current_index: BM25Index,
    metadata_index: BM25Index,
    top_k: int,
) -> dict[str, Any]:
    """Evalua todas las variantes sobre un dataset, reutilizando los candidatos densos."""
    results: dict[str, Any] = {}
    for variant in variants:
        hits_by_id: dict[str, list[dict[str, Any]]] = {}
        details: list[dict[str, Any]] = []
        for row in rows:
            outcome = retrieve(
                row["question"],
                variant,
                store=store,
                current_index=current_index,
                metadata_index=metadata_index,
                top_k=top_k,
            )
            hits_by_id[row["id"]] = outcome.hits
            gated = post_gate_hits(outcome.hits, variant.gate)
            details.append(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "query_type": row.get("query_type", row.get("expected_behavior")),
                    "expected_behavior": row.get("expected_behavior"),
                    "reference_contexts": row.get("reference_contexts", []),
                    "hits": [_hit_summary(hit) for hit in outcome.hits],
                    "gated_hits": len(gated),
                    "rank": next(
                        (
                            rank
                            for rank, hit in enumerate(outcome.hits, start=1)
                            if hit_key(hit) in reference_keys(row)
                        ),
                        None,
                    )
                    if reference_keys(row)
                    else None,
                    "post_gate_hit": _has_reference(row, gated),
                    "dense_candidate_hit": _has_reference(row, outcome.dense_candidates),
                    "lexical_candidate_hit": _has_reference(
                        row, outcome.lexical_candidates
                    ),
                    "union_candidate_hit": _has_reference(
                        row, outcome.dense_candidates + outcome.lexical_candidates
                    ),
                    "latency_ms": outcome.elapsed_ms,
                }
            )
        summary = summarize(rows, hits_by_id, variant.gate, top_k=top_k)
        results[variant.name] = {
            "summary": summary,
            "latency": _latency_summary(details),
            "details": details,
            "hits_by_id": hits_by_id,
        }
    return results


def _by_query_type(
    rows: Sequence[dict[str, Any]],
    results: dict[str, Any],
    variants: dict[str, Variant],
    top_k: int,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row.get("query_type", row["expected_behavior"])].append(row)
    output: dict[str, Any] = {}
    for query_type, subset in sorted(grouped.items()):
        output[query_type] = {}
        for name, result in results.items():
            summary = summarize(
                subset,
                result["hits_by_id"],
                variants[name].gate,
                top_k=top_k,
            )
            candidate_rows = [
                detail
                for detail in result["details"]
                if detail["id"] in {row["id"] for row in subset}
            ]
            output[query_type][name] = {
                "n": len(subset),
                "recall_post_gate": summary["recall_post_gate"],
                f"recall@{top_k}": summary[f"recall@{top_k}"],
                "ndcg@5": summary["ndcg@5"],
                "dense_candidate_recall": mean(
                    1.0 if detail["dense_candidate_hit"] else 0.0
                    for detail in candidate_rows
                ),
                "lexical_candidate_recall": mean(
                    1.0 if detail["lexical_candidate_hit"] else 0.0
                    for detail in candidate_rows
                ),
                "union_candidate_recall": mean(
                    1.0 if detail["union_candidate_hit"] else 0.0
                    for detail in candidate_rows
                ),
            }
    return output


def _configure_variants(settings: Any) -> dict[str, Variant]:
    variants = [
        Variant(
            name="dense",
            mode="dense",
            gate=settings.umbral_score_dense,
        ),
        Variant(
            name="hybrid_current",
            mode="hybrid",
            gate=settings.umbral_score_hybrid,
            index_kind="current",
            dense_floor=settings.umbral_score_dense,
        ),
        Variant(
            name="hybrid_meta",
            mode="hybrid",
            gate=settings.umbral_score_hybrid,
            index_kind="meta",
            dense_floor=settings.umbral_score_dense,
        ),
        Variant(
            name="hybrid_current_sin_piso",
            mode="hybrid",
            gate=settings.umbral_score_hybrid,
            index_kind="current",
            dense_floor=None,
        ),
        Variant(
            name="hybrid_meta_sin_piso",
            mode="hybrid",
            gate=settings.umbral_score_hybrid,
            index_kind="meta",
            dense_floor=None,
        ),
    ]
    return {variant.name: variant for variant in variants}


def _abstention_values(
    rows: Sequence[dict[str, Any]],
    hits_by_id: dict[str, list[dict[str, Any]]],
    gate: float,
) -> list[bool]:
    return [
        not post_gate_hits(hits_by_id.get(row["id"], []), gate)
        for row in rows
    ]


def _comparison(
    rows: Sequence[dict[str, Any]],
    results: dict[str, Any],
    variants: dict[str, Variant],
    name_a: str,
    name_b: str,
    *,
    top_k: int,
    n_resamples: int,
    seed: int,
) -> dict[str, Any]:
    return paired_comparison(
        rows,
        results[name_a]["hits_by_id"],
        results[name_b]["hits_by_id"],
        k=top_k,
        gate_a=variants[name_a].gate,
        gate_b=variants[name_b].gate,
        n_resamples=n_resamples,
        seed=seed,
    )


def _abstention_comparison(
    rows: Sequence[dict[str, Any]],
    results: dict[str, Any],
    variants: dict[str, Variant],
    name_a: str,
    name_b: str,
    *,
    n_resamples: int,
    seed: int,
) -> dict[str, Any]:
    values_a = _abstention_values(
        rows, results[name_a]["hits_by_id"], variants[name_a].gate
    )
    values_b = _abstention_values(
        rows, results[name_b]["hits_by_id"], variants[name_b].gate
    )
    return {
        "rate_a": mean(values_a) if values_a else None,
        "rate_b": mean(values_b) if values_b else None,
        "delta": bootstrap_mean_delta(
            [1.0 if value else 0.0 for value in values_a],
            [1.0 if value else 0.0 for value in values_b],
            n_resamples=n_resamples,
            seed=seed,
        ),
        "mcnemar": mcnemar_exact(values_a, values_b),
    }


def _serializable_dataset(result: dict[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "summary": value["summary"],
            "latency": value["latency"],
            "details": value["details"],
        }
        for name, value in result.items()
    }


def _render_summary_table(
    title: str, summaries: dict[str, Any], top_k: int
) -> str:
    metrics = (
        "recall@1",
        "recall@3",
        f"recall@{top_k}",
        "mrr",
        "ndcg@5",
        "recall_post_gate",
        "abstencion",
    )
    names = list(summaries)
    lines = [
        f"### {title}",
        "",
        "| Variante | " + " | ".join(metrics) + " |",
        "|---" * (len(metrics) + 1) + "|",
    ]
    for name in names:
        summary = summaries[name]["summary"]
        lines.append(
            f"| {name} | "
            + " | ".join(render_metric(summary[metric]) for metric in metrics)
            + " |"
        )
    return "\n".join(lines)


def _render_by_type(by_type: dict[str, Any], top_k: int) -> str:
    variants = list(next(iter(by_type.values()))) if by_type else []
    lines = [
        "### Recall post-gate por tipo de consulta (set literal)",
        "",
        "| Tipo | n | " + " | ".join(variants) + " |",
        "|---" * (len(variants) + 2) + "|",
    ]
    for query_type, values in by_type.items():
        lines.append(
            f"| {query_type} | {next(iter(values.values()))['n']} | "
            + " | ".join(
                render_metric(values[name]["recall_post_gate"]) for name in variants
            )
            + " |"
        )
    return "\n".join(lines)


def _render_candidates(by_type: dict[str, Any]) -> str:
    variants = list(next(iter(by_type.values()))) if by_type else []
    lines = [
        "### Candidatos recuperados antes del gate (set literal)",
        "",
        "| Tipo | " + " | ".join(f"{name} denso/lex/union" for name in variants) + " |",
        "|---" * (len(variants) + 1) + "|",
    ]
    for query_type, values in by_type.items():
        cells = []
        for name in variants:
            value = values[name]
            cells.append(
                f"{render_metric(value['dense_candidate_recall'])}/"
                f"{render_metric(value['lexical_candidate_recall'])}/"
                f"{render_metric(value['union_candidate_recall'])}"
            )
        lines.append(f"| {query_type} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render_comparisons(comparisons: dict[str, Any]) -> str:
    lines = [
        "### Comparaciones pareadas (recall@5 post-gate)",
        "",
        "| Comparación | Δ recall | IC 95% | Rescates | Regresiones | McNemar p |",
        "|---|---|---|---|---|---|",
    ]
    for label, comparison in comparisons.items():
        delta = comparison["delta_recall"]
        test = comparison["mcnemar_recall"]
        lines.append(
            f"| {label} | {render_metric(delta['delta'])} | "
            f"[{render_metric(delta['ci_low'])}, {render_metric(delta['ci_high'])}] | "
            f"{comparison['rescues']} | {comparison['regressions']} | "
            f"{test['p_value']:.4f} |"
        )
    return "\n".join(lines)


def _render_abstention(comparisons: dict[str, Any]) -> str:
    lines = [
        "### Abstención (negativos: golden + OOD)",
        "",
        "| Comparación | A | B | Δ abstención | IC 95% | McNemar p |",
        "|---|---|---|---|---|---|",
    ]
    for label, comparison in comparisons.items():
        delta = comparison["delta"]
        lines.append(
            f"| {label} | {render_metric(comparison['rate_a'])} | "
            f"{render_metric(comparison['rate_b'])} | "
            f"{render_metric(delta['delta'])} | "
            f"[{render_metric(delta['ci_low'])}, {render_metric(delta['ci_high'])}] | "
            f"{comparison['mcnemar']['p_value']:.4f} |"
        )
    return "\n".join(lines)


def _render_latency(latencies: dict[str, Any]) -> str:
    lines = [
        "### Latencia por consulta (set literal)",
        "",
        "| Variante | mean ms | p50 ms | p95 ms | max ms |",
        "|---|---|---|---|---|",
    ]
    for name, value in latencies.items():
        lines.append(
            f"| {name} | {value['mean_ms']:.1f} | {value['p50_ms']:.1f} | "
            f"{value['p95_ms']:.1f} | {value['max_ms']:.1f} |"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--literal", type=Path, default=LITERAL_PATH)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--top-k", type=int, default=TOP_K)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--variants",
        nargs="+",
        default=[
            "dense",
            "hybrid_current",
            "hybrid_meta",
            "hybrid_current_sin_piso",
            "hybrid_meta_sin_piso",
        ],
    )
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    variants = _configure_variants(settings)
    unknown = set(args.variants) - set(variants)
    if unknown:
        raise SystemExit(f"Variantes desconocidas: {sorted(unknown)}")
    selected = [variants[name] for name in args.variants]
    literal = _load_jsonl(args.literal)
    golden = load_golden(args.golden)
    golden_policy = [
        row for row in golden if row["expected_behavior"] == POLICY_BEHAVIOR
    ]
    golden_abstain = [
        row for row in golden if row["expected_behavior"].startswith("abstain_")
    ]
    ood = _ood_rows()
    negative = golden_abstain + ood

    store = _get_search_store()
    current_index = get_bm25_index()
    metadata_index = get_metadata_bm25_index()
    warmup = "¿Qué cubre la póliza?"
    _dense_hits(warmup, args.top_k * HYBRID_CANDIDATES_FACTOR, store)
    _lexical_hits(warmup, args.top_k * HYBRID_CANDIDATES_FACTOR, current_index)
    _lexical_hits(warmup, args.top_k * HYBRID_CANDIDATES_FACTOR, metadata_index)

    datasets = {
        "literal": literal,
        "golden_policy": golden_policy,
        "golden_abstain": golden_abstain,
        "ood": ood,
        "negative": negative,
    }
    results = {
        name: evaluate_dataset(
            rows,
            selected,
            store=store,
            current_index=current_index,
            metadata_index=metadata_index,
            top_k=args.top_k,
        )
        for name, rows in datasets.items()
    }

    literal_by_type = _by_query_type(
        literal, results["literal"], variants, args.top_k
    )
    literal_comparisons = {
        f"{name_a} → {name_b}": _comparison(
            literal,
            results["literal"],
            variants,
            name_a,
            name_b,
            top_k=args.top_k,
            n_resamples=args.bootstrap,
            seed=args.seed,
        )
        for name_a, name_b in (
            ("dense", "hybrid_current"),
            ("dense", "hybrid_meta"),
            ("dense", "hybrid_current_sin_piso"),
            ("dense", "hybrid_meta_sin_piso"),
            ("hybrid_current", "hybrid_meta"),
            ("hybrid_current_sin_piso", "hybrid_meta_sin_piso"),
        )
        if name_a in results["literal"] and name_b in results["literal"]
    }
    golden_comparisons = {
        f"{name_a} → {name_b}": _comparison(
            golden_policy,
            results["golden_policy"],
            variants,
            name_a,
            name_b,
            top_k=args.top_k,
            n_resamples=args.bootstrap,
            seed=args.seed,
        )
        for name_a, name_b in (
            ("dense", "hybrid_current"),
            ("dense", "hybrid_meta"),
            ("dense", "hybrid_current_sin_piso"),
            ("dense", "hybrid_meta_sin_piso"),
            ("hybrid_current_sin_piso", "hybrid_meta_sin_piso"),
        )
        if name_a in results["golden_policy"] and name_b in results["golden_policy"]
    }
    abstention_comparisons = {
        f"{name_a} → {name_b}": _abstention_comparison(
            negative,
            results["negative"],
            variants,
            name_a,
            name_b,
            n_resamples=args.bootstrap,
            seed=args.seed,
        )
        for name_a, name_b in (
            ("dense", "hybrid_current"),
            ("dense", "hybrid_meta"),
            ("dense", "hybrid_current_sin_piso"),
            ("dense", "hybrid_meta_sin_piso"),
        )
        if name_a in results["negative"] and name_b in results["negative"]
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "top_k": args.top_k,
            "bootstrap": args.bootstrap,
            "seed": args.seed,
            "variants": args.variants,
            "umbral_dense": settings.umbral_score_dense,
            "umbral_hybrid": settings.umbral_score_hybrid,
            "embedding_model": settings.embedding_model,
            "qdrant_collection": settings.qdrant_collection,
            "n_literal": len(literal),
            "n_golden_policy": len(golden_policy),
            "n_golden_abstain": len(golden_abstain),
            "n_ood": len(ood),
        },
        "datasets": {name: _serializable_dataset(value) for name, value in results.items()},
        "literal_by_type": literal_by_type,
        "comparisons": {
            "literal": literal_comparisons,
            "golden_policy": golden_comparisons,
            "abstention": abstention_comparisons,
        },
    }
    out = args.out
    if out is None:
        RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = RESULTS_ROOT / f"ab_literal_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        display_out = out.relative_to(ROOT)
    except ValueError:
        display_out = out
    print(f"Detalle en {display_out}")
    print(
        f"Set literal: {len(literal)} · golden policy: {len(golden_policy)} · "
        f"golden abstain: {len(golden_abstain)} · OOD: {len(ood)}"
    )
    print(
        f"Umbrales: denso={settings.umbral_score_dense:.2f} "
        f"hibrido={settings.umbral_score_hybrid:.2f} · top_k={args.top_k}\n"
    )
    for name, title in (
        ("literal", "Set literal"),
        ("golden_policy", "Control golden (paráfrasis)"),
        ("negative", "Negativos (golden abstain + OOD)"),
    ):
        print(_render_summary_table(title, results[name], args.top_k))
        print()
    print(_render_by_type(literal_by_type, args.top_k))
    print()
    print(_render_candidates(literal_by_type))
    print()
    print(_render_comparisons(literal_comparisons))
    print()
    print(_render_comparisons(golden_comparisons))
    print()
    print(_render_abstention(abstention_comparisons))
    print()
    print(
        _render_latency(
            {
                name: results["literal"][name]["latency"]
                for name in results["literal"]
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Metricas deterministicas de retrieval para el A/B hibrido.

No usa LLM, RAGAS ni red: recibe filas con ``reference_contexts`` y los hits
devueltos por cualquier variante de busqueda. Sirve para comparar denso contra
hibrido sobre el set literal (codigos, articulos, terminos raros y frases
unicas) y para medir la abstencion del hard gate en consultas fuera de dominio.

Convenciones:

* la relevancia es binaria por articulo ``(poliza, documento, articulo)``;
* los hits deben venir colapsados por articulo (contrato de ``search()``);
* ``recall``, ``MRR`` y ``nDCG`` se calculan antes del hard gate; las variantes
  ``post_gate`` aplican el umbral del modo;
* las filas sin ``reference_contexts`` no entran en metricas de ranking.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from statistics import mean
from typing import Any

ArticleKey = tuple[Any, Any, Any]
Hit = dict[str, Any]
Row = dict[str, Any]


def article_key(metadata: dict[str, Any]) -> ArticleKey:
    """Clave de articulo usada por las referencias y por los hits."""
    return (
        metadata.get("poliza"),
        metadata.get("documento"),
        metadata.get("articulo"),
    )


def reference_keys(row: Row) -> set[ArticleKey]:
    """Claves de los ``reference_contexts`` de una fila."""
    return {article_key(ref) for ref in row.get("reference_contexts", [])}


def hit_key(hit: Hit) -> ArticleKey:
    """Clave de articulo de un hit ``{page_content, metadata, score}``."""
    return article_key(hit["metadata"])


def rank_of_first_relevant(row: Row, hits: Sequence[Hit]) -> int | None:
    """Posicion 1-based del primer hit relevante; ``None`` si no aparece."""
    wanted = reference_keys(row)
    if not wanted:
        return None
    for rank, hit in enumerate(hits, start=1):
        if hit_key(hit) in wanted:
            return rank
    return None


def post_gate_hits(hits: Sequence[Hit], umbral: float) -> list[Hit]:
    """Hits cuyo score supera el hard gate del modo."""
    return [hit for hit in hits if hit["score"] >= umbral]


def relevant_at(row: Row, hits: Sequence[Hit], k: int) -> bool:
    """¿Algun articulo de referencia esta en el top-k?"""
    rank = rank_of_first_relevant(row, hits[:k])
    return rank is not None


def recall_at(rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]], k: int) -> float | None:
    """Recall@k binario promedio sobre filas con contexto de referencia."""
    values = per_row_recall_at(rows, hits_by_id, k)
    return mean(values) if values else None


def per_row_recall_at(
    rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]], k: int
) -> list[float]:
    """Un ``0.0``/``1.0`` por fila con referencia (el orden conserva ``rows``)."""
    return [
        1.0 if relevant_at(row, hits_by_id.get(row["id"], []), k) else 0.0
        for row in rows
        if reference_keys(row)
    ]


def reciprocal_rank(row: Row, hits: Sequence[Hit]) -> float:
    """``1/rank`` del primer relevante, o ``0`` si no aparece."""
    rank = rank_of_first_relevant(row, hits)
    return 1.0 / rank if rank else 0.0


def mrr(rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]]) -> float | None:
    """Mean Reciprocal Rank sobre filas con referencia."""
    values = [
        reciprocal_rank(row, hits_by_id.get(row["id"], []))
        for row in rows
        if reference_keys(row)
    ]
    return mean(values) if values else None


def ndcg_at_k(row: Row, hits: Sequence[Hit], k: int) -> float | None:
    """nDCG@k con relevancia binaria y un solo hit por articulo.

    ``None`` si la fila no declara referencias. La ganancia ideal asume que
    todos los articulos de referencia de la fila pueden ocupar los primeros
    puestos, acotada por ``k``.
    """
    wanted = reference_keys(row)
    if not wanted:
        return None
    dcg = 0.0
    seen: set[ArticleKey] = set()
    for rank, hit in enumerate(hits[:k], start=1):
        key = hit_key(hit)
        if key in wanted and key not in seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen.add(key)
    ideal = min(len(wanted), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1))
    return dcg / idcg if idcg else None


def per_row_ndcg_at(
    rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]], k: int
) -> list[float]:
    """Un nDCG@k por fila con referencia."""
    values = [
        ndcg_at_k(row, hits_by_id.get(row["id"], []), k)
        for row in rows
        if reference_keys(row)
    ]
    return [value for value in values if value is not None]


def mean_ndcg_at(
    rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]], k: int
) -> float | None:
    """nDCG@k promedio sobre filas con referencia."""
    values = per_row_ndcg_at(rows, hits_by_id, k)
    return mean(values) if values else None


def abstention_rate(
    rows: Sequence[Row], hits_by_id: dict[str, Sequence[Hit]], umbral: float
) -> float | None:
    """Fraccion de filas sin ningun hit post-gate (abstencion correcta)."""
    if not rows:
        return None
    return sum(
        1
        for row in rows
        if not post_gate_hits(hits_by_id.get(row["id"], []), umbral)
    ) / len(rows)


def summarize(
    rows: Sequence[Row],
    hits_by_id: dict[str, Sequence[Hit]],
    umbral: float,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Agrega ranking y hard gate para un conjunto de filas.

    Returns:
        Diccionario con ``n_rows``, ``n_policy``, ``n_abstain`` y las metricas
        ``recall@1/3/5``, ``mrr``, ``ndcg@5``, ``recall_post_gate``,
        ``mrr_post_gate``, ``hits_post_gate`` y ``abstencion``. Las metricas sin
        filas aplicables valen ``None``.
    """
    policy_rows = [row for row in rows if reference_keys(row)]
    abstain_rows = [row for row in rows if not reference_keys(row)]

    post_gate = {
        row["id"]: post_gate_hits(hits_by_id.get(row["id"], []), umbral)
        for row in policy_rows
    }
    post_gate_rr = [
        reciprocal_rank(row, post_gate[row["id"]]) for row in policy_rows
    ]
    return {
        "n_rows": len(rows),
        "n_policy": len(policy_rows),
        "n_abstain": len(abstain_rows),
        "umbral": umbral,
        "recall@1": recall_at(policy_rows, hits_by_id, 1),
        "recall@3": recall_at(policy_rows, hits_by_id, 3),
        f"recall@{top_k}": recall_at(policy_rows, hits_by_id, top_k),
        "mrr": mrr(policy_rows, hits_by_id),
        "ndcg@5": mean_ndcg_at(policy_rows, hits_by_id, 5),
        "recall_post_gate": (
            sum(
                1
                for row in policy_rows
                if relevant_at(row, post_gate[row["id"]], top_k)
            )
            / len(policy_rows)
            if policy_rows
            else None
        ),
        "mrr_post_gate": mean(post_gate_rr) if post_gate_rr else None,
        "hits_post_gate": (
            mean(len(post_gate[row["id"]]) for row in policy_rows)
            if policy_rows
            else None
        ),
        "abstencion": abstention_rate(abstain_rows, hits_by_id, umbral),
    }


def bootstrap_mean_delta(
    values_a: Sequence[float],
    values_b: Sequence[float],
    *,
    n_resamples: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Delta pareado ``mean(b) - mean(a)`` con IC bootstrap percentil.

    Remuestrea filas (no variantes) con reemplazo, de modo que cada remuestra
    usa el mismo conjunto de preguntas para ambas variantes. Es el IC que
    reporta el A/B: si no cruza 0, la diferencia no se explica por el muestreo
    de preguntas del set.

    Raises:
        ValueError: si las listas tienen distinto largo, estan vacias o
            ``n_resamples``/``alpha`` son invalidos.
    """
    if len(values_a) != len(values_b):
        raise ValueError("Las listas pareadas deben tener el mismo largo")
    if not values_a:
        raise ValueError("No hay filas para remuestrear")
    if n_resamples < 1:
        raise ValueError("n_resamples debe ser >= 1")
    if not 0 < alpha < 1:
        raise ValueError("alpha debe estar entre 0 y 1")

    rng = random.Random(seed)
    n = len(values_a)
    deltas: list[float] = []
    for _ in range(n_resamples):
        indices = [rng.randrange(n) for _ in range(n)]
        sample_a = mean(values_a[index] for index in indices)
        sample_b = mean(values_b[index] for index in indices)
        deltas.append(sample_b - sample_a)
    deltas.sort()
    lower_index = max(0, int((alpha / 2) * n_resamples) - 1)
    upper_index = min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))
    observed = mean(values_b) - mean(values_a)
    return {
        "delta": observed,
        "ci_low": deltas[lower_index],
        "ci_high": deltas[upper_index],
        "n_resamples": n_resamples,
        "seed": seed,
    }


def mcnemar_exact(values_a: Sequence[bool], values_b: Sequence[bool]) -> dict[str, Any]:
    """McNemar exacto para dos variantes sobre las mismas filas.

    Args:
        values_a: acierto (``True``) de la variante A por fila.
        values_b: acierto de la variante B por fila.

    Returns:
        ``{"b": A falla y B acierta, "c": A acierta y B falla, "p_value": ...}``.
        ``p_value`` es el test binomial exacto de dos colas; no usa chi-cuadrado.
    """
    if len(values_a) != len(values_b):
        raise ValueError("Las listas pareadas deben tener el mismo largo")
    b = sum(1 for a, other in zip(values_a, values_b) if not a and other)
    c = sum(1 for a, other in zip(values_a, values_b) if a and not other)
    discordant = b + c
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, index)
            for index in range(min(b, c) + 1)
        )
        p_value = min(1.0, 2 * tail / (2**discordant))
    return {"b": b, "c": c, "p_value": p_value}


def paired_comparison(
    rows: Sequence[Row],
    hits_a: dict[str, Sequence[Hit]],
    hits_b: dict[str, Sequence[Hit]],
    *,
    k: int = 5,
    gate_a: float | None = None,
    gate_b: float | None = None,
    n_resamples: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compara recall@k y nDCG@k de dos variantes con bootstrap y McNemar.

    Solo usa filas con ``reference_contexts``; el orden de ``rows`` define el
    pareo. Si se pasan ``gate_a``/``gate_b``, las metricas se calculan sobre los
    hits post-gate de cada variante (el criterio del A/B); con ``None`` se usan
    los hits crudos.

    Devuelve deltas, IC 95 %, conteo de rescates/regresiones y p-valor de
    McNemar sobre el acierto binario de recall@k.
    """
    policy_rows = [row for row in rows if reference_keys(row)]
    effective_a = (
        {
            row_id: post_gate_hits(hits, gate_a)
            for row_id, hits in hits_a.items()
        }
        if gate_a is not None
        else hits_a
    )
    effective_b = (
        {
            row_id: post_gate_hits(hits, gate_b)
            for row_id, hits in hits_b.items()
        }
        if gate_b is not None
        else hits_b
    )
    recall_a = per_row_recall_at(policy_rows, effective_a, k)
    recall_b = per_row_recall_at(policy_rows, effective_b, k)
    ndcg_a = per_row_ndcg_at(policy_rows, effective_a, k)
    ndcg_b = per_row_ndcg_at(policy_rows, effective_b, k)
    return {
        "n": len(policy_rows),
        "delta_recall": bootstrap_mean_delta(
            recall_a, recall_b, n_resamples=n_resamples, seed=seed
        ),
        "delta_ndcg": bootstrap_mean_delta(
            ndcg_a, ndcg_b, n_resamples=n_resamples, seed=seed
        ),
        "mcnemar_recall": mcnemar_exact(
            [value > 0 for value in recall_a],
            [value > 0 for value in recall_b],
        ),
        "rescues": sum(
            1 for a, b in zip(recall_a, recall_b) if a == 0 and b > 0
        ),
        "regressions": sum(
            1 for a, b in zip(recall_a, recall_b) if a > 0 and b == 0
        ),
    }


def render_metric(value: float | None, digits: int = 3) -> str:
    """Formatea una metrica para tablas Markdown."""
    return "—" if value is None else f"{value:.{digits}f}"


def render_comparison(name_a: str, name_b: str, comparison: dict[str, Any]) -> str:
    """Linea Markdown con delta de recall, IC y McNemar."""
    delta = comparison["delta_recall"]
    test = comparison["mcnemar_recall"]
    return (
        f"| {name_a} → {name_b} | "
        f"{render_metric(delta['delta'])} | "
        f"[{render_metric(delta['ci_low'])}, {render_metric(delta['ci_high'])}] | "
        f"{comparison['rescues']} | {comparison['regressions']} | "
        f"{test['p_value']:.4f} |"
    )


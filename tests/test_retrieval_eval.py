import math

import pytest

from app.rag.retrieval_eval import (
    abstention_rate,
    bootstrap_mean_delta,
    hit_key,
    mcnemar_exact,
    mean_ndcg_at,
    mrr,
    ndcg_at_k,
    paired_comparison,
    per_row_recall_at,
    post_gate_hits,
    rank_of_first_relevant,
    recall_at,
    reference_keys,
    relevant_at,
    summarize,
)


def _hit(poliza, articulo, *, documento="doc", score=0.9):
    return {
        "page_content": "",
        "metadata": {"poliza": poliza, "documento": documento, "articulo": articulo},
        "score": score,
    }


def _row(row_id, refs, behavior="answer_from_policy"):
    contexts = [
        {"poliza": poliza, "documento": "doc", "articulo": articulo}
        for poliza, articulo in refs
    ]
    return {
        "id": row_id,
        "question": f"pregunta {row_id}",
        "reference_answer": "",
        "expected_behavior": behavior,
        "reference_contexts": contexts,
    }


def test_keys_and_rank():
    row = _row("r1", [("P1", 2)])
    hits = [_hit("P2", 1), _hit("P1", 2)]
    assert reference_keys(row) == {("P1", "doc", 2)}
    assert hit_key(hits[1]) == ("P1", "doc", 2)
    assert rank_of_first_relevant(row, hits) == 2
    assert rank_of_first_relevant(row, [hits[0]]) is None
    assert relevant_at(row, hits, 1) is False
    assert relevant_at(row, hits, 2) is True


def test_recall_and_mrr():
    rows = [_row("r1", [("P1", 2)]), _row("r2", [("P1", 3)])]
    hits = {
        "r1": [_hit("P2", 1), _hit("P1", 2)],
        "r2": [_hit("P1", 3)],
    }
    assert recall_at(rows, hits, 1) == 0.5
    assert recall_at(rows, hits, 3) == 1.0
    assert per_row_recall_at(rows, hits, 1) == [0.0, 1.0]
    assert mrr(rows, hits) == pytest.approx((0.5 + 1.0) / 2)
    assert recall_at([_row("r3", [])], {"r3": []}, 1) is None


def test_ndcg():
    row = _row("r1", [("P1", 2)])
    hits = [_hit("P2", 1), _hit("P1", 2)]
    expected = 1 / math.log2(3)
    assert ndcg_at_k(row, hits, 2) == pytest.approx(expected)
    assert ndcg_at_k(row, hits, 1) == 0.0

    row_two = _row("r2", [("P1", 1), ("P1", 3)])
    hits_two = [_hit("P1", 1), _hit("P2", 2), _hit("P1", 3)]
    dcg = 1 + 1 / math.log2(4)
    idcg = 1 + 1 / math.log2(3)
    assert ndcg_at_k(row_two, hits_two, 3) == pytest.approx(dcg / idcg)
    assert mean_ndcg_at([row, row_two], {"r1": hits, "r2": hits_two}, 3) == pytest.approx(
        (1 / math.log2(3) + dcg / idcg) / 2
    )


def test_post_gate_and_abstention():
    hits = [_hit("P1", 1, score=0.9), _hit("P1", 2, score=0.5)]
    assert len(post_gate_hits(hits, 0.8)) == 1
    assert abstention_rate([_row("a", [])], {"a": []}, 0.8) == 1.0
    assert abstention_rate([_row("a", [])], {"a": hits}, 0.8) == 0.0
    assert abstention_rate([], {}, 0.8) is None


def test_summarize():
    rows = [
        _row("r1", [("P1", 2)]),
        _row("r2", [("P1", 3)]),
        _row("a1", [], behavior="abstain_insufficient_information"),
    ]
    hits = {
        "r1": [_hit("P2", 1, score=0.95), _hit("P1", 2, score=0.90)],
        "r2": [_hit("P1", 3, score=0.50)],
        "a1": [],
    }
    summary = summarize(rows, hits, umbral=0.8, top_k=5)
    assert summary["n_rows"] == 3
    assert summary["n_policy"] == 2
    assert summary["n_abstain"] == 1
    assert summary["recall@1"] == 0.5
    assert summary["recall@3"] == 1.0
    assert summary["mrr"] == pytest.approx(0.75)
    assert summary["recall_post_gate"] == 0.5
    assert summary["mrr_post_gate"] == pytest.approx(0.25)
    assert summary["hits_post_gate"] == pytest.approx(1.0)
    assert summary["abstencion"] == 1.0


def test_bootstrap_mean_delta():
    result = bootstrap_mean_delta([0, 0, 0, 0], [1, 1, 1, 1], n_resamples=200, seed=7)
    assert result["delta"] == 1.0
    assert result["ci_low"] == 1.0
    assert result["ci_high"] == 1.0

    same = bootstrap_mean_delta([0.2, 0.8], [0.2, 0.8], n_resamples=200, seed=7)
    assert same["delta"] == 0.0
    assert same["ci_low"] == 0.0
    assert same["ci_high"] == 0.0

    with pytest.raises(ValueError):
        bootstrap_mean_delta([1], [1, 0])
    with pytest.raises(ValueError):
        bootstrap_mean_delta([], [])


def test_mcnemar_exact():
    assert mcnemar_exact([False] * 5, [True] * 5) == {
        "b": 5,
        "c": 0,
        "p_value": pytest.approx(0.0625),
    }
    assert mcnemar_exact([True, False], [True, False]) == {
        "b": 0,
        "c": 0,
        "p_value": 1.0,
    }
    assert mcnemar_exact([True] * 3 + [False] * 2, [False] * 3 + [True] * 2)[
        "p_value"
    ] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        mcnemar_exact([True], [])


def test_paired_comparison():
    rows = [
        _row("r1", [("P1", 1)]),
        _row("r2", [("P1", 2)]),
        _row("r3", [("P1", 3)]),
    ]
    hits_a = {"r1": [_hit("P1", 1)], "r2": [_hit("P2", 2)], "r3": [_hit("P2", 3)]}
    hits_b = {"r1": [_hit("P1", 1)], "r2": [_hit("P1", 2)], "r3": [_hit("P1", 3)]}
    comparison = paired_comparison(rows, hits_a, hits_b, k=5, n_resamples=200, seed=7)
    assert comparison["n"] == 3
    assert comparison["rescues"] == 2
    assert comparison["regressions"] == 0
    assert comparison["delta_recall"]["delta"] == pytest.approx(2 / 3)
    assert 0 <= comparison["delta_recall"]["ci_low"] <= comparison["delta_recall"]["ci_high"] <= 1
    assert comparison["mcnemar_recall"] == {
        "b": 2,
        "c": 0,
        "p_value": pytest.approx(0.5),
    }

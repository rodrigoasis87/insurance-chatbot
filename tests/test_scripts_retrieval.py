"""Tests de la logica pura de los scripts de medicion del retrieval (#42).

``scripts/analisis_umbral.py`` (barrido del hard gate) y
``scripts/ab_retrieval.py`` (A/B denso vs. hibrido sobre el golden set) se
prueban con un ``search_fn`` falso: sin Qdrant ni Ollama.
"""

import pytest

from scripts import ab_retrieval, analisis_umbral
from scripts.evaluate_ragas import _render_report


def _hit(canonico: str, score: float, *, poliza: str = "POL1", articulo: int = 1, documento: int = 1) -> dict:
    return {
        "page_content": "x",
        "metadata": {
            "poliza": poliza,
            "documento": documento,
            "articulo": articulo,
            "titulo_canonico": canonico,
        },
        "score": score,
    }


# --- analisis_umbral ---

QUERIES = [
    {"clase": "dominio", "q": "carencia?", "canonico": "carencia"},
    {"clase": "dominio", "q": "retracto?", "canonico": "retracto"},
    {"clase": "adyacente", "q": "perro?", "canonico": None},
    {"clase": "ajena", "q": "mundial?", "canonico": None},
]

RESULTADOS = {
    "carencia?": [_hit("carencia", 0.9), _hit("cobertura", 0.4)],
    "retracto?": [_hit("vigencia", 0.5), _hit("retracto", 0.45)],
    "perro?": [_hit("cobertura", 0.35)],
    "mundial?": [],  # hibrido con piso semantico: sin hits
}


@pytest.fixture
def records() -> list[dict]:
    return analisis_umbral.measure(QUERIES, lambda q: RESULTADOS[q])


def test_measure_arma_un_registro_por_query(records: list[dict]) -> None:
    assert [r["clase"] for r in records] == ["dominio", "dominio", "adyacente", "ajena"]
    assert records[0]["top1"] == {"canonico": "carencia", "poliza": "POL1", "articulo": 1}
    assert records[1]["top5_canonicos"] == ["vigencia", "retracto"]
    assert records[3]["scores"] == [] and records[3]["top1"] is None


def test_top1_sin_hits_vale_cero(records: list[dict]) -> None:
    assert analisis_umbral.top1(records[0]) == 0.9
    assert analisis_umbral.top1(records[3]) == 0.0


def test_sweep_cuenta_pasan_y_bloqueados(records: list[dict]) -> None:
    assert analisis_umbral.sweep(records, 0.40) == {
        "dominio_pasa": 2,
        "dominio_hit1": 1,
        "adyacente_bloquea": 1,
        "ajena_bloquea": 1,
    }
    # Con umbral 0 una query SIN hits sigue bloqueada (no hay nada que pase).
    assert analisis_umbral.sweep(records, 0.0)["ajena_bloquea"] == 1
    assert analisis_umbral.sweep(records, 0.0)["adyacente_bloquea"] == 0
    assert analisis_umbral.sweep(records, 0.95)["dominio_pasa"] == 0


def test_hit_rates_sobre_dominio(records: list[dict]) -> None:
    assert analisis_umbral.hit_rates(records) == (1, 2, 2)


def test_stats_resumen_y_vacio() -> None:
    assert analisis_umbral.stats([]) == "—"
    assert analisis_umbral.stats([0.2, 0.4]).startswith("n= 2 min=0.200")


def test_output_path_por_modo() -> None:
    assert analisis_umbral.output_path("dense") == analisis_umbral.OUT
    assert analisis_umbral.output_path("hybrid").name == "umbral_raw_hybrid.json"
    assert (
        analisis_umbral.output_path("hybrid", sin_piso=True).name
        == "umbral_raw_hybrid_sin_piso.json"
    )


def test_parse_args_modo_y_sin_piso(monkeypatch: pytest.MonkeyPatch) -> None:
    assert analisis_umbral.parse_args([]).mode == "dense"
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    assert analisis_umbral.parse_args([]).mode == "hybrid"
    assert analisis_umbral.parse_args(["--sin-piso"]).sin_piso is True
    with pytest.raises(SystemExit):
        analisis_umbral.parse_args(["--mode", "dense", "--sin-piso"])


# --- ab_retrieval ---

ROWS = [
    {
        "id": "p1",
        "question": "q1",
        "expected_behavior": "answer_from_policy",
        "reference_contexts": [{"poliza": "POL1", "documento": 1, "articulo": 5}],
    },
    {
        "id": "p2",
        "question": "q2",
        "expected_behavior": "answer_from_policy",
        "reference_contexts": [{"poliza": "POL2", "documento": 1, "articulo": 9}],
    },
    {"id": "a1", "question": "q3", "expected_behavior": "abstain_personal_information"},
    {"id": "w1", "question": "q4", "expected_behavior": "answer_from_web"},
]

AB_HITS = {
    "q1": [_hit("t", 0.9, articulo=2), _hit("t", 0.5, articulo=5)],  # referencia en rank 2
    "q2": [_hit("t", 0.8, poliza="POL3", articulo=9)],  # otra poliza: miss
    "q3": [_hit("t", 0.3)],  # bajo el gate: abstencion correcta
}


def test_select_rows_descarta_las_web() -> None:
    assert [r["id"] for r in ab_retrieval.select_rows(ROWS)] == ["p1", "p2", "a1"]


def test_reference_rank_exige_poliza_documento_y_articulo() -> None:
    assert ab_retrieval.reference_rank(ROWS[0], AB_HITS["q1"]) == 2
    assert ab_retrieval.reference_rank(ROWS[1], AB_HITS["q2"]) is None
    assert ab_retrieval.reference_rank(ROWS[2], AB_HITS["q3"]) is None


def test_evaluate_mode_agrega_metricas() -> None:
    result = ab_retrieval.evaluate_mode(
        ab_retrieval.select_rows(ROWS), lambda q: AB_HITS[q], umbral=0.6
    )
    summary = result["summary"]
    assert summary["n_policy"] == 2 and summary["n_abstain"] == 1
    assert summary["recall@1"] == 0.0
    assert summary["recall@3"] == 0.5
    assert summary["mrr"] == pytest.approx(0.25)  # (1/2 + 0) / 2
    # La referencia de q1 (score 0.5) no pasa el gate 0.6.
    assert summary["recall_post_gate"] == 0.0
    assert summary["hits_post_gate_policy"] == 1.0
    assert summary["abstencion"] == 1.0
    assert [d["id"] for d in result["rows"]] == ["p1", "p2", "a1"]


def test_evaluate_mode_sin_filas_de_poliza_no_divide_por_cero() -> None:
    summary = ab_retrieval.evaluate_mode([ROWS[2]], lambda q: AB_HITS[q], 0.6)["summary"]
    assert summary["recall@5"] is None and summary["mrr"] is None
    assert summary["abstencion"] == 1.0


def test_render_table_con_delta() -> None:
    def res(r5: float) -> dict:
        summary = {m: None for m in ("recall@1", "recall@3", "mrr", "recall_post_gate",
                                      "hits_post_gate_policy", "abstencion")}
        summary["recall@5"] = r5
        return {"summary": summary}

    table = ab_retrieval.render_table({"dense": res(0.70), "hybrid": res(0.75)})
    assert "| Métrica | dense | hybrid | Δ (hybrid − dense) |" in table
    assert "| recall@5 | 0.700 | 0.750 | +0.050 |" in table
    assert "| mrr | — | — | — |" in table


# --- evaluate_ragas: el reporte registra el modo de retrieval ---


def test_reporte_ragas_incluye_el_modo_de_retrieval() -> None:
    meta = {
        "started_at": "t", "git_commit": "c", "generator_provider": "ollama",
        "generator_model": "m", "judge_provider": "ollama", "judge_model": "m",
        "embedding_model": "e", "retrieval_mode": "hybrid", "score_threshold": 0.4,
        "top_k": 5, "qdrant_collection": "polizas", "qdrant_points_count": 1,
        "qdrant_status": "green", "corpus_sha256": "h", "ragas_version": "0.4.3",
        "metrics": ["context_recall"], "selected_question_ids": ["ragas-001"],
    }
    summary = {"metadata": meta, "questions_run": 1, "ragas_metrics": {}, "by_behavior": {}}
    report = _render_report(summary)
    assert "- Retrieval: `hybrid` · umbral (hard gate): `0.4` · top_k `5`" in report
    # Corridas viejas (sin la clave) se leen como densas.
    del meta["retrieval_mode"]
    assert "- Retrieval: `dense`" in _render_report(summary)


# --- scripts/test_vectordb.py: el smoke del denso no depende de RETRIEVAL_MODE ---


def test_smoke_vectordb_fija_el_modo_denso(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import test_vectordb as smoke

    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    by_canonico = {c["metadata"]["titulo_canonico"]: c for c in smoke.MOCK_CHUNKS}
    modes: list[str | None] = []

    def fake_search(query: str, top_k: int, *, store, mode=None) -> list[dict]:
        modes.append(mode)
        expected = dict(smoke.QUERIES)[query]
        top = by_canonico[expected]
        return [
            {"page_content": top["page_content"], "metadata": top["metadata"], "score": 0.9},
            {"page_content": "otro", "metadata": {}, "score": 0.1},
        ]

    monkeypatch.setattr(smoke, "search", fake_search)
    assert smoke.check_search(store=None, min_score=0.3) == []
    assert modes == ["dense"] * len(smoke.QUERIES)

"""Tests de la logica pura de evaluacion RAG (#19), sin red ni RAGAS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.rag.eval import cap_policy, cita_ok, expected_hit, load_golden


def _write_golden(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _row(**overrides) -> dict:
    row = {
        "id": "q01",
        "question": "¿Qué cubre?",
        "reference_answer": "Cubre X.",
        "expected_behavior": "answer_from_policy",
    }
    row.update(overrides)
    return row


def test_load_golden_ok(tmp_path: Path) -> None:
    path = _write_golden(tmp_path / "g.jsonl", [_row(), _row(id="q02")])
    rows = load_golden(path)
    assert [row["id"] for row in rows] == ["q01", "q02"]


def test_load_golden_missing_field(tmp_path: Path) -> None:
    row = _row()
    del row["reference_answer"]
    path = _write_golden(tmp_path / "g.jsonl", [row])
    with pytest.raises(ValueError, match="faltan campos"):
        load_golden(path)


def test_load_golden_duplicate_ids(tmp_path: Path) -> None:
    path = _write_golden(tmp_path / "g.jsonl", [_row(), _row()])
    with pytest.raises(ValueError, match="IDs duplicados"):
        load_golden(path)


def test_load_golden_unknown_behavior(tmp_path: Path) -> None:
    path = _write_golden(
        tmp_path / "g.jsonl", [_row(expected_behavior="inventado")]
    )
    with pytest.raises(ValueError, match="no reconocido"):
        load_golden(path)


def test_load_golden_empty(tmp_path: Path) -> None:
    path = _write_golden(tmp_path / "g.jsonl", [])
    with pytest.raises(ValueError, match="vacio"):
        load_golden(path)


def test_load_golden_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_golden(tmp_path / "no_existe.jsonl")


def test_expected_hit_match() -> None:
    row = {
        "reference_contexts": [
            {"poliza": "POL1", "documento": 1, "articulo": 13}
        ]
    }
    trace = {
        "retrieval_hits": [
            {"metadata": {"poliza": "POL1", "documento": 1, "articulo": 13}}
        ]
    }
    assert expected_hit(row, trace) is True


def test_expected_hit_no_match() -> None:
    row = {
        "reference_contexts": [
            {"poliza": "POL1", "documento": 1, "articulo": 13}
        ]
    }
    trace = {
        "retrieval_hits": [
            {"metadata": {"poliza": "POL9", "documento": 1, "articulo": 99}}
        ]
    }
    assert expected_hit(row, trace) is False


def test_expected_hit_without_reference_contexts() -> None:
    assert expected_hit({"id": "q"}, {"retrieval_hits": []}) is None


def test_cap_policy_limits_policy_keeps_others() -> None:
    rows = [
        _row(id="p1"),
        _row(id="p2"),
        _row(id="p3"),
        _row(id="a1", expected_behavior="abstain_missing_information"),
    ]
    selected = cap_policy(rows, 2, seed=0)
    assert len([r for r in selected if r["expected_behavior"] == "answer_from_policy"]) == 2
    assert [r["id"] for r in selected if r["expected_behavior"] != "answer_from_policy"] == [
        "a1"
    ]
    assert len(selected) == 3


def test_cap_policy_none_returns_copy() -> None:
    rows = [_row(id="p1")]
    selected = cap_policy(rows, None)
    assert selected == rows
    assert selected is not rows


def test_cap_policy_noop_when_above_count() -> None:
    rows = [_row(id="p1"), _row(id="p2")]
    assert [r["id"] for r in cap_policy(rows, 5, seed=0)] == ["p1", "p2"]


def test_cap_policy_rejects_zero() -> None:
    with pytest.raises(ValueError, match="al menos 1"):
        cap_policy([_row()], 0)


def _policy_source(poliza: str = "POL1", articulo: int = 13) -> dict:
    return {"origen": "poliza", "poliza": poliza, "articulo": articulo}


def test_cita_ok_valid() -> None:
    result = cita_ok(
        "Cobertura [fuente: POL1 · Art. 13] y [fuente: POL1 · Art. 9].",
        [_policy_source(articulo=13), _policy_source(articulo=9)],
    )
    assert result["ok"] is True
    assert result["citadas"] == 2
    assert result["validas"] == 2
    assert result["rate"] == 1.0


def test_cita_ok_invalid_article() -> None:
    result = cita_ok(
        "Cobertura [fuente: POL1 · Art. 99].", [_policy_source(articulo=13)]
    )
    assert result["ok"] is False
    assert result["validas"] == 0
    assert result["rate"] == 0.0


def test_cita_ok_mixed() -> None:
    result = cita_ok(
        "[fuente: POL1 · Art. 13] y [fuente: POL1 · Art. 99].",
        [_policy_source(articulo=13)],
    )
    assert result["citadas"] == 2
    assert result["validas"] == 1
    assert result["ok"] is False
    assert result["rate"] == 0.5


def test_cita_ok_without_citations() -> None:
    result = cita_ok("No está en las fuentes.", [])
    assert result["citadas"] == 0
    assert result["rate"] is None
    assert result["ok"] is False


def test_cita_ok_web_valid_and_invalid() -> None:
    sources = [{"origen": "web", "url": "https://cmf.cl/a"}]
    valid = cita_ok("Dato [fuente web: https://cmf.cl/a].", sources)
    assert valid["ok"] is True
    invalid = cita_ok("Dato [fuente web: https://otro.cl/b].", sources)
    assert invalid["ok"] is False


def test_cita_ok_accepts_page_suffix() -> None:
    result = cita_ok(
        "Cobertura [fuente: POL1 · Art. 13 · pág. 50].",
        [_policy_source(articulo=13)],
    )
    assert result["ok"] is True
    assert result["citadas"] == 1
    assert result["validas"] == 1


def test_cita_ok_accepts_page_suffix_without_accent() -> None:
    result = cita_ok(
        "Cobertura [fuente: POL1 · Art. 13 · pag. 50].",
        [_policy_source(articulo=13)],
    )
    assert result["ok"] is True
    assert result["validas"] == 1


def test_cita_ok_accepts_numbered_format() -> None:
    result = cita_ok(
        "1. Cobertura [1] POL1 · Art. 13 · pág. 50: el texto citado.",
        [_policy_source(articulo=13)],
    )
    assert result["ok"] is True
    assert result["citadas"] == 1
    assert result["validas"] == 1


def test_cita_ok_numbered_format_rejects_wrong_article() -> None:
    result = cita_ok(
        "1. Cobertura [1] POL1 · Art. 99 · pág. 50: el texto citado.",
        [_policy_source(articulo=13)],
    )
    assert result["ok"] is False
    assert result["citadas"] == 1
    assert result["validas"] == 0


def test_cita_ok_numbered_format_rejects_unknown_policy() -> None:
    result = cita_ok(
        "1. Cobertura [1] POL999 · Art. 13 · pág. 50: el texto citado.",
        [_policy_source(articulo=13)],
    )
    assert result["ok"] is False
    assert result["validas"] == 0


def test_cita_ok_counts_page_and_numbered_together() -> None:
    result = cita_ok(
        "Ver [fuente: POL1 · Art. 13 · pág. 50] y [1] POL1 · Art. 9 · pág. 12: texto.",
        [_policy_source(articulo=13), _policy_source(articulo=9)],
    )
    assert result["ok"] is True
    assert result["citadas"] == 2
    assert result["validas"] == 2

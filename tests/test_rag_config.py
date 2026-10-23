"""Tests de la configuracion del retrieval (#42): modo y hard gate por modo."""

import pytest

from app.rag.config import (
    DEFAULT_UMBRAL_SCORE,
    DEFAULT_UMBRAL_SCORE_HYBRID,
    get_settings,
)


def test_default_es_denso_con_el_umbral_historico(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UMBRAL_SCORE", raising=False)
    settings = get_settings()
    assert settings.retrieval_mode == "dense"
    assert settings.umbral_score == pytest.approx(DEFAULT_UMBRAL_SCORE)
    assert settings.umbral_score_dense == pytest.approx(DEFAULT_UMBRAL_SCORE)
    assert settings.umbral_score_hybrid == pytest.approx(DEFAULT_UMBRAL_SCORE_HYBRID)


def test_modo_hibrido_usa_su_propio_umbral(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UMBRAL_SCORE", raising=False)
    monkeypatch.setenv("RETRIEVAL_MODE", " Hybrid ")
    settings = get_settings()
    assert settings.retrieval_mode == "hybrid"
    assert settings.umbral_score == pytest.approx(DEFAULT_UMBRAL_SCORE_HYBRID)
    # El umbral denso sigue disponible: es el piso semantico del hibrido.
    assert settings.umbral_score_dense == pytest.approx(DEFAULT_UMBRAL_SCORE)


def test_umbrales_configurables_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UMBRAL_SCORE", "0.55")
    monkeypatch.setenv("UMBRAL_SCORE_HYBRID", "0.7")
    assert get_settings().umbral_score == pytest.approx(0.55)
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    settings = get_settings()
    assert settings.umbral_score == pytest.approx(0.7)
    assert settings.umbral_score_dense == pytest.approx(0.55)


def test_modo_desconocido_se_conserva_para_que_search_lo_rechace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UMBRAL_SCORE", raising=False)
    monkeypatch.setenv("RETRIEVAL_MODE", "sparse")
    settings = get_settings()
    assert settings.retrieval_mode == "sparse"
    assert settings.umbral_score == pytest.approx(DEFAULT_UMBRAL_SCORE)

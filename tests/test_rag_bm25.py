"""Tests unitarios del indice lexico BM25 (#42). Sin Docker ni Ollama."""

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.rag import bm25 as bm25_module
from app.rag.bm25 import (
    BM25Index,
    build_bm25_index,
    chunk_key,
    get_bm25_index,
    tokenize,
)


def _doc(text: str, articulo: int, *, poliza: str = "POL1", chunk_index: int = 0) -> Document:
    return Document(
        page_content=text,
        metadata={
            "poliza": poliza,
            "documento": 1,
            "ramo": "salud",
            "año": "2020",
            "familia": "f",
            "articulo": articulo,
            "titulo_canonico": "t",
            "pagina": 1,
            "chunk_index": chunk_index,
        },
    )


@pytest.fixture
def index() -> BM25Index:
    return BM25Index(
        [
            _doc("El período de carencia es de 90 días para enfermedades.", 5),
            _doc("El asegurado puede ejercer el derecho de retracto dentro de 10 días.", 18),
            _doc("La compañía reembolsará los gastos médicos cubiertos.", 2),
            _doc("Las primas se pagan mensualmente en unidades de fomento.", 8),
        ]
    )


def test_tokenize_normaliza_tildes_minusculas_y_stopwords() -> None:
    assert tokenize("¿Qué es el PERÍODO de Carencia?") == ["periodo", "carencia"]


def test_tokenize_descarta_tokens_de_un_caracter_y_puntuacion() -> None:
    assert tokenize("a) gastos; b) prótesis, 2022") == ["gastos", "protesis", "2022"]


def test_tokenize_de_solo_stopwords_queda_vacio() -> None:
    assert tokenize("¿de que se trata?") == ["trata"]
    assert tokenize("y de la") == []


def test_chunk_key_coincide_con_la_clave_del_point_id() -> None:
    meta = _doc("x", 3, chunk_index=2).metadata
    assert chunk_key(meta) == ("POL1", 1, 3, 2)
    # Metadata incompleta (puntos viejos sin "documento") no rompe: queda None.
    assert chunk_key({"poliza": "P", "articulo": 1, "chunk_index": 0}) == ("P", None, 1, 0)


def test_search_rankea_por_coincidencia_lexica(index: BM25Index) -> None:
    hits = index.search("¿Cuánto dura la carencia?", k=3)
    assert hits[0].document.metadata["articulo"] == 5
    assert hits[0].score > 0


def test_search_ignora_tildes_en_la_pregunta(index: BM25Index) -> None:
    [hit] = index.search("retractó retracto", k=1)
    assert hit.document.metadata["articulo"] == 18


def test_search_no_devuelve_chunks_sin_terminos_en_comun(index: BM25Index) -> None:
    hits = index.search("carencia", k=10)
    assert [h.document.metadata["articulo"] for h in hits] == [5]


def test_search_vacia_para_pregunta_ajena_o_sin_terminos(index: BM25Index) -> None:
    assert index.search("¿Quién ganó el mundial?", k=5) == []
    assert index.search("¿de la?", k=5) == []
    assert index.search("carencia", k=0) == []


def test_search_respeta_k_y_orden_descendente(index: BM25Index) -> None:
    hits = index.search("gastos primas carencia retracto", k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score


def test_indice_vacio_falla_con_mensaje_claro() -> None:
    with pytest.raises(ValueError, match="sin documentos"):
        BM25Index([])


def test_build_bm25_index_lee_y_valida_chunks_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    # 3 docs: con 2, un termino presente en exactamente la mitad tiene IDF 0.
    docs = [
        _doc("carencia de noventa días", 5),
        _doc("retracto en diez días", 18),
        _doc("primas mensuales", 8),
    ]
    path.write_text(
        "\n".join(
            json.dumps({"page_content": d.page_content, "metadata": d.metadata}, ensure_ascii=False)
            for d in docs
        )
        + "\n",
        encoding="utf-8",
    )
    index = build_bm25_index(path)
    assert len(index) == 3
    assert index.search("retracto", k=1)[0].document.metadata["articulo"] == 18


def test_build_bm25_index_sin_archivo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_bm25_index(tmp_path / "no-existe.jsonl")


def test_get_bm25_index_se_construye_una_vez(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_build(path: Path) -> BM25Index:
        calls.append(path)
        return BM25Index([_doc("carencia", 5)])

    monkeypatch.setattr(bm25_module, "build_bm25_index", fake_build)
    get_bm25_index.cache_clear()
    try:
        path = tmp_path / "chunks.jsonl"
        first = get_bm25_index(path)
        assert get_bm25_index(path) is first
        assert calls == [path]
    finally:
        get_bm25_index.cache_clear()

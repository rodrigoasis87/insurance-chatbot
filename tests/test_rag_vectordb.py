"""Tests unitarios de la capa vectorial con Qdrant en memoria y embeddings falsos.

No necesitan Docker ni Ollama. La prueba con el modelo real esta en
scripts/test_vectordb.py.
"""

from collections.abc import Iterator

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient, models

from app.rag import vectordb as vectordb_module
from app.rag.bm25 import BM25Index
from app.rag.embeddings import get_embedding_dim
from app.rag.vectordb import (
    RRF_K,
    colapsar_por_articulo,
    ensure_collection,
    get_vector_store,
    hybrid_search,
    rrf_fuse,
    search,
)

DIM = 32


@pytest.fixture
def client() -> Iterator[QdrantClient]:
    client = QdrantClient(":memory:")
    yield client
    client.close()


@pytest.fixture
def embeddings() -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(size=DIM)


def test_embedding_dim_is_measured_not_hardcoded(
    embeddings: DeterministicFakeEmbedding,
) -> None:
    assert get_embedding_dim(embeddings) == DIM


def test_ensure_collection_creates_cosine_collection(client: QdrantClient) -> None:
    assert ensure_collection(client, "c", DIM, payload_indexes=False) is True
    params = client.get_collection("c").config.params.vectors
    assert isinstance(params, models.VectorParams)
    assert params.size == DIM
    assert params.distance == models.Distance.COSINE


def test_ensure_collection_is_idempotent(client: QdrantClient) -> None:
    ensure_collection(client, "c", DIM, payload_indexes=False)
    assert ensure_collection(client, "c", DIM, payload_indexes=False) is False


def test_dimension_mismatch_raises(client: QdrantClient) -> None:
    ensure_collection(client, "c", DIM, payload_indexes=False)
    with pytest.raises(ValueError, match="EMBEDDING_MODEL"):
        ensure_collection(client, "c", DIM * 2, payload_indexes=False)


def test_recreate_replaces_collection(client: QdrantClient) -> None:
    ensure_collection(client, "c", DIM, payload_indexes=False)
    created = ensure_collection(
        client, "c", DIM * 2, recreate=True, payload_indexes=False
    )
    assert created is True
    params = client.get_collection("c").config.params.vectors
    assert isinstance(params, models.VectorParams)
    assert params.size == DIM * 2


def test_search_returns_contract_shape(
    client: QdrantClient, embeddings: DeterministicFakeEmbedding
) -> None:
    store = get_vector_store("c", embeddings=embeddings, client=client)
    metadata = {
        "poliza": "POL320130223",
        "ramo": "salud",
        "año": "2013",
        "articulo": 2,
        "titulo_canonico": "cobertura",
        "pagina": 1,
        "chunk_index": 0,
    }
    store.add_texts(["cobertura de gastos médicos"], metadatas=[metadata])

    [hit] = search("cobertura de gastos médicos", top_k=1, store=store)

    assert set(hit) == {"page_content", "metadata", "score"}
    assert hit["page_content"] == "cobertura de gastos médicos"
    assert hit["metadata"] == metadata  # sin "_id" ni "_collection_name"
    assert hit["score"] == pytest.approx(1.0, abs=1e-6)  # mismo texto -> coseno 1


def test_search_rejects_empty_query(
    client: QdrantClient, embeddings: DeterministicFakeEmbedding
) -> None:
    store = get_vector_store("c", embeddings=embeddings, client=client)
    with pytest.raises(ValueError, match="vacia"):
        search("   ", store=store)


def _hit(
    poliza: str, articulo: int, score: float, *, documento: int = 1
) -> dict:
    return {
        "page_content": f"{poliza} art {articulo} (doc {documento})",
        "metadata": {
            "poliza": poliza,
            "documento": documento,
            "articulo": articulo,
        },
        "score": score,
    }


def test_colapsar_conserva_el_mayor_score_por_articulo() -> None:
    hits = [
        _hit("POL1", 2, 0.9, documento=1),
        _hit("POL1", 2, 0.95, documento=3),  # copia embebida: gana
        _hit("POL1", 3, 0.5),
        _hit("POL2", 2, 0.8),  # misma numeracion, otra poliza: NO colapsa
    ]
    out = colapsar_por_articulo(hits)

    assert [(h["metadata"]["poliza"], h["metadata"]["articulo"], h["score"]) for h in out] == [
        ("POL1", 2, 0.95),
        ("POL2", 2, 0.8),
        ("POL1", 3, 0.5),
    ]


def test_colapsar_agrupa_chunks_del_mismo_articulo() -> None:
    hits = [
        _hit("POL1", 2, 0.7, documento=1),
        _hit("POL1", 2, 0.85, documento=1),
    ]
    assert len(colapsar_por_articulo(hits)) == 1


def test_search_colapsa_la_copia_embebida(
    client: QdrantClient, embeddings: DeterministicFakeEmbedding
) -> None:
    store = get_vector_store("c", embeddings=embeddings, client=client)
    base = {
        "ramo": "salud",
        "año": "2013",
        "familia": "colectivo_complementario",
        "titulo_canonico": "cobertura",
        "pagina": 1,
        "chunk_index": 0,
    }
    store.add_texts(
        ["el articulo dos de la poliza original", "la misma clausula copiada"],
        metadatas=[
            {**base, "poliza": "POL320130223", "documento": 1, "articulo": 2},
            {**base, "poliza": "POL320130223", "documento": 3, "articulo": 2},
        ],
    )

    hits = search("el articulo dos de la poliza original", top_k=5, store=store)

    assert len(hits) == 1  # el clon no ocupa un segundo lugar del top_k
    assert hits[0]["page_content"] == "el articulo dos de la poliza original"


def test_search_devuelve_top_k_articulos_distintos(
    client: QdrantClient, embeddings: DeterministicFakeEmbedding
) -> None:
    store = get_vector_store("c", embeddings=embeddings, client=client)
    base = {"ramo": "salud", "familia": "f", "titulo_canonico": "t", "pagina": 1, "chunk_index": 0}
    metas = [
        {**base, "poliza": "P1", "documento": 1, "articulo": i, "año": "2000"}
        for i in range(1, 5)
    ]
    store.add_texts([f"contenido del articulo {i}" for i in range(1, 5)], metadatas=metas)

    hits = search("contenido del articulo 1", top_k=2, store=store)

    assert len(hits) == 2
    assert len({(h["metadata"]["poliza"], h["metadata"]["articulo"]) for h in hits}) == 2


# --- Busqueda hibrida: BM25 + denso fusionados con RRF (#42) ---

def _chunk(poliza: str, articulo: int, chunk_index: int = 0, *, documento: int = 1) -> dict:
    return {
        "page_content": f"{poliza} art {articulo} chunk {chunk_index}",
        "metadata": {
            "poliza": poliza,
            "documento": documento,
            "articulo": articulo,
            "chunk_index": chunk_index,
        },
        "score": 0.0,
    }


def _ids(hits: list[dict]) -> list[tuple]:
    return [(h["metadata"]["poliza"], h["metadata"]["articulo"]) for h in hits]


def test_rrf_premia_el_acuerdo_entre_rankings_y_normaliza() -> None:
    a, b, c, d = (_chunk("P", i) for i in (1, 2, 3, 4))
    fused = rrf_fuse([[a, b, c], [b, d]])

    assert _ids(fused) == [("P", 2), ("P", 1), ("P", 4), ("P", 3)]
    maximo = 2 / (RRF_K + 1)
    assert fused[0]["score"] == pytest.approx((1 / 62 + 1 / 61) / maximo)
    assert fused[1]["score"] == pytest.approx(0.5)  # 1.º en una sola lista
    assert all(0 < h["score"] <= 1 for h in fused)
    assert set(fused[0]) == {"page_content", "metadata", "score"}


def test_rrf_primero_en_ambas_listas_vale_uno() -> None:
    a, b = _chunk("P", 1), _chunk("P", 2)
    fused = rrf_fuse([[a, b], [a, b]])
    assert fused[0]["score"] == pytest.approx(1.0)


def test_rrf_ignora_el_score_original_de_cada_retriever() -> None:
    a, b = _chunk("P", 1), _chunk("P", 2)
    a["score"], b["score"] = 0.01, 999.0  # escalas incomparables (coseno vs. BM25)
    assert _ids(rrf_fuse([[a, b]])) == [("P", 1), ("P", 2)]


def test_rrf_cuenta_una_sola_vez_un_chunk_repetido_en_la_misma_lista() -> None:
    a = _chunk("P", 1)
    [hit] = rrf_fuse([[a, dict(a)], []])
    # Contado dos veces sumaria (1/61 + 1/62); una sola vez vale 1/61 = 0.5 del maximo.
    assert hit["score"] == pytest.approx(0.5)


def test_rrf_distingue_chunks_del_mismo_articulo() -> None:
    fused = rrf_fuse([[_chunk("P", 1, 0), _chunk("P", 1, 1)]])
    assert len(fused) == 2  # el colapso por articulo es un paso posterior


def test_rrf_con_listas_vacias_y_k_invalido() -> None:
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []
    [solo] = rrf_fuse([[], [_chunk("P", 1)]])
    assert solo["score"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="k de RRF"):
        rrf_fuse([[_chunk("P", 1)]], k=-1)


HYBRID_TEXTS = {
    ("POL1", 2, 0): "el periodo de carencia para enfermedades es de noventa dias",
    ("POL1", 2, 1): "la carencia no aplica a los accidentes cubiertos",
    ("POL1", 5, 0): "el derecho de retracto se ejerce dentro de diez dias",
    ("POL2", 2, 0): "las primas se pagan en unidades de fomento",
    ("POL2", 7, 0): "la compania reembolsara los gastos medicos razonables",
}


def _hybrid_docs() -> list[Document]:
    return [
        Document(
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
        for (poliza, articulo, chunk_index), text in HYBRID_TEXTS.items()
    ]


@pytest.fixture
def hybrid_setup(
    client: QdrantClient, embeddings: DeterministicFakeEmbedding
) -> tuple:
    docs = _hybrid_docs()
    store = get_vector_store("c", embeddings=embeddings, client=client)
    store.add_documents(docs)
    return store, BM25Index(docs)


def test_hybrid_devuelve_el_shape_del_contrato_y_colapsa(hybrid_setup: tuple) -> None:
    store, index = hybrid_setup
    query = HYBRID_TEXTS[("POL1", 2, 0)]
    hits = hybrid_search(query, top_k=5, store=store, bm25_index=index, dense_floor=None)

    assert hits[0]["page_content"] == query  # 1.º denso (coseno 1) y 1.º BM25
    assert hits[0]["score"] == pytest.approx(1.0)
    for hit in hits:
        assert set(hit) == {"page_content", "metadata", "score"}
        assert not any(key.startswith("_") for key in hit["metadata"])
    # Los 2 chunks de POL1 · Art. 2 matchean "carencia": queda uno solo.
    assert _ids(hits).count(("POL1", 2)) == 1
    assert len(set(_ids(hits))) == len(hits)
    assert [h["score"] for h in hits] == sorted((h["score"] for h in hits), reverse=True)


def test_hybrid_piso_semantico_descarta_chunks_solo_lexicos(hybrid_setup: tuple) -> None:
    store, index = hybrid_setup
    query = HYBRID_TEXTS[("POL1", 5, 0)]  # coseno 1 consigo mismo, ~0 con el resto
    # "dias" tambien esta en POL1 · Art. 2: BM25 lo trae aunque no sea semantico.
    sin_piso = hybrid_search(query, top_k=5, store=store, bm25_index=index, dense_floor=None)
    con_piso = hybrid_search(query, top_k=5, store=store, bm25_index=index, dense_floor=0.99)

    assert ("POL1", 2) in _ids(sin_piso)
    assert _ids(con_piso) == [("POL1", 5)]
    assert con_piso[0]["score"] == pytest.approx(1.0)


def test_hybrid_sin_nada_sobre_el_piso_devuelve_vacio(hybrid_setup: tuple) -> None:
    store, index = hybrid_setup
    hits = hybrid_search(
        "carencia", top_k=5, store=store, bm25_index=index, dense_floor=1.01
    )
    assert hits == []


def test_search_hybrid_usa_umbral_denso_como_piso(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, index = hybrid_setup
    monkeypatch.setenv("UMBRAL_SCORE", "0.99")
    query = HYBRID_TEXTS[("POL1", 5, 0)]
    hits = search(query, top_k=5, store=store, mode="hybrid", bm25_index=index)
    assert _ids(hits) == [("POL1", 5)]


def test_retrieval_mode_del_entorno_activa_el_hibrido(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, index = hybrid_setup
    calls: list[dict] = []

    def spy(query: str, top_k: int, **kwargs) -> list[dict]:
        calls.append({"top_k": top_k, **kwargs})
        return []

    monkeypatch.setattr(vectordb_module, "hybrid_search", spy)
    search("carencia", top_k=3, store=store, bm25_index=index)
    assert calls == []  # default: dense

    monkeypatch.setenv("RETRIEVAL_MODE", "HYBRID")
    search("carencia", top_k=3, store=store, bm25_index=index)
    assert len(calls) == 1
    assert calls[0]["top_k"] == 3
    assert calls[0]["bm25_index"] is index
    assert calls[0]["dense_floor"] == pytest.approx(0.60)


def test_modo_explicito_pisa_al_del_entorno(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, index = hybrid_setup
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(
        vectordb_module, "hybrid_search", lambda *a, **k: pytest.fail("no debia fusionar")
    )
    query = HYBRID_TEXTS[("POL2", 7, 0)]
    [top, *_] = search(query, top_k=2, store=store, mode="dense", bm25_index=index)
    assert top["score"] == pytest.approx(1.0, abs=1e-6)  # coseno, no RRF


def test_search_hybrid_sin_indice_usa_el_de_chunks_jsonl(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, index = hybrid_setup
    monkeypatch.setattr(vectordb_module, "get_bm25_index", lambda: index)
    hits = search(HYBRID_TEXTS[("POL2", 2, 0)], top_k=1, store=store, mode="hybrid")
    assert _ids(hits) == [("POL2", 2)]


def test_search_hybrid_sin_chunks_jsonl_falla_claro(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = hybrid_setup

    def missing() -> BM25Index:
        raise FileNotFoundError("No existe data/processed/chunks.jsonl")

    monkeypatch.setattr(vectordb_module, "get_bm25_index", missing)
    with pytest.raises(FileNotFoundError, match="chunks.jsonl"):
        search("carencia", store=store, mode="hybrid")


@pytest.mark.parametrize("mode", ["sparse", "bm25"])
def test_modo_no_soportado_falla(
    hybrid_setup: tuple, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    store, index = hybrid_setup
    with pytest.raises(ValueError, match="no soportado"):
        search("carencia", store=store, mode=mode, bm25_index=index)
    monkeypatch.setenv("RETRIEVAL_MODE", mode)
    with pytest.raises(ValueError, match="no soportado"):
        search("carencia", store=store, bm25_index=index)

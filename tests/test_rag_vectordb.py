"""Tests unitarios de la capa vectorial con Qdrant en memoria y embeddings falsos.

No necesitan Docker ni Ollama. La prueba con el modelo real esta en
scripts/test_vectordb.py.
"""

from collections.abc import Iterator

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient, models

from app.rag.embeddings import get_embedding_dim
from app.rag.vectordb import (
    colapsar_por_articulo,
    ensure_collection,
    get_vector_store,
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

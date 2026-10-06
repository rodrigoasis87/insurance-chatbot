"""Tests unitarios de la capa vectorial con Qdrant en memoria y embeddings falsos.

No necesitan Docker ni Ollama. La prueba con el modelo real esta en
scripts/test_vectordb.py.
"""

from collections.abc import Iterator

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from qdrant_client import QdrantClient, models

from app.rag.embeddings import get_embedding_dim
from app.rag.vectordb import ensure_collection, get_vector_store, search

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

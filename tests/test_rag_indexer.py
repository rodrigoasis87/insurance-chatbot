"""Tests unitarios del index build: lectura de chunks.jsonl e indexado idempotente."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.rag.indexer import build_index, chunk_point_id, load_chunks
from app.rag.vectordb import get_vector_store


def make_chunk(articulo: int = 2, chunk_index: int = 0, **meta: Any) -> dict[str, Any]:
    metadata = {
        "poliza": "POL320130223",
        "ramo": "salud",
        "año": "2013",
        "articulo": articulo,
        "titulo_canonico": "cobertura",
        "pagina": 1,
        "chunk_index": chunk_index,
    }
    metadata.update(meta)
    return {
        "page_content": f"texto art {articulo} chunk {chunk_index}",
        "metadata": metadata,
    }


def to_line(item: Any) -> str:
    """Un dict se escribe como JSON; un str tal cual (sirve para lineas rotas)."""
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def write_jsonl(path: Path, items: list[Any]) -> Path:
    path.write_text("\n".join(to_line(i) for i in items) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def store() -> Iterator[QdrantVectorStore]:
    client = QdrantClient(":memory:")
    yield get_vector_store(
        "c", embeddings=DeterministicFakeEmbedding(size=16), client=client
    )
    client.close()


def test_load_chunks_reads_every_line_and_keeps_metadata(tmp_path: Path) -> None:
    chunks = [
        make_chunk(chunk_index=0),
        make_chunk(chunk_index=1),
        make_chunk(articulo=3),
    ]
    path = write_jsonl(tmp_path / "chunks.jsonl", [*chunks, ""])  # linea vacia ignorada

    docs = load_chunks(path)

    assert [d.page_content for d in docs] == [c["page_content"] for c in chunks]
    assert [d.metadata for d in docs] == [c["metadata"] for c in chunks]


def test_load_chunks_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        json.dumps(make_chunk(), ensure_ascii=False) + "\n", encoding="utf-8-sig"
    )
    assert len(load_chunks(path)) == 1


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("{no es json", "JSON invalido"),
        ({"metadata": make_chunk()["metadata"]}, "page_content"),
        ({"page_content": "x"}, "metadata"),
        (make_chunk(articulo="2"), "articulo"),  # tipo incorrecto
        (make_chunk(año=2013), "año"),  # contrato: año es str
        (make_chunk(pagina=True), "pagina"),  # bool no cuenta como int
    ],
)
def test_load_chunks_reports_the_bad_line(
    tmp_path: Path, line: Any, error: str
) -> None:
    path = write_jsonl(tmp_path / "chunks.jsonl", [make_chunk(), line])
    with pytest.raises(ValueError, match=rf"linea 2: .*{error}"):
        load_chunks(path)


def test_load_chunks_rejects_duplicated_chunk(tmp_path: Path) -> None:
    path = write_jsonl(tmp_path / "chunks.jsonl", [make_chunk(), make_chunk()])
    with pytest.raises(ValueError, match="linea 2: chunk repetido"):
        load_chunks(path)


def test_load_chunks_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="#7"):
        load_chunks(tmp_path / "no-existe.jsonl")


def test_point_id_is_deterministic_and_unique() -> None:
    a = make_chunk()["metadata"]
    assert chunk_point_id(a) == chunk_point_id(dict(a))
    assert chunk_point_id(a) != chunk_point_id({**a, "chunk_index": 1})


def test_build_index_is_idempotent(tmp_path: Path, store: QdrantVectorStore) -> None:
    chunks = [make_chunk(chunk_index=i) for i in range(5)]
    path = write_jsonl(tmp_path / "chunks.jsonl", chunks)

    assert build_index(path, store=store, batch_size=2) == 5
    assert build_index(path, store=store, batch_size=2) == 5  # segunda corrida

    assert store.client.count("c", exact=True).count == 5

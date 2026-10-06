"""Tests de los prefijos de tarea de los embeddings (sin Ollama: cliente falso)."""

import asyncio
from typing import Any

import pytest

from app.rag.embeddings import get_embeddings, task_prefixes


class FakeOllamaClient:
    """Imita ``ollama.Client.embed`` y guarda los textos que recibe."""

    def __init__(self) -> None:
        self.received: list[str] = []

    def embed(self, model: str, texts: list[str], **_: Any) -> dict[str, Any]:
        self.received.extend(texts)
        return {"embeddings": [[0.1, 0.2, 0.3] for _ in texts]}


class FakeAsyncOllamaClient(FakeOllamaClient):
    async def embed(self, model: str, texts: list[str], **_: Any) -> dict[str, Any]:  # type: ignore[override]
        return super().embed(model, texts)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)


def with_fake_clients(model: str) -> tuple[Any, FakeOllamaClient, FakeOllamaClient]:
    emb = get_embeddings(model)
    sync_client, async_client = FakeOllamaClient(), FakeAsyncOllamaClient()
    emb._client = sync_client  # type: ignore[assignment]
    emb._async_client = async_client  # type: ignore[assignment]
    return emb, sync_client, async_client


def test_nomic_uses_query_and_document_prefixes() -> None:
    emb, client, _ = with_fake_clients("nomic-embed-text")

    emb.embed_documents(["Este seguro no cubre cirugías estéticas."])
    emb.embed_query("¿Cubre una cirugía estética?")

    assert client.received == [
        "search_document: Este seguro no cubre cirugías estéticas.",
        "search_query: ¿Cubre una cirugía estética?",  # sin prefijo de documento
    ]


def test_async_methods_use_the_same_prefixes() -> None:
    emb, _, client = with_fake_clients("nomic-embed-text")

    asyncio.run(emb.aembed_documents(["doc"]))
    asyncio.run(emb.aembed_query("pregunta"))

    assert client.received == ["search_document: doc", "search_query: pregunta"]


def test_model_tag_is_ignored_when_matching_prefixes() -> None:
    assert task_prefixes("nomic-embed-text:latest") == task_prefixes("nomic-embed-text")


def test_unknown_model_has_no_prefixes() -> None:
    emb, client, _ = with_fake_clients("bge-m3")

    emb.embed_documents(["doc"])
    emb.embed_query("pregunta")

    assert client.received == ["doc", "pregunta"]


def test_default_model_is_qwen3_embedding() -> None:
    emb = get_embeddings()
    assert emb.model == "qwen3-embedding:0.6b"
    assert emb.query_prefix.startswith("Instruct: ")
    assert emb.document_prefix == ""


def test_qwen3_adds_the_instruction_only_to_questions() -> None:
    emb, client, _ = with_fake_clients("qwen3-embedding:0.6b")

    emb.embed_documents(["Este seguro no cubre cirugías estéticas."])
    emb.embed_query("¿Cubre una cirugía estética?")

    assert client.received[0] == "Este seguro no cubre cirugías estéticas."
    assert client.received[1].startswith("Instruct: ")
    assert client.received[1].endswith("\nQuery: ¿Cubre una cirugía estética?")

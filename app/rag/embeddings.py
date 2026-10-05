"""Modelo de embeddings local via Ollama (Issue #9).

Los embeddings son SIEMPRE locales y no dependen de ``LLM_PROVIDER``: cambiar
el LLM a OpenAI no debe obligar a reindexar la base vectorial (cada modelo de
embeddings produce vectores de distinta dimension).

Algunos modelos necesitan un prefijo de tarea distinto para la pregunta y para
el documento. ``qwen3-embedding`` (el default) usa una instruccion solo en la
pregunta; ``nomic-embed-text`` exige "search_query: " y "search_document: ".
Cambiar modelo o prefijos cambia los vectores: hay que reindexar con
``--recreate``.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings

from app.rag.config import get_settings

_DIM_PROBE_TEXT = "dimension probe"

# (prefijo de la pregunta, prefijo del documento) segun el model card de cada modelo.
TASK_PREFIXES: dict[str, tuple[str, str]] = {
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "mxbai-embed-large": (
        "Represent this sentence for searching relevant passages: ",
        "",
    ),
    "qwen3-embedding": (
        "Instruct: Given a question about an insurance policy, "
        "retrieve the policy clauses that answer it\nQuery: ",
        "",
    ),
}


class PrefixedOllamaEmbeddings(OllamaEmbeddings):
    """``OllamaEmbeddings`` que antepone un prefijo a preguntas y documentos."""

    query_prefix: str = ""
    document_prefix: str = ""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embebe los chunks con el prefijo de documento del modelo."""
        return super().embed_documents([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        """Embebe una pregunta con el prefijo de pregunta del modelo."""
        # Se llama a la clase base para no sumar tambien el prefijo de documento.
        return super().embed_documents([self.query_prefix + text])[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """Version async de ``embed_documents``."""
        return await super().aembed_documents([self.document_prefix + t for t in texts])

    async def aembed_query(self, text: str) -> list[float]:
        """Version async de ``embed_query``."""
        return (await super().aembed_documents([self.query_prefix + text]))[0]


def task_prefixes(model: str) -> tuple[str, str]:
    """Prefijos (pregunta, documento) del modelo; ``("", "")`` si no necesita."""
    # "nomic-embed-text:latest" -> "nomic-embed-text"
    base_name = model.split(":", 1)[0]
    return TASK_PREFIXES.get(base_name, ("", ""))


def get_embeddings(
    model: str | None = None, *, validate: bool = False
) -> PrefixedOllamaEmbeddings:
    """Crea el cliente de embeddings de Ollama, con los prefijos del modelo.

    Args:
        model: nombre del modelo en Ollama. Por defecto ``EMBEDDING_MODEL``
            del ``.env`` (``qwen3-embedding:0.6b``).
        validate: si es ``True``, verifica al crear el cliente que Ollama
            responde y que el modelo ya fue descargado (``ollama pull``).

    Raises:
        ValueError: con ``validate=True``, si Ollama no responde o el modelo
            no esta disponible.
    """
    settings = get_settings()
    name = model or settings.embedding_model
    query_prefix, document_prefix = task_prefixes(name)
    return PrefixedOllamaEmbeddings(
        model=name,
        base_url=settings.ollama_base_url,
        validate_model_on_init=validate,
        query_prefix=query_prefix,
        document_prefix=document_prefix,
    )


def get_embedding_dim(embeddings: Embeddings | None = None) -> int:
    """Devuelve la dimension real de los vectores del modelo de embeddings.

    Se calcula embebiendo un texto de prueba, en lugar de hardcodear el valor
    (1024 para ``qwen3-embedding:0.6b``, 768 para ``nomic-embed-text``), para que
    cambiar de modelo nunca rompa la coleccion en silencio.
    """
    embeddings = embeddings or get_embeddings()
    vector = embeddings.embed_query(_DIM_PROBE_TEXT)
    if not vector:
        raise RuntimeError("El modelo de embeddings devolvio un vector vacio.")
    return len(vector)

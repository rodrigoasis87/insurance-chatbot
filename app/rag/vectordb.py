"""Base vectorial (Qdrant en docker compose) y busqueda por similitud (Issue #9).

Contrato: docs/CONTRACTS.md seccion 2.

* Coleccion ``polizas``, distancia Cosine, dimension = la del modelo de
  embeddings (1024 con ``qwen3-embedding:0.6b``).
* ``search()`` devuelve ``page_content``, ``metadata`` y ``score``, con a lo
  sumo un hit por ``(poliza, articulo)`` (colapsa la copia embebida).

Ojo: con coseno, Qdrant devuelve un score de SIMILITUD (mas alto = mas
parecido), no una distancia como Chroma.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.rag.config import get_settings
from app.rag.embeddings import get_embedding_dim, get_embeddings

DISTANCE = models.Distance.COSINE

# Campos de metadata con indice para filtrar rapido (recomendacion del EDA, #3).
# langchain-qdrant guarda la metadata bajo la clave "metadata" del payload.
KEYWORD_INDEX_FIELDS = ("poliza", "ramo", "titulo_canonico")


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    """Devuelve un cliente Qdrant unico por proceso (``QDRANT_URL``).

    Raises:
        ConnectionError: si Qdrant no responde.
    """
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url, timeout=10)
    try:
        client.get_collections()
    except Exception as exc:
        raise ConnectionError(
            f"No se pudo conectar a Qdrant en {settings.qdrant_url}. "
            "Levanta el servicio con: docker compose up -d qdrant"
        ) from exc
    return client


def _get_dense_params(
    client: QdrantClient, collection_name: str
) -> models.VectorParams:
    """Lee la configuracion del vector (sin nombre) de una coleccion existente."""
    vectors = client.get_collection(collection_name).config.params.vectors
    if not isinstance(vectors, models.VectorParams):
        raise ValueError(
            f"La coleccion {collection_name!r} usa vectores con nombre; "
            "se esperaba un unico vector sin nombre."
        )
    return vectors


def ensure_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
    *,
    recreate: bool = False,
    payload_indexes: bool = True,
) -> bool:
    """Crea la coleccion con la dimension y distancia correctas si no existe.

    Args:
        client: cliente Qdrant.
        collection_name: nombre de la coleccion.
        vector_size: dimension de los vectores (usar ``get_embedding_dim()``).
        recreate: si es ``True``, borra la coleccion existente y la crea de nuevo.
        payload_indexes: crea indices keyword sobre ``KEYWORD_INDEX_FIELDS``.

    Returns:
        ``True`` si la coleccion se creo, ``False`` si ya existia.

    Raises:
        ValueError: si la coleccion existe con otra dimension o distancia.
            Pasa si se cambia ``EMBEDDING_MODEL`` sin reindexar.
    """
    exists = client.collection_exists(collection_name)

    if exists and recreate:
        client.delete_collection(collection_name)
        exists = False

    if exists:
        params = _get_dense_params(client, collection_name)
        if params.size != vector_size or params.distance != DISTANCE:
            raise ValueError(
                f"La coleccion {collection_name!r} existe con size={params.size} y "
                f"distance={params.distance}, pero se esperaba size={vector_size} y "
                f"distance={DISTANCE}. Probablemente cambio EMBEDDING_MODEL: "
                "recrea la coleccion (recreate=True) y vuelve a indexar."
            )
        return False

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=vector_size, distance=DISTANCE),
    )
    if payload_indexes:
        for field in KEYWORD_INDEX_FIELDS:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=f"{QdrantVectorStore.METADATA_KEY}.{field}",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
    return True


def get_vector_store(
    collection_name: str | None = None,
    *,
    embeddings: Embeddings | None = None,
    client: QdrantClient | None = None,
    recreate: bool = False,
) -> QdrantVectorStore:
    """Devuelve el vector store de LangChain listo para insertar y buscar.

    Crea la coleccion si hace falta, con la dimension real del modelo de
    embeddings. Lo usa el index build (``app.rag.indexer``).

    Args:
        collection_name: por defecto ``QDRANT_COLLECTION`` del ``.env``.
        embeddings: por defecto ``get_embeddings()`` (Ollama).
        client: por defecto ``get_client()``. Util para inyectar uno en tests.
        recreate: borra y recrea la coleccion (se pierden los datos).
    """
    settings = get_settings()
    name = collection_name or settings.qdrant_collection
    embeddings = embeddings or get_embeddings()
    client = client or get_client()

    ensure_collection(client, name, get_embedding_dim(embeddings), recreate=recreate)
    return QdrantVectorStore(
        client=client,
        collection_name=name,
        embedding=embeddings,
        distance=DISTANCE,
    )


@lru_cache(maxsize=1)
def _get_search_store() -> QdrantVectorStore:
    """Vector store de solo lectura para ``search()``, creado una vez por proceso.

    Raises:
        RuntimeError: si la coleccion todavia no fue indexada.
    """
    settings = get_settings()
    client = get_client()
    if not client.collection_exists(settings.qdrant_collection):
        raise RuntimeError(
            f"La coleccion {settings.qdrant_collection!r} no existe. "
            "Genera el indice con: uv run python -m app.rag.indexer"
        )
    return QdrantVectorStore(
        client=client,
        collection_name=settings.qdrant_collection,
        embedding=get_embeddings(),
        distance=DISTANCE,
    )


def colapsar_por_articulo(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Conserva un solo hit por ``(poliza, articulo)``: el de mayor score.

    El corpus trae el mismo articulo mas de una vez en dos casos: (1) la copia
    embebida de ``POL320130223`` (doc1/doc3 dentro de ``POL320190074.pdf``, ver
    CONTRACTS 1.1) y (2) un articulo largo partido en varios chunks. En ambos,
    repetir el mismo articulo en el top_k no aporta contexto y le roba un lugar
    a otro articulo. Articulos de polizas distintas nunca se colapsan aunque
    tengan el mismo numero: la cita (poliza + pagina) es distinta.

    Preserva el orden descendente de ``score``.
    """
    best: dict[tuple[str, int], dict[str, Any]] = {}
    for hit in results:
        meta = hit["metadata"]
        key = (meta["poliza"], meta["articulo"])
        actual = best.get(key)
        if actual is None or hit["score"] > actual["score"]:
            best[key] = hit
    return sorted(best.values(), key=lambda h: h["score"], reverse=True)


def search(
    query: str, top_k: int = 5, *, store: QdrantVectorStore | None = None
) -> list[dict[str, Any]]:
    """Busca los ``top_k`` articulos mas parecidos a ``query`` (similitud coseno).

    Args:
        query: pregunta en lenguaje natural.
        top_k: cantidad de articulos unicos a devolver.
        store: vector store a usar. Por defecto la coleccion ``polizas``.

    Returns:
        Lista ordenada por score descendente, con a lo sumo un hit por
        ``(poliza, articulo)`` (ver :func:`colapsar_por_articulo`). Cada item:
        ``{"page_content": str, "metadata": {...contrato 1.2...}, "score": float}``.
    """
    if not query.strip():
        raise ValueError("La consulta esta vacia.")
    store = store or _get_search_store()
    # Se piden el doble de candidatos: el colapso por (poliza, articulo) puede
    # descartar varios, y asi se devuelven top_k articulos distintos igualmente.
    results = store.similarity_search_with_score(query, k=top_k * 2)
    hits = [
        {
            "page_content": doc.page_content,
            # langchain-qdrant agrega "_id" y "_collection_name": no son del contrato.
            "metadata": {
                k: v for k, v in doc.metadata.items() if not k.startswith("_")
            },
            "score": float(score),
        }
        for doc, score in results
    ]
    return colapsar_por_articulo(hits)[:top_k]

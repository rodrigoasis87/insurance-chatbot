"""Base vectorial (Qdrant en docker compose) y busqueda por similitud (Issue #9).

Contrato: docs/CONTRACTS.md seccion 2.

* Coleccion ``polizas``, distancia Cosine, dimension = la del modelo de
  embeddings (1024 con ``qwen3-embedding:0.6b``).
* ``search()`` devuelve ``page_content``, ``metadata`` y ``score``, con a lo
  sumo un hit por ``(poliza, articulo)`` (colapsa la copia embebida).
* ``RETRIEVAL_MODE`` (#42): ``dense`` (default) busca solo por embeddings;
  ``hybrid`` fusiona el ranking denso con el lexico BM25 (``app.rag.bm25``)
  via Reciprocal Rank Fusion (:func:`rrf_fuse`). El shape y el colapso no
  cambian; en ``hybrid`` el ``score`` es el RRF normalizado a ``[0, 1]``.

Ojo: con coseno, Qdrant devuelve un score de SIMILITUD (mas alto = mas
parecido), no una distancia como Chroma.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from app.rag.bm25 import BM25Index, chunk_key, get_bm25_index
from app.rag.config import SUPPORTED_RETRIEVAL_MODES, get_settings
from app.rag.embeddings import get_embedding_dim, get_embeddings

DISTANCE = models.Distance.COSINE

# Campos de metadata con indice para filtrar rapido (recomendacion del EDA, #3).
# langchain-qdrant guarda la metadata bajo la clave "metadata" del payload.
KEYWORD_INDEX_FIELDS = ("poliza", "ramo", "titulo_canonico")

# Constante k de RRF (Cormack, Clarke y Buettcher, SIGIR 2009): 60 es el valor
# del paper y el default de Elasticsearch/OpenSearch/Qdrant.
RRF_K = 60

# En modo hibrido cada retriever aporta top_k * HYBRID_CANDIDATES_FACTOR
# candidatos (20 con top_k=5): la fusion necesita listas mas profundas que el
# top_k final para que un chunk bien rankeado por un solo retriever compita, y
# el colapso por (poliza, articulo) descarta varios.
HYBRID_CANDIDATES_FACTOR = 4

SearchHit = dict[str, Any]


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


def rrf_fuse(
    rankings: Sequence[Sequence[SearchHit]],
    *,
    k: int = RRF_K,
    key: Callable[[SearchHit], Any] = lambda hit: chunk_key(hit["metadata"]),
) -> list[SearchHit]:
    """Fusiona rankings con Reciprocal Rank Fusion, con score normalizado.

    Cada hit suma ``1 / (k + rank)`` por cada ranking en el que aparece (rank
    1-based); se ignora el ``score`` original de cada retriever, que vive en
    escalas incomparables (coseno vs. BM25). La suma se divide por el maximo
    posible, ``len(rankings) / (k + 1)``, asi el score queda en ``(0, 1]``:
    ``1.0`` = primero en todos los rankings; ``0.5`` (con 2 rankings) = primero
    en uno solo y ausente del otro.

    Args:
        rankings: listas de hits ``{page_content, metadata, score}`` ordenadas
            de mejor a peor (p. ej. ``[denso, bm25]``). Pueden estar vacias.
        k: constante de suavizado de RRF (``RRF_K``).
        key: identidad del hit para reconocerlo entre rankings. Por defecto el
            chunk ``(poliza, documento, articulo, chunk_index)``.

    Returns:
        Hits unicos por ``key``, ordenados por score fusionado descendente (a
        igual score, el mejor rank individual). Cada hit conserva el
        ``page_content`` y la ``metadata`` de la primera lista donde aparece.

    Raises:
        ValueError: si ``k`` es negativo.
    """
    if k < 0:
        raise ValueError("k de RRF debe ser >= 0")
    if not rankings:
        return []
    max_score = len(rankings) / (k + 1)
    fused: dict[Any, SearchHit] = {}
    raw: dict[Any, float] = {}
    best_rank: dict[Any, int] = {}
    for ranking in rankings:
        seen: set[Any] = set()
        for rank, hit in enumerate(ranking, start=1):
            hit_key = key(hit)
            if hit_key in seen:  # el mismo chunk dos veces en una lista: cuenta una
                continue
            seen.add(hit_key)
            raw[hit_key] = raw.get(hit_key, 0.0) + 1.0 / (k + rank)
            best_rank[hit_key] = min(best_rank.get(hit_key, rank), rank)
            fused.setdefault(
                hit_key,
                {"page_content": hit["page_content"], "metadata": hit["metadata"]},
            )
    ordered = sorted(fused, key=lambda hk: (-raw[hk], best_rank[hk]))
    return [{**fused[hk], "score": raw[hk] / max_score} for hk in ordered]


def _dense_hits(query: str, k: int, store: QdrantVectorStore) -> list[SearchHit]:
    """Top ``k`` chunks por similitud coseno en Qdrant, sin colapsar."""
    results = store.similarity_search_with_score(query, k=k)
    return [
        {
            "page_content": doc.page_content,
            # langchain-qdrant agrega "_id" y "_collection_name": no son del contrato.
            "metadata": {
                key: value
                for key, value in doc.metadata.items()
                if not key.startswith("_")
            },
            "score": float(score),
        }
        for doc, score in results
    ]


def _lexical_hits(query: str, k: int, index: BM25Index) -> list[SearchHit]:
    """Top ``k`` chunks por BM25 (score crudo), sin colapsar."""
    return [
        {
            "page_content": hit.document.page_content,
            "metadata": dict(hit.document.metadata),
            "score": hit.score,
        }
        for hit in index.search(query, k)
    ]


def _resolve_mode(mode: str | None) -> str:
    """Modo explicito o ``RETRIEVAL_MODE`` del entorno, validado."""
    resolved = (mode or get_settings().retrieval_mode).strip().lower()
    if resolved not in SUPPORTED_RETRIEVAL_MODES:
        raise ValueError(
            f"RETRIEVAL_MODE={resolved!r} no soportado; "
            f"usa uno de {SUPPORTED_RETRIEVAL_MODES}."
        )
    return resolved


def hybrid_search(
    query: str,
    top_k: int = 5,
    *,
    store: QdrantVectorStore,
    bm25_index: BM25Index,
    dense_floor: float | None,
    k: int = RRF_K,
) -> list[SearchHit]:
    """Busqueda hibrida: ranking denso + ranking BM25 fusionados con RRF.

    1. Qdrant devuelve los ``top_k * HYBRID_CANDIDATES_FACTOR`` chunks mas
       parecidos (coseno) y BM25 otros tantos por coincidencia lexica.
    2. **Piso semantico** (``dense_floor``): solo son elegibles los chunks del
       ranking denso con coseno ``>= dense_floor``; los del ranking BM25 que no
       esten entre ellos se descartan. El score RRF depende solo de posiciones
       (es relativo a cada pregunta), asi que por si solo no distingue una
       pregunta ajena al corpus de una del dominio: este piso conserva el hard
       gate semantico de ADR-004 (ver docs/umbral_score.md §7). Con ``None``
       no hay piso y la fusion es la union pura de ambos rankings.
    3. :func:`rrf_fuse` (score en ``(0, 1]``) y colapso por ``(poliza, articulo)``.

    Args:
        query: pregunta en lenguaje natural (no vacia).
        top_k: cantidad de articulos unicos a devolver.
        store: vector store denso.
        bm25_index: indice lexico.
        dense_floor: coseno minimo para que un chunk sea elegible, o ``None``.
        k: constante de RRF.
    """
    n_candidates = top_k * HYBRID_CANDIDATES_FACTOR
    dense = _dense_hits(query, n_candidates, store)
    lexical = _lexical_hits(query, n_candidates, bm25_index)
    if dense_floor is not None:
        dense = [hit for hit in dense if hit["score"] >= dense_floor]
        eligible = {chunk_key(hit["metadata"]) for hit in dense}
        lexical = [hit for hit in lexical if chunk_key(hit["metadata"]) in eligible]
    return colapsar_por_articulo(rrf_fuse([dense, lexical], k=k))[:top_k]


def search(
    query: str,
    top_k: int = 5,
    *,
    store: QdrantVectorStore | None = None,
    mode: str | None = None,
    bm25_index: BM25Index | None = None,
) -> list[SearchHit]:
    """Busca los ``top_k`` articulos mas relevantes para ``query``.

    * ``dense`` (default): similitud coseno en Qdrant; ``score`` = coseno. El
      hard gate ``UMBRAL_SCORE`` lo aplica despues ``query()``.
    * ``hybrid``: ranking denso + BM25 fusionados con RRF
      (:func:`hybrid_search`); ``score`` = RRF normalizado a ``(0, 1]``. Usa
      ``UMBRAL_SCORE`` como piso semantico antes de fusionar, y ``query()``
      aplica ``UMBRAL_SCORE_HYBRID`` sobre el score fusionado.

    En ambos modos se colapsa por ``(poliza, articulo)`` despues de rankear, asi
    que el contrato de CONTRACTS §2 no cambia.

    Args:
        query: pregunta en lenguaje natural.
        top_k: cantidad de articulos unicos a devolver.
        store: vector store a usar. Por defecto la coleccion ``polizas``.
        mode: ``"dense"`` o ``"hybrid"``. Por defecto ``RETRIEVAL_MODE``.
        bm25_index: indice lexico (solo ``hybrid``). Por defecto el de
            ``data/processed/chunks.jsonl``, construido una vez por proceso.

    Returns:
        Lista ordenada por score descendente, con a lo sumo un hit por
        ``(poliza, articulo)`` (ver :func:`colapsar_por_articulo`). Cada item:
        ``{"page_content": str, "metadata": {...contrato 1.2...}, "score": float}``.

    Raises:
        ValueError: consulta vacia o modo no soportado.
        FileNotFoundError: modo ``hybrid`` sin ``chunks.jsonl`` para BM25.
    """
    if not query.strip():
        raise ValueError("La consulta esta vacia.")
    resolved = _resolve_mode(mode)
    store = store or _get_search_store()
    if resolved == "hybrid":
        return hybrid_search(
            query,
            top_k,
            store=store,
            bm25_index=bm25_index or get_bm25_index(),
            dense_floor=get_settings().umbral_score_dense,
        )
    # Se piden el doble de candidatos: el colapso por (poliza, articulo) puede
    # descartar varios, y asi se devuelven top_k articulos distintos igualmente.
    return colapsar_por_articulo(_dense_hits(query, top_k * 2, store))[:top_k]

"""Index build (Issue #9): ``chunks.jsonl`` -> embeddings -> Qdrant.

Entrada: ``data/processed/chunks.jsonl`` (salida de #7, docs/CONTRACTS.md 1.2).
Una linea JSON por chunk, en formato ``Document`` de LangChain::

    {"page_content": "...fragmento...",
     "metadata": {"poliza": "POL320130223", "ramo": "salud", "año": "2013",
                  "articulo": 2, "titulo_canonico": "cobertura",
                  "pagina": 1, "chunk_index": 0}}

Uso:
    uv run python -m app.rag.indexer              # indexa data/processed/chunks.jsonl
    uv run python -m app.rag.indexer --recreate   # borra la coleccion y reindexa
    uv run python -m app.rag.indexer --path otro/chunks.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from tqdm import tqdm

from app.paths import CHUNKS_JSONL
from app.rag.config import get_settings
from app.rag.vectordb import get_client, get_vector_store

# Campos obligatorios de la metadata de cada chunk y su tipo (contrato 1.2).
CHUNK_METADATA_FIELDS: dict[str, type] = {
    "poliza": str,
    "ramo": str,
    "año": str,
    "articulo": int,
    "titulo_canonico": str,
    "pagina": int,
    "chunk_index": int,
}

# Chunks que se embeben e insertan por vuelta. En CPU, lotes chicos dan
# progreso visible y no cargan de golpe todo el corpus en memoria de Ollama.
DEFAULT_BATCH_SIZE = 32


def chunk_point_id(metadata: dict[str, Any]) -> str:
    """ID deterministico del punto en Qdrant: ``uuid5("POLIZA|articulo|chunk_index")``.

    El mismo chunk siempre recibe el mismo ID, asi re-correr el index build
    reemplaza los puntos en lugar de duplicarlos (docs/CONTRACTS.md 2).
    """
    key = f"{metadata['poliza']}|{metadata['articulo']}|{metadata['chunk_index']}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _to_document(record: Any, line_no: int) -> Document:
    """Valida una linea de ``chunks.jsonl`` contra el contrato 1.2."""
    if not isinstance(record, dict):
        raise ValueError(f"linea {line_no}: se esperaba un objeto JSON")

    text = record.get("page_content")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"linea {line_no}: 'page_content' falta o esta vacio")

    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"linea {line_no}: 'metadata' falta o no es un objeto")

    for field, expected in CHUNK_METADATA_FIELDS.items():
        value = metadata.get(field)
        # En Python True/False tambien son int: no los aceptamos como numero.
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ValueError(
                f"linea {line_no}: metadata[{field!r}] debe ser "
                f"{expected.__name__}, llego {value!r}"
            )

    return Document(page_content=text, metadata=metadata)


def load_chunks(path: Path = CHUNKS_JSONL) -> list[Document]:
    """Lee ``chunks.jsonl`` y devuelve un ``Document`` por linea.

    Valida cada linea contra el contrato 1.2 y corta en el primer error,
    indicando el numero de linea. Ignora lineas vacias.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: JSON invalido, campos faltantes o de otro tipo, chunks
            repetidos (misma poliza + articulo + chunk_index) o archivo vacio.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Generalo primero con el chunking de #7."
        )

    documents: list[Document] = []
    first_seen: dict[str, int] = {}
    # utf-8-sig: lee bien el archivo aunque un editor de Windows le agregue BOM.
    with path.open(encoding="utf-8-sig") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"linea {line_no}: JSON invalido ({exc.msg})") from exc

            doc = _to_document(record, line_no)
            point_id = chunk_point_id(doc.metadata)
            if point_id in first_seen:
                raise ValueError(
                    f"linea {line_no}: chunk repetido (poliza, articulo, chunk_index), "
                    f"ya aparece en la linea {first_seen[point_id]}"
                )
            first_seen[point_id] = line_no
            documents.append(doc)

    if not documents:
        raise ValueError(f"{path} no tiene chunks.")
    return documents


def build_index(
    path: Path = CHUNKS_JSONL,
    *,
    recreate: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    store: QdrantVectorStore | None = None,
) -> int:
    """Indexa ``chunks.jsonl`` en Qdrant: lee, embebe por lotes e inserta.

    Es idempotente: cada chunk tiene un ID fijo (``chunk_point_id``), asi que
    correrlo dos veces no duplica puntos.

    Args:
        path: archivo de entrada. Por defecto ``data/processed/chunks.jsonl``.
        recreate: borra la coleccion antes de indexar. Usarlo cuando cambia el
            chunking o el modelo de embeddings. Se ignora si se pasa ``store``.
        batch_size: chunks por lote de embedding + insercion.
        store: vector store destino. Por defecto la coleccion ``polizas``.

    Returns:
        Cantidad de chunks indexados.
    """
    documents = load_chunks(path)
    store = store or get_vector_store(recreate=recreate)
    ids = [chunk_point_id(doc.metadata) for doc in documents]

    with tqdm(total=len(documents), desc="Indexando chunks", unit="chunk") as bar:
        for start in range(0, len(documents), batch_size):
            batch = documents[start : start + batch_size]
            store.add_documents(batch, ids=ids[start : start + batch_size])
            bar.update(len(batch))
    return len(documents)


def main(argv: list[str] | None = None) -> int:
    """CLI del index build: ``uv run python -m app.rag.indexer [--recreate]``.

    Returns:
        0 si indexo todo; 1 si el archivo falta, trae lineas invalidas o
        Qdrant no responde.
    """
    parser = argparse.ArgumentParser(description="Indexa chunks.jsonl en Qdrant (#9).")
    parser.add_argument("--path", type=Path, default=CHUNKS_JSONL)
    parser.add_argument(
        "--recreate", action="store_true", help="borra la coleccion y reindexa"
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)

    try:
        total = build_index(
            args.path, recreate=args.recreate, batch_size=args.batch_size
        )
    except (FileNotFoundError, ValueError, ConnectionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    collection = get_settings().qdrant_collection
    stored = get_client().count(collection, exact=True).count
    print(f"OK: {total} chunks indexados en la coleccion {collection!r}")
    if stored > total:
        print(
            f"Aviso: la coleccion tiene {stored} puntos y el archivo {total}. "
            "Quedan chunks de una corrida anterior: reindexa con --recreate."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

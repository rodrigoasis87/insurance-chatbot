"""Indice lexico BM25 sobre ``chunks.jsonl`` (Issue #42, busqueda hibrida).

Complementa la busqueda densa de Qdrant (``app.rag.vectordb``): los embeddings
capturan la semantica pero fallan con terminos literales del dominio
("carencia", "retracto", "deducible", codigos ``POL…``); BM25 los premia.

El indice se construye en memoria con ``rank_bm25.BM25Okapi`` a partir del mismo
``data/processed/chunks.jsonl`` que alimenta a Qdrant (contrato 1.2), asi que
no hace falta reindexar la coleccion ni cambiar su esquema. Con 758 chunks el
build tarda menos de un segundo y se hace una vez por proceso.

``rank_bm25`` no preprocesa texto: la tokenizacion (minusculas, sin tildes,
sin stopwords del espanol) vive en :func:`tokenize` y se aplica igual a los
chunks y a la pregunta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from app.paths import CHUNKS_JSONL

# Stopwords del espanol (sin tildes, porque se comparan ya normalizadas). Lista
# corta a proposito: solo palabras funcionales; terminos del rubro como
# "seguro", "poliza" o "asegurado" se quedan (BM25 ya les baja el peso por IDF).
STOPWORDS_ES: frozenset[str] = frozenset(
    {
        "a", "al", "algo", "algun", "alguna", "algunas", "alguno", "algunos", "ante",
        "antes", "aqui", "asi", "aun", "cada", "como", "con", "contra", "cual", "cuales",
        "cuando", "cuanto", "cuanta", "cuantos", "cuantas", "de", "del", "desde", "donde",
        "durante", "e", "el", "ella", "ellas", "ellos", "en", "entre", "era", "es", "esa",
        "esas", "ese", "eso", "esos", "esta", "estan", "estas", "este", "esto", "estos",
        "fue", "fueron", "ha", "han", "hasta", "hay", "la", "las", "le", "les", "lo",
        "los", "mas", "me", "mi", "mis", "muy", "ni", "no", "nos", "o", "otra", "otras",
        "otro", "otros", "para", "pero", "por", "porque", "que", "quien", "quienes", "se",
        "sea", "segun", "ser", "si", "sin", "sobre", "son", "su", "sus", "tambien", "te",
        "tiene", "tienen", "tengo", "tu", "tus", "un", "una", "unas", "uno", "unos", "y",
        "ya", "yo",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _sin_tildes(text: str) -> str:
    """Quita tildes y dieresis (``"póliza"`` -> ``"poliza"``); conserva la ``ñ``
    como ``n``, igual en chunks y preguntas."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    """Tokeniza para BM25: minusculas, sin tildes, alfanumerico, sin stopwords.

    Descarta tokens de un caracter (letras de incisos ``a)``, ``b)``…), que no
    aportan senal lexica.
    """
    tokens = _TOKEN_RE.findall(_sin_tildes(text.lower()))
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS_ES]


def chunk_key(metadata: dict[str, Any]) -> tuple[Any, ...]:
    """Identidad de un chunk: ``(poliza, documento, articulo, chunk_index)``.

    Es la misma clave del ``point_id`` del index build (CONTRACTS §2), asi un
    chunk recuperado por Qdrant y el mismo chunk recuperado por BM25 se
    reconocen como uno solo al fusionar los rankings.
    """
    return (
        metadata.get("poliza"),
        metadata.get("documento"),
        metadata.get("articulo"),
        metadata.get("chunk_index"),
    )


@dataclass(frozen=True)
class LexicalHit:
    """Un chunk recuperado por BM25 con su score crudo (no acotado)."""

    document: Document
    score: float


class BM25Index:
    """Indice BM25 en memoria sobre una lista de ``Document`` de LangChain."""

    def __init__(self, documents: list[Document]) -> None:
        """Construye el indice.

        Raises:
            ValueError: si no hay documentos (``BM25Okapi`` divide por el
                tamano del corpus).
        """
        if not documents:
            raise ValueError("No se puede construir un indice BM25 sin documentos.")
        self.documents: list[Document] = list(documents)
        self._bm25 = BM25Okapi([tokenize(doc.page_content) for doc in self.documents])

    def __len__(self) -> int:
        return len(self.documents)

    def search(self, query: str, k: int) -> list[LexicalHit]:
        """Devuelve hasta ``k`` chunks con score BM25 > 0, de mayor a menor.

        Los chunks sin ningun termino en comun con la pregunta (score 0) no se
        devuelven: no son evidencia lexica y no deben sumar en la fusion. Por
        eso una pregunta ajena al corpus puede devolver una lista vacia.
        """
        if k <= 0:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        scores = self._bm25.get_scores(terms)
        # Orden estable: a igual score gana el chunk que aparece antes en el archivo.
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [
            LexicalHit(self.documents[i], float(scores[i]))
            for i in order[:k]
            if scores[i] > 0
        ]


def build_bm25_index(path: Path = CHUNKS_JSONL) -> BM25Index:
    """Construye el indice BM25 leyendo y validando ``chunks.jsonl`` (contrato 1.2).

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el archivo es invalido o esta vacio.
    """
    # Import local: app.rag.indexer importa app.rag.vectordb, que a su vez
    # importa este modulo.
    from app.rag.indexer import load_chunks

    return BM25Index(load_chunks(path))


@lru_cache(maxsize=4)
def get_bm25_index(path: Path = CHUNKS_JSONL) -> BM25Index:
    """Indice BM25 de ``path``, construido una vez por proceso y reutilizado."""
    return build_bm25_index(Path(path))

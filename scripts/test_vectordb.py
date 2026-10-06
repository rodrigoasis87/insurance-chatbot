"""Prueba de infraestructura del Issue #9: chunks.jsonl -> Qdrant -> search().

Corre 100% local con chunks ficticios (no usa PDFs ni datos de otras celulas):

1. Verifica que Ollama (modelo de embeddings) y Qdrant respondan.
2. Escribe 4 chunks ficticios en un chunks.jsonl temporal (contrato 1.2).
3. Los indexa con el mismo camino que el real (``build_index``) en una
   coleccion temporal, dos veces, para probar que no duplica.
4. Valida ``search()``: top-1 esperado, score minimo y metadata intacta.
5. Hace un ping al LLM configurado en LLM_PROVIDER.

Sale con codigo 1 si algo falla.

Uso:
    uv run python scripts/test_vectordb.py
    uv run python scripts/test_vectordb.py --skip-llm --keep --min-score 0.4
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# El proyecto no se instala como paquete: agregamos la raiz al sys.path para
# poder correr "uv run python scripts/test_vectordb.py" desde la raiz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_qdrant import QdrantVectorStore  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

from app.rag.config import get_settings  # noqa: E402
from app.rag.embeddings import get_embedding_dim, get_embeddings  # noqa: E402
from app.rag.indexer import build_index  # noqa: E402
from app.rag.llm import get_llm  # noqa: E402
from app.rag.vectordb import get_client, get_vector_store, search  # noqa: E402

TEST_COLLECTION = "test_vectordb_mocks"
# Similitud coseno minima del top-1. Es orientativa: el valor absoluto depende
# del modelo de embeddings, por eso lo principal es el ranking.
DEFAULT_MIN_SCORE = 0.3


def _chunk(
    text: str,
    poliza: str,
    ramo: str,
    anio: str,
    articulo: int,
    titulo: str,
    pagina: int,
) -> dict[str, Any]:
    """Arma una linea de chunks.jsonl con el formato del contrato 1.2."""
    return {
        "page_content": text,
        "metadata": {
            "poliza": poliza,
            "ramo": ramo,
            "año": anio,
            "articulo": articulo,
            "titulo_canonico": titulo,
            "pagina": pagina,
            "chunk_index": 0,
        },
    }


MOCK_CHUNKS: list[dict[str, Any]] = [
    _chunk(
        "La compañía aseguradora reembolsará los gastos médicos razonables, "
        "acostumbrados y efectivamente incurridos por el asegurado en "
        "hospitalización, cirugía y atención ambulatoria, según los porcentajes "
        "y topes indicados en las Condiciones Particulares.",
        "POL320200071",
        "salud",
        "2020",
        2,
        "cobertura",
        2,
    ),
    _chunk(
        "Este seguro no cubre los gastos derivados de cirugías estéticas o "
        "cosméticas, tratamientos experimentales, curas de reposo ni "
        "enfermedades preexistentes no declaradas en la solicitud.",
        "POL320190074",
        "salud",
        "2019",
        4,
        "exclusiones",
        5,
    ),
    _chunk(
        "Durante los primeros 90 días de vigencia de la póliza no se cubrirán "
        "prestaciones. Para las prestaciones de maternidad y parto el período "
        "de carencia es de 10 meses.",
        "POL320210210",
        "salud",
        "2021",
        5,
        "carencia",
        4,
    ),
    _chunk(
        "Ocurrido un accidente, el asegurado o sus beneficiarios deberán dar "
        "aviso a la compañía dentro de un plazo de 30 días, presentando el "
        "formulario de denuncia, los certificados médicos y las boletas de los "
        "gastos.",
        "POL120190177",
        "accidentes",
        "2019",
        9,
        "denuncia de siniestro",
        7,
    ),
]

# (consulta, titulo_canonico que debe salir primero)
QUERIES: list[tuple[str, str]] = [
    ("¿Qué gastos médicos me reembolsa el seguro?", "cobertura"),
    ("¿La póliza cubre una cirugía estética?", "exclusiones"),
    ("¿Cuánto tiempo tengo que esperar para que me cubran un parto?", "carencia"),
    (
        "¿En qué plazo debo avisar un accidente a la aseguradora?",
        "denuncia de siniestro",
    ),
]


def write_mock_jsonl(folder: Path) -> Path:
    """Escribe los chunks ficticios como chunks.jsonl, igual que lo haria #7."""
    path = folder / "chunks.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for record in MOCK_CHUNKS:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def check_index(
    store: QdrantVectorStore, client: QdrantClient, path: Path
) -> list[str]:
    """Indexa el archivo dos veces: la segunda no debe duplicar puntos."""
    failures: list[str] = []
    for attempt in (1, 2):
        build_index(path, store=store)
        count = client.count(TEST_COLLECTION, exact=True).count
        if count != len(MOCK_CHUNKS):
            failures.append(
                f"index build #{attempt}: se esperaban {len(MOCK_CHUNKS)} puntos "
                f"y hay {count}"
            )
    if not failures:
        print(f"[OK] index build: {len(MOCK_CHUNKS)} chunks, re-indexar no duplica")
    return failures


def check_search(store: QdrantVectorStore, min_score: float) -> list[str]:
    """Cada consulta debe traer primero el chunk esperado, con su metadata intacta."""
    failures: list[str] = []
    originals = {c["metadata"]["titulo_canonico"]: c["metadata"] for c in MOCK_CHUNKS}

    print(f"\n     {'consulta':<62} {'esperado':<22} {'top-1':<22} top-1  top-2")
    for query, expected in QUERIES:
        results = search(query, top_k=len(MOCK_CHUNKS), store=store)
        top, second = results[0], results[1]
        got = top["metadata"]["titulo_canonico"]

        if got != expected:
            failures.append(f"ranking: {query!r} -> {got!r}, se esperaba {expected!r}")
        elif top["score"] < min_score:
            failures.append(f"score: {query!r} -> {top['score']:.3f} < {min_score}")
        elif top["metadata"] != originals[expected]:
            failures.append(f"metadata: {top['metadata']} != {originals[expected]}")

        ok = got == expected and top["score"] >= min_score
        print(
            f"{'OK  ' if ok else 'FAIL'} {query:<62} {expected:<22} {got:<22} "
            f"{top['score']:.3f}  {second['score']:.3f}"
        )
    print()
    if not failures:
        print("[OK] search(): ranking correcto y metadata intacta en cada resultado")
    return failures


def check_llm() -> list[str]:
    """Ping al LLM del proveedor configurado en LLM_PROVIDER."""
    settings = get_settings()
    try:
        llm = get_llm()
        reply = llm.invoke("Responde solo con la palabra: OK")
    except Exception as exc:
        return [f"llm ({settings.llm_provider}): {exc}"]
    # .text junta solo los bloques de texto (Claude puede devolver una lista).
    text = reply.text.strip().replace("\n", " ")
    label = f"{settings.llm_provider} ({type(llm).__name__})"
    # Con temperatura 0 la respuesta debe ser "OK". Un texto largo suele ser el
    # razonamiento del modelo filtrado en la respuesta (modelo solo-thinking).
    if not text.upper().startswith("OK") or len(text) > 20:
        return [
            f"llm {label}: se esperaba 'OK' y respondio {text[:80]!r}. "
            "Si es razonamiento, usa un modelo sin thinking "
            "(OLLAMA_CHAT_MODEL=qwen3:4b-instruct)."
        ]
    print(f"[OK] llm: {label} -> {text!r}")
    return []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Lee las opciones de la linea de comandos (ver ``--help``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-llm", action="store_true", help="no hacer ping al LLM")
    parser.add_argument(
        "--keep", action="store_true", help="no borrar la coleccion de prueba al final"
    )
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Corre los chequeos en orden e imprime OK o FAIL por cada uno.

    Returns:
        0 si todo pasa, 1 si algun chequeo falla.
    """
    args = parse_args(argv)
    settings = get_settings()

    print("== Test de infraestructura local (Issue #9) ==")
    print(f"Qdrant: {settings.qdrant_url}")
    print(f"Embeddings: {settings.embedding_model}")
    print(f"LLM_PROVIDER: {settings.llm_provider}\n")

    try:
        embeddings = get_embeddings(validate=True)
        dim = get_embedding_dim(embeddings)
        client = get_client()
    except Exception as exc:
        print(f"[FAIL] servicios: {exc}")
        print(
            "       Revisa: docker compose up -d  y  "
            f"docker compose exec ollama ollama pull {settings.embedding_model}"
        )
        return 1
    print(f"[OK] servicios: Ollama y Qdrant responden (dimension = {dim})")

    failures: list[str] = []
    try:
        store = get_vector_store(
            TEST_COLLECTION, embeddings=embeddings, client=client, recreate=True
        )
        with tempfile.TemporaryDirectory() as tmp:
            failures += check_index(store, client, write_mock_jsonl(Path(tmp)))
        failures += check_search(store, args.min_score)
    except Exception as exc:
        failures.append(f"vector store: {exc!r}")
    finally:
        if not args.keep and client.collection_exists(TEST_COLLECTION):
            client.delete_collection(TEST_COLLECTION)

    if not args.skip_llm:
        failures += check_llm()

    if failures:
        print(f"\nRESULTADO: FALLO ({len(failures)} problema/s)")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("\nRESULTADO: OK - infraestructura local validada")
    return 0


if __name__ == "__main__":
    sys.exit(main())

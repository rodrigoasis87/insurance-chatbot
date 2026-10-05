"""Create article-scoped chunks for the policy retrieval pipeline."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.paths import PROCESSED_DIR

ARTICLES_PATH = PROCESSED_DIR / "articulos.jsonl"
CHUNKS_PATH = PROCESSED_DIR / "chunks.jsonl"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
SEPARATORS = ["\n\n", "\n", ".", " ", ""]

_REQUIRED_TYPES: dict[str, type] = {
    "poliza": str,
    "ramo": str,
    "año": str,
    "articulo": int,
    "canonico": str,
    "pagina": int,
    "texto": str,
}


def make_splitter() -> RecursiveCharacterTextSplitter:
    """Return the configured MVP splitter."""
    return RecursiveCharacterTextSplitter(
        separators=SEPARATORS,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )


def _validate_article(article: Any, line_number: int) -> dict[str, Any]:
    if not isinstance(article, dict):
        raise ValueError(f"Line {line_number}: expected a JSON object")

    missing = [field for field in _REQUIRED_TYPES if field not in article]
    if missing:
        fields = ", ".join(missing)
        raise ValueError(f"Line {line_number}: missing required fields: {fields}")

    for field, expected_type in _REQUIRED_TYPES.items():
        value = article[field]
        if isinstance(value, bool) or not isinstance(value, expected_type):
            raise ValueError(
                f"Line {line_number}: field {field!r} must be {expected_type.__name__}"
            )

    if not article["poliza"].strip():
        raise ValueError(f"Line {line_number}: poliza cannot be empty")
    if not article["texto"].strip():
        raise ValueError(f"Line {line_number}: texto cannot be empty")

    return article


def load_articles(path: Path = ARTICLES_PATH) -> list[dict[str, Any]]:
    """Load and validate article records from a JSONL file."""
    if not path.exists():
        raise FileNotFoundError(f"Articles file does not exist: {path}")

    articles: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            if not raw_line.strip():
                continue
            try:
                article = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_number}: invalid JSON: {exc.msg}") from exc
            articles.append(_validate_article(article, line_number))

    if not articles:
        raise ValueError(f"Articles file is empty: {path}")
    return articles


def iter_chunks(
    articles: Iterable[dict[str, Any]],
    splitter: RecursiveCharacterTextSplitter | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield chunks while keeping each article occurrence isolated."""
    splitter = splitter or make_splitter()
    article_indexes: defaultdict[str, int] = defaultdict(int)

    for article in articles:
        policy = article["poliza"]
        article_index = article_indexes[policy]
        article_indexes[policy] += 1

        text_chunks = splitter.split_text(article["texto"])
        if not text_chunks:
            raise ValueError(
                f"No chunks generated for {policy}, article {article['articulo']}"
            )

        for chunk_index, page_content in enumerate(text_chunks):
            yield {
                "page_content": page_content,
                "metadata": {
                    "poliza": policy,
                    "article_index": article_index,
                    "ramo": article["ramo"],
                    "año": article["año"],
                    "articulo": article["articulo"],
                    "titulo_canonico": article["canonico"],
                    "pagina": article["pagina"],
                    "chunk_index": chunk_index,
                },
            }


def write_chunks(chunks: Iterable[dict[str, Any]], path: Path = CHUNKS_PATH) -> int:
    """Write chunks as UTF-8 JSONL and return the number of records written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as output_file:
        for chunk in chunks:
            output_file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            count += 1
    return count


def build_chunks(input_path: Path = ARTICLES_PATH, output_path: Path = CHUNKS_PATH) -> int:
    """Build the chunks file and return its record count."""
    articles = load_articles(input_path)
    count = write_chunks(iter_chunks(articles), output_path)
    if count == 0:
        raise ValueError("Chunking produced no output records")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ARTICLES_PATH)
    parser.add_argument("--output", type=Path, default=CHUNKS_PATH)
    args = parser.parse_args()

    articles = load_articles(args.input)
    chunks = list(iter_chunks(articles))
    write_chunks(chunks, args.output)
    print(f"Chunked {len(articles)} articles into {len(chunks)} chunks")


if __name__ == "__main__":
    main()

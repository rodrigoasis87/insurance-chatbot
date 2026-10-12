import json
from pathlib import Path

import pytest
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.data.chunker import iter_chunks, load_articles, write_chunks


def article(
    policy: str,
    number: int,
    canonical: str,
    text: str,
    page: int = 1,
) -> dict:
    return {
        "poliza": policy,
        "documento": 1,
        "ramo": "salud",
        "año": "2019",
        "familia": "test",
        "articulo": number,
        "canonico": canonical,
        "pagina": page,
        "texto": text,
    }


def test_chunks_overlap_only_within_one_article() -> None:
    splitter = RecursiveCharacterTextSplitter(
        separators=[" "], chunk_size=20, chunk_overlap=5
    )
    articles = [
        article("POL1", 1, "cobertura", "uno dos tres cuatro cinco seis"),
        article("POL1", 2, "cobertura", "siete ocho nueve diez once doce"),
    ]

    chunks = list(iter_chunks(articles, splitter))

    first = [chunk for chunk in chunks if chunk["metadata"]["articulo"] == 1]
    second = [chunk for chunk in chunks if chunk["metadata"]["articulo"] == 2]
    assert len(first) > 1
    assert len(second) > 1
    assert first[-1]["page_content"] not in second[0]["page_content"]
    assert [chunk["metadata"]["chunk_index"] for chunk in first] == list(range(len(first)))
    assert [chunk["metadata"]["chunk_index"] for chunk in second] == list(range(len(second)))


def test_repeated_article_numbers_get_distinct_documents() -> None:
    articles = [
        article("POL1", 1, "reglas", "reglas"),
        {**article("POL1", 1, "cobertura", "cobertura"), "documento": 2},
    ]

    chunks = list(iter_chunks(articles))

    assert [chunk["metadata"]["documento"] for chunk in chunks] == [1, 2]
    assert [chunk["metadata"]["titulo_canonico"] for chunk in chunks] == [
        "reglas",
        "cobertura",
    ]


def test_documento_is_preserved_for_each_policy() -> None:
    articles = [
        article("POL1", 1, "cobertura", "uno"),
        article("POL2", 1, "cobertura", "dos"),
    ]

    chunks = list(iter_chunks(articles))

    assert [chunk["metadata"]["documento"] for chunk in chunks] == [1, 1]


def test_invalid_article_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "articulos.jsonl"
    path.write_text(json.dumps({"poliza": "POL1"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required fields"):
        load_articles(path)


def test_empty_article_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "articulos.jsonl"
    record = article("POL1", 1, "cobertura", "   ")
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="texto cannot be empty"):
        load_articles(path)


def test_output_is_valid_utf8_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    chunks = list(iter_chunks([article("POL1", 1, "cobertura", "área cubierta")]))

    assert write_chunks(chunks, path) == 1
    output = json.loads(path.read_text(encoding="utf-8"))
    assert output["page_content"] == "área cubierta"
    assert output["metadata"]["pagina"] == 1


def test_same_input_produces_identical_output(tmp_path: Path) -> None:
    articles = [
        article("POL1", 1, "cobertura", "uno dos tres cuatro cinco seis"),
        article("POL1", 2, "exclusiones", "siete ocho nueve diez once doce"),
    ]
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"

    write_chunks(iter_chunks(articles), first_path)
    write_chunks(iter_chunks(articles), second_path)

    assert first_path.read_bytes() == second_path.read_bytes()

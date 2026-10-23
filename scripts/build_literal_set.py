"""Genera el set literal de retrieval (issue de evaluacion hibrida).

El set tiene 60 filas ``answer_from_policy`` con ``reference_contexts`` exactos:

* 20 terminos literales raros (df 1) del corpus;
* 15 frases textuales unicas (df 1);
* 15 casos cross-policy: mismo canonico en varias polizas, con una frase que
  identifica la poliza/articulo correctos;
* 10 consultas con codigo de poliza y numero de articulo.

La generacion es determinista: los terminos raros estan curados a mano y las
frases se eligen con un recorrido round-robin por poliza. El archivo resultante
se versiona para que el A/B sea reproducible.

Uso:
    uv run python scripts/build_literal_set.py
    uv run python scripts/build_literal_set.py --out data/evaluation/retrieval_literal.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.paths import ARTICULOS_JSONL, CHUNKS_JSONL  # noqa: E402
from app.rag.bm25 import STOPWORDS_ES, tokenize  # noqa: E402

EVALUATION_DIR = ROOT / "data/evaluation"
DEFAULT_OUT = EVALUATION_DIR / "retrieval_literal.jsonl"
NGRAM_SIZE = 8
TOKEN_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")

RARE_TERMS: tuple[str, ...] = (
    "autoprovocadas",
    "irreversible",
    "micobacteriana",
    "prescindencia",
    "nosologica",
    "desvitalizacion",
    "nombramiento",
    "atentados",
    "ventriculostomia",
    "aranceladas",
    "preexistencias",
    "hiperbilirrubinemia",
    "agravaciones",
    "inmunoterapias",
    "interconsultas",
    "otorgamiento",
    "confidencialidad",
    "controversias",
    "destinataria",
    "modificarlos",
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    for match in TOKEN_RE.finditer(text):
        token = _normalize(match.group(0))
        if len(token) > 1 and token not in STOPWORDS_ES:
            spans.append((token, match.start(), match.end()))
    return spans


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _article_map(articulos: list[dict[str, Any]]) -> dict[tuple[Any, Any, Any], dict[str, Any]]:
    return {
        (item["poliza"], item["documento"], item["articulo"]): item
        for item in articulos
    }


def _reference_answer(article: dict[str, Any]) -> str:
    text = _squash(article["texto"])
    return text[:400]


def _context(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "poliza": article["poliza"],
        "documento": article["documento"],
        "articulo": article["articulo"],
        "canonico": article["canonico"],
    }


def _row(
    *,
    row_id: str,
    question: str,
    query_type: str,
    article: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": row_id,
        "question": question,
        "reference_answer": _reference_answer(article),
        "expected_behavior": "answer_from_policy",
        "reference_contexts": [_context(article)],
        "query_type": query_type,
    }


def _ngram_counts(articles: list[dict[str, Any]]) -> Counter[tuple[str, ...]]:
    counts: Counter[tuple[str, ...]] = Counter()
    for article in articles:
        tokens = [token for token, _, _ in _token_spans(article["texto"])]
        for start in range(len(tokens) - NGRAM_SIZE + 1):
            counts[tuple(tokens[start : start + NGRAM_SIZE])] += 1
    return counts


def _chunk_ngram_counts(chunks: list[dict[str, Any]]) -> Counter[tuple[str, ...]]:
    counts: Counter[tuple[str, ...]] = Counter()
    for chunk in chunks:
        tokens = [token for token, _, _ in _token_spans(chunk["page_content"])]
        for start in range(len(tokens) - NGRAM_SIZE + 1):
            counts[tuple(tokens[start : start + NGRAM_SIZE])] += 1
    return counts


def _token_df(chunks: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for chunk in chunks:
        counts.update(set(tokenize(chunk["page_content"])))
    return counts


def _unique_fragment(
    article: dict[str, Any],
    ngrams: Counter[tuple[str, ...]],
    chunk_ngrams: Counter[tuple[str, ...]],
    df: Counter[str],
) -> str | None:
    spans = _token_spans(article["texto"])
    candidates: list[tuple[float, int]] = []
    for start in range(len(spans) - NGRAM_SIZE + 1):
        key = tuple(token for token, _, _ in spans[start : start + NGRAM_SIZE])
        if ngrams[key] != 1 or chunk_ngrams[key] < 1:
            continue
        if sum(1 for token in key if df[token] <= 20) < 2:
            continue
        score = sum(1.0 / df[token] for token in key)
        candidates.append((score, start))
    if not candidates:
        return None
    _, start = max(candidates, key=lambda item: (item[0], -item[1]))
    return _squash(
        article["texto"][spans[start][1] : spans[start + NGRAM_SIZE - 1][2]]
    )


def _round_robin(
    candidates: list[dict[str, Any]],
    count: int,
    *,
    max_per_policy: int,
    one_per_canonical: bool,
) -> list[dict[str, Any]]:
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_policy[item["poliza"]].append(item)
    for items in by_policy.values():
        items.sort(key=lambda item: item["articulo"])
    selected: list[dict[str, Any]] = []
    used_canonical: set[str] = set()
    per_policy: Counter[str] = Counter()
    policies = sorted(by_policy)
    while len(selected) < count and any(by_policy.values()):
        progressed = False
        for policy in policies:
            if len(selected) >= count:
                break
            if per_policy[policy] >= max_per_policy:
                continue
            items = by_policy[policy]
            while items:
                item = items.pop(0)
                if one_per_canonical and item["canonico"] in used_canonical:
                    continue
                selected.append(item)
                per_policy[policy] += 1
                used_canonical.add(item["canonico"])
                progressed = True
                break
        if not progressed:
            break
    return selected


def build(
    articulos_path: Path = ARTICULOS_JSONL,
    chunks_path: Path = CHUNKS_JSONL,
    out_path: Path = DEFAULT_OUT,
) -> list[dict[str, Any]]:
    articulos = _load_jsonl(articulos_path)
    chunks = _load_jsonl(chunks_path)
    by_key = _article_map(articulos)
    ngrams = _ngram_counts(articulos)
    chunk_ngrams = _chunk_ngram_counts(chunks)
    df = _token_df(chunks)

    chunks_by_term: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        for term in set(tokenize(chunk["page_content"])):
            chunks_by_term[term].append(chunk)

    rows: list[dict[str, Any]] = []
    used_keys: set[tuple[Any, Any, Any]] = set()
    used_questions: set[str] = set()

    for index, term in enumerate(RARE_TERMS, start=1):
        matches = chunks_by_term.get(term, [])
        if len(matches) != 1:
            raise ValueError(f"El termino {term!r} tiene df={len(matches)}; se esperaba 1")
        metadata = matches[0]["metadata"]
        key = (metadata["poliza"], metadata["documento"], metadata["articulo"])
        if key in used_keys:
            raise ValueError(f"El termino {term!r} repite el articulo {key}")
        article = by_key[key]
        if df[term] != 1:
            raise ValueError(f"El termino {term!r} no tiene df=1 en el indice BM25")
        question = f"¿Qué dice la póliza sobre «{term}»?"
        rows.append(
            _row(
                row_id=f"lit-rare-{index:02d}",
                question=question,
                query_type="rare_term",
                article=article,
            )
        )
        used_keys.add(key)
        used_questions.add(question)

    phrase_candidates = []
    for article in sorted(articulos, key=lambda item: (item["poliza"], item["articulo"])):
        key = (article["poliza"], article["documento"], article["articulo"])
        if key in used_keys:
            continue
        fragment = _unique_fragment(article, ngrams, chunk_ngrams, df)
        if fragment is None:
            continue
        phrase_candidates.append({**article, "_fragment": fragment})

    phrase_targets = _round_robin(
        phrase_candidates, 15, max_per_policy=2, one_per_canonical=False
    )
    if len(phrase_targets) != 15:
        raise ValueError(f"No hay suficientes frases unicas: {len(phrase_targets)}")
    for index, article in enumerate(phrase_targets, start=1):
        question = f"¿Qué establece el contrato sobre «{article['_fragment']}»?"
        if question in used_questions:
            raise ValueError(f"Pregunta duplicada: {question}")
        rows.append(
            _row(
                row_id=f"lit-phrase-{index:02d}",
                question=question,
                query_type="unique_phrase",
                article=article,
            )
        )
        used_keys.add((article["poliza"], article["documento"], article["articulo"]))
        used_questions.add(question)

    policies_by_canonical: dict[str, set[str]] = defaultdict(set)
    for article in articulos:
        policies_by_canonical[article["canonico"]].add(article["poliza"])

    cross_candidates = []
    for article in sorted(articulos, key=lambda item: (item["poliza"], item["articulo"])):
        key = (article["poliza"], article["documento"], article["articulo"])
        if key in used_keys:
            continue
        if len(policies_by_canonical[article["canonico"]]) < 2:
            continue
        fragment = _unique_fragment(article, ngrams, chunk_ngrams, df)
        if fragment is None:
            continue
        cross_candidates.append({**article, "_fragment": fragment})

    cross_targets = _round_robin(
        cross_candidates, 15, max_per_policy=3, one_per_canonical=True
    )
    if len(cross_targets) != 15:
        raise ValueError(f"No hay suficientes casos cross-policy: {len(cross_targets)}")
    for index, article in enumerate(cross_targets, start=1):
        question = f"¿Qué establece el contrato sobre «{article['_fragment']}»?"
        if question in used_questions:
            raise ValueError(f"Pregunta duplicada: {question}")
        rows.append(
            _row(
                row_id=f"lit-cross-{index:02d}",
                question=question,
                query_type="cross_policy",
                article=article,
            )
        )
        used_keys.add((article["poliza"], article["documento"], article["articulo"]))
        used_questions.add(question)

    code_candidates = [
        article
        for article in sorted(articulos, key=lambda item: (item["poliza"], item["articulo"]))
        if article["articulo"] >= 10
        and len(_squash(article["texto"])) >= 120
        and (article["poliza"], article["documento"], article["articulo"]) not in used_keys
    ]
    code_targets = _round_robin(
        code_candidates, 10, max_per_policy=2, one_per_canonical=False
    )
    if len(code_targets) != 10:
        raise ValueError(f"No hay suficientes casos codigo/articulo: {len(code_targets)}")
    for index, article in enumerate(code_targets, start=1):
        question = (
            f"¿Qué establece la póliza {article['poliza']} "
            f"en el artículo {article['articulo']}?"
        )
        if question in used_questions:
            raise ValueError(f"Pregunta duplicada: {question}")
        rows.append(
            _row(
                row_id=f"lit-code-{index:02d}",
                question=question,
                query_type="code_article",
                article=article,
            )
        )
        used_keys.add((article["poliza"], article["documento"], article["articulo"]))
        used_questions.add(question)

    if len(rows) != 60:
        raise ValueError(f"Se esperaban 60 filas y se generaron {len(rows)}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--articulos", type=Path, default=ARTICULOS_JSONL)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_JSONL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build(args.articulos, args.chunks, args.out)
    by_type = Counter(row["query_type"] for row in rows)
    print(f"Escrito {args.out} ({len(rows)} filas)")
    for query_type, count in sorted(by_type.items()):
        print(f"  {query_type}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

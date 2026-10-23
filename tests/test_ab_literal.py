from langchain_core.documents import Document

from app.rag.bm25 import BM25Index
from scripts.ab_retrieval_literal import MetadataBM25Index, _fuse_hits, _metadata_text


def _document(poliza, documento, articulo, titulo, texto, chunk_index=0):
    return Document(
        page_content=texto,
        metadata={
            "poliza": poliza,
            "documento": documento,
            "ramo": "salud",
            "año": 2020,
            "familia": "individual",
            "articulo": articulo,
            "titulo_canonico": titulo,
            "pagina": 1,
            "chunk_index": chunk_index,
        },
    )


def _documents():
    return [
        _document("POL120190177", "doc1", 3, "cobertura", "La cobertura cubre gastos medicos."),
        _document("POL320200214", "doc2", 10, "exclusiones", "No cubre autoprovocadas."),
        _document("POL320210063", "doc3", 2, "primas", "La prima se paga mensualmente."),
    ]


def test_base_bm25_no_encuentra_codigo_ni_articulo():
    index = BM25Index(_documents())
    assert index.search("¿Qué establece la póliza POL320200214 en el artículo 10?", 5) == []


def test_metadata_bm25_encuentra_codigo_y_articulo():
    index = MetadataBM25Index(_documents())
    hits = index.search("¿Qué establece la póliza POL320200214 en el artículo 10?", 5)
    assert hits
    assert hits[0].document.metadata["poliza"] == "POL320200214"
    assert hits[0].document.metadata["articulo"] == 10


def test_metadata_bm25_agrega_artn_para_articulos_de_un_digito():
    index = MetadataBM25Index(_documents())
    hits = index.search("¿Qué establece la póliza POL320210063 en el artículo 2?", 5)
    assert hits
    assert hits[0].document.metadata["poliza"] == "POL320210063"


def test_metadata_bm25_sigue_encontrando_terminos_del_texto():
    index = MetadataBM25Index(_documents())
    hits = index.search("¿Qué dice la póliza sobre «autoprovocadas»?", 5)
    assert hits
    assert hits[0].document.metadata["poliza"] == "POL320200214"


def test_metadata_text_incluye_campos_del_contrato():
    text = _metadata_text(_documents()[0])
    assert "POL120190177" in text
    assert "documento doc1" in text
    assert "articulo 3" in text
    assert "art3" in text
    assert "cobertura" in text


def _hit(poliza, articulo, score, chunk_index=0):
    return {
        "page_content": "",
        "metadata": {
            "poliza": poliza,
            "documento": "doc",
            "articulo": articulo,
            "chunk_index": chunk_index,
        },
        "score": score,
    }


def test_fuse_hits_con_piso_descarta_lexico_no_elegible():
    dense = [_hit("P1", 1, 0.90), _hit("P1", 2, 0.40)]
    lexical = [_hit("P1", 2, 12.0), _hit("P1", 3, 10.0)]
    hits = _fuse_hits(dense, lexical, dense_floor=0.60, top_k=5)
    assert [(hit["metadata"]["poliza"], hit["metadata"]["articulo"]) for hit in hits] == [
        ("P1", 1)
    ]


def test_fuse_hits_sin_piso_incorpora_el_lexico():
    dense = [_hit("P1", 1, 0.90), _hit("P1", 2, 0.40)]
    lexical = [_hit("P1", 2, 12.0), _hit("P1", 3, 10.0)]
    hits = _fuse_hits(dense, lexical, dense_floor=None, top_k=5)
    articles = {(hit["metadata"]["poliza"], hit["metadata"]["articulo"]) for hit in hits}
    assert articles == {("P1", 1), ("P1", 2), ("P1", 3)}


def test_fuse_hits_respeta_top_k():
    dense = [_hit("P1", 1, 0.90)]
    lexical = [_hit("P1", 2, 12.0), _hit("P1", 3, 10.0)]
    hits = _fuse_hits(dense, lexical, dense_floor=None, top_k=2)
    assert len(hits) == 2


def test_literal_set_shape():
    import json
    from collections import Counter

    from scripts.ab_retrieval_literal import LITERAL_PATH

    rows = [json.loads(line) for line in LITERAL_PATH.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 60
    assert Counter(row["query_type"] for row in rows) == {
        "rare_term": 20,
        "unique_phrase": 15,
        "cross_policy": 15,
        "code_article": 10,
    }
    assert len({row["id"] for row in rows}) == 60
    assert len({row["question"] for row in rows}) == 60
    assert all(len(row["reference_contexts"]) == 1 for row in rows)
    assert all(
        row["reference_contexts"][0]["articulo"] >= 10
        for row in rows
        if row["query_type"] == "code_article"
    )


def test_build_literal_set_es_reproducible(tmp_path):
    import json

    from scripts.ab_retrieval_literal import LITERAL_PATH
    from scripts.build_literal_set import build

    out = tmp_path / "literal.jsonl"
    build(out_path=out)
    generated = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    committed = [
        json.loads(line) for line in LITERAL_PATH.read_text(encoding="utf-8").splitlines()
    ]
    assert generated == committed

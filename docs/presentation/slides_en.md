---
marp: true
theme: default
paginate: true
lang: en
footer: "Insurance Policy RAG Chatbot · Final Project · AnyoneAI"
---

<!-- _class: lead -->

# Insurance Policy RAG Chatbot

Answers with verifiable citations about Chilean health insurance policies

**Final Project · AnyoneAI** — Prototype presentation · Sep 2026

---

# Agenda

1. **Problem Statement** — context and motivation
2. **Dataset Description** — resources at our disposal and how we leverage them
3. **Proposed Solution** — architecture, key components and integration
4. **Roadmap** — milestones and current status

---

# Context and Business Rule

- Chilean health policies are **dense legal PDF documents**, with heterogeneous header styles and, in some cases, **composite documents** (several nested policies/endorsements).
- The advisor must locate **the right contract and the right article every time** — slow and error-prone.
- The problem is not "generating", it is **finding the faithful fragment** inside the documentation and **returning it citing the source**.
- **Business rule:** given a question about policies, return the faithful fragment **with its citation** (policy · article · page), without inventing anything.

---

# Persona: the advisor at a health insurance brokerage

**Primary persona (B2B),** with the policyholder as secondary.

- **Tasks:** handle policyholder inquiries and **validate the answer against the contract** before communicating it.
- **Typical questions:** does it cover X? Why doesn't it cover Y? Premium/waiting period, term/renewal, claim deadlines, COVID case.
- **Needs:** clear answer · **original text fragment** · **verifiable citation** · coverage of **all** clauses · consultation privacy.
- **Value:** confidence to answer **without re-reading the PDF**.

---

# The Problem in Numbers

Findings from the **EDA** (they size the problem, they don't define it):

- **9 policies** (2013–2021) · health (8) + accident (1)
- **227 articles** segmented across the corpus
- **36 canonical clauses** — from coverage to terms
- Length per article: median **~1,200 chars**; up to **25.7k chars**
- What matters: **what the documentation contains and how we organize it** to retrieve the faithful fragment.

---

# Requirements → Priorities (order = design criterion)

1. **Security** — **100% local** stack; the query never leaves the system.
2. **Traceability** — the answer **always carries its sources**; the UI shows them.
3. **0 hallucination** — cites only what is retrieved; score threshold; web sources marked.
4. **Speed** (if left) — local, `top_k=5`, answer in seconds.

> Explicit trade-off: **traceability and zero hallucination > speed.**

---

# Scope and Guardrails

- **Domain (inside the policies):** we answer with citations from the corpus.
- **Related (industry, outside the corpus):** the **agent**'s web search — competitor prices, current regulation — with the **external source always marked**.
- **Out of domain:** we do not answer content; we explain why and restate the scope.
- **Guardrail:** `SCORE_THRESHOLD` filters in code + no-hallucination instruction within the call itself · **max. 2 LLM calls per query**.

---

# Dataset · Source & Access

- **9 PDFs** downloaded from S3 into `data/raw_pdfs` (gitignored).
  - Health: **8** · Accident: **1**
  - Period 2013–2021 · Chilean market
- **Reproducible** download (pinned in `scripts/setup.sh`).
- Language: Chilean legal Spanish · **no PII** in the sample.

---

# Dataset · Structure Discovered (EDA)

- **Skeleton matrix**: the clause order is compatible across policies (position 2 = coverage, with exceptions).
- **36 canonical keys** normalize different writing styles.
- Edge cases detected and characterized:
  - **COVID policy** (Law 21.342) — atypical header syntax.
  - **POL320190074** — composite document with **5 nested policies/endorsements**.

---

# Dataset · Data Quality (EDA)

- **5 corruption cases** formalized into cleaning rules:
  1. Control bytes
  2. Empty lines
  3. Duplicated words ("de de")
  4. Mis-joined end-of-line hyphens
  5. Article header inline in the body
- Cleaning turns noisy text into a clean `articulos.jsonl`.
- Legal boilerplate and inline references **are preserved** (they are useful content).

---

# Dataset · How We Leverage It

- **Per-article segmentation** (227 records) plus metadata:
  `poliza`, `ramo`, `año`, `canonico`, `pagina`, `chars`.
- Metadata is the **filtering layer** for retrieval (by clause).
- Versioned artifacts: `docs/EDA.md` + matrices (CSV/JSON).
- Clean articles are the **direct input** to chunking and to the index.

---

# Solution · Architecture in Cells

MVP baseline: agent + web, **≤2 LLM calls**, answers always cited.

```
Data (D1→D2) ─► RAG Engine (R1→R2) ─► Exposure (E1)
                                    ▲
Assurance (G1) ─── validates / secures ┘
```

- **Data:** D1 capture & cleaning → D2 chunking
- **RAG Engine:** R1 indexing & retrieval → **R2 agent + web**
- **Exposure:** E1 API + UI
- **Assurance:** G1 QA, eval and ops (cross-cutting)

---

# Solution · Data (D1 + D2)

- **D1 · Capture & Cleaning (#4):** PDFs → parser (`extract_articles`, `segment_text`, `canonical_title`) → cleaning → `articulos.jsonl` (227, with metadata).
- **D2 · Chunking (#7):** chunks that **never cross an article**; `RecursiveCharacterTextSplitter` · `chunk_size=1000` · `overlap=150`.
- Metadata **propagated** from articles (mapping `canonico` → `titulo_canonico`).
- Binding format: `docs/CONTRACTS.md` §1.

---

# Solution · RAG Engine — R1: Indexing & Retrieval

- **Qdrant** · collection `polizas` (768 dims · cosine) + `search(query, top_k)` with **score and metadata** (#9).
- Embeddings **`nomic-embed-text`** via Ollama (local).
- Deterministic `point_id` → **idempotent** index build.
- Metadata **always travels with the chunk** (traceability); `SCORE_THRESHOLD` applies downstream.

---

# Solution · RAG Engine — R2: Agent + Web

`query()` = a bounded agent:

1. Retrieve → **`SCORE_THRESHOLD` filter** (hard gate in code).
2. **1st call:** *grounded* answer with internal citations.
3. If the context is not enough and it is in-domain → **2nd call** with `web_search` → **web source marked** (`origin: web`).
4. If there is nothing → "not in the sources" + assistant scope.

- LLM **`qwen3:4b`** local · domain guardrail · contract in `CONTRACTS.md` §3 (#17 + #8).

---

# Solution · Exposure (E1)

- **FastAPI** (`/chat`, `/health`, `/policies`) — **thin HTTP**: delegates to `query()`, no RAG logic of its own (#16).
- **Chainlit** — chat with **visible sources**; web ones are visually differentiated (#18).
- Single docker compose · hardened CORS · stack smoke test.

---

# Solution · Assurance & Roadmap (G1)

- **QA:** pytest without Docker (mocks) — parser, retrieval, API (#20).
- **Eval:** golden set → `recall@k`, `cita_ok`, web marking (#19).
- **Ops:** 1-command compose + README + demo video (#21, #22).
- **MVP demo:** answer with internal citation + **1 example of a marked web source**.

| Milestone | Scope | Status |
|---|---|---|
| **M1 · Data** | #4, #7 | in progress (#4) |
| **M2 · RAG Engine** | #9, #8, #17, #19 | next |
| **M3 · Product** | #16, #18, #20, #21, #22 | planned |

---

<!-- _class: lead -->

# Next Steps

1. Finish `articulos.jsonl` (#4) and `chunks.jsonl` (#7)
2. Index build + `search()` (#9) and web tool (#8)
3. Agent `query()` with citations (#17) → first demos
4. Golden set + eval (#19) and product (API/UI/compose · #16–#22)

**Questions?**
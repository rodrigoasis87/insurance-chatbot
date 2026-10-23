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

**Final Project · AnyoneAI** — Prototype presentation · Oct 2026

---

# Agenda

1. **Problem Statement** — context, actors and motivation
2. **Dataset Description** — resources at our disposal and how we leverage them
3. **Proposed Solution** — architecture, key components and integration
4. **Evidence** — measured numbers: quality, speed and cost
5. **Roadmap** — what is delivered, what is pending and next steps

---

# Context and Business Rule

- Chilean health policies are **dense legal PDF documents**, with heterogeneous header styles and, in some cases, **composite documents** (several nested policies/endorsements).
- The advisor must locate **the right contract and the right article every time** — slow and error-prone.
- The problem is not "generating", it is **finding the faithful fragment** inside the documentation and **returning it citing the source**.
- **Business rule:** given a question about policies, return the faithful fragment **with its citation** (policy · article · page), without inventing anything.
- **Documentary underwriting:** the assistant reports what the contract requires/conditions for a profile; it **does not decide, does not price, and does not ask for personal data**.

---

# Actor Map

The chatbot is a **movable piece**: it stands **on the brokerage** and assists the **in-house advisor** (who has **two tasks**: answer and recombine).

```
[REGULATOR · Policy Depository CMF] ──► catalog of templates ◄── [INSURERS]
                                    │
                   [BROKERAGE ◉ bot]  ← parked: assists the in-house advisor
                          │              │
              advises clients      advises insurers
                          ▼
                   [END CLIENT]
```

**When it operates (lifecycle):** UNDERWRITING (profile + documentary answer) · ISSUANCE (recombine → DEM) · IN-FORCE (answer queries) · CLAIM (citations/deadlines).

- Brokerage = **central intermediary**: advises both **insurers** and **end clients**.
- **Regulator** = envelope (Policy Depository): the catalog holds deposited general-condition templates.
- End client = **indirect** user (served by the advisor) · **B2C = future evolution**.

---

# Persona: the advisor at the brokerage (two tasks)

**Primary persona (B2B):** the bot assists the **in-house human**; the end client is an indirect user (B2C = evolution).

1. **Answer policyholder inquiries** and **validate against the contract** before communicating (verifiable citation).
2. **Recombine policies** from market cases: build **DEM** drafts (the brokerage's own standard) to propose to insurers.

- Typical questions: does it cover X? why not Y? term/renewal, claim deadlines, COVID, **market price ranges** (via cited web).
- Value: answer **without re-reading the PDF** and produce new proposals in minutes.

---

# Client Profile: no Personal Data

The bot establishes the **minimum client profile without asking for identifying data or storing anything**: only the conditions policies require to narrow coverage (verified in the corpus):

- **age** (9/9) · **pre-existing conditions** (8/9) · **risk sports** (7/9) · **Fonasa/Isapre** (7/9) · **pregnancy/maternity** (7/9) · **chronic diseases** (2/9) · **collective/labor** (3/9) · **residence** (1/9).

- **Curated options**, no free text · **in-memory (not persisted)** · **confirmed by the advisor** (already known via CRM).
- Several are **sensitive data** (health, Law 19.628) → only a clause selector, never retained.
- Output is **conditional and textual** — "for this profile, the text conditions X" — **never a price or a decision** (price → cited `web_search`).

---

# The Problem, in Numbers

The pain is **search time + the risk of answering without support**. We separate what we have **measured** from what we still need to **measure with the business**.

| What we already measured in the MVP | What still needs measuring with the business |
|---|---|
| **2.4 s** to answer with a citation (measured p50, cloud route) | **[ ] minutes today per advisor query** |
| **227 articles** across 9 deposited policies: the faithful fragment is diluted in that volume | **[ ] queries per advisor per day** |
| **100 %** of answers carry a **verifiable source** (not opinion) | **[ ] hours/month** spent hunting clauses |
| articles of up to **25.7k chars**: re-reading the contract does not scale | **[ ] cost of an unsupported answer** (a claim) |

**The 4 questions for the client** (5 minutes, in the validation session): how long a query takes today · how many are done per day · what happens when the answer is wrong · how much of that time is spent searching the contract.

> With those answers, "the problem in numbers" stops being an EDA data point and becomes **the cost of the process we automate**.

---

# Requirements → Priorities (order = design criterion)

1. **Security** — **self-hosted** stack: the query **never reaches a third-party AI provider**.
2. **Traceability** — the answer **always carries its sources**; the UI shows them.
3. **0 hallucination** — cites only what is retrieved; score threshold; web sources marked.
4. **Speed** (if left) — `top_k=5`, answer in seconds (GPU on the demo).

> Explicit trade-off: **traceability and zero hallucination > speed.**

---

# Where It Runs (and What We Promise)

Same architecture, same corpus, same models; what changes is **who operates the machine**.

| Mode | The model runs on | The query leaves | When |
|---|---|---|---|
| **On-premise** | your office / datacenter | nowhere | real client data |
| **Self-hosted in the cloud** *(the demo: GPU VPS)* | a VPS we administer | our VPS | demo, pilot, development |
| **Third-party API** | OpenAI/Gemini/… datacenter | towards the provider | cloud opt-in mode (ADR-006) |

- The claim we hold in the first two modes: **"the query never reaches a third-party AI provider"**.
- The MVP corpus is **public** (CMF Policy Depository). With real client data the answer is **on-premise with the same Docker image**.
- Embeddings, corpus and index are **always self-hosted** — in all three modes.

---

# Scope and Guardrails

- **Domain (inside the policies):** we answer with citations from the corpus.
- **Related (industry, outside the corpus):** the **agent**'s web search — prices and **market value/price ranges** for a policy type, regulation, real companies — with the **external source always marked**; **a figure is never invented**.
- **Out of domain:** we do not answer content; we explain why and restate the scope.
- **Guardrail:** `SCORE_THRESHOLD` filters in code + no-hallucination instruction within the call itself · **max. 2 LLM calls per query** · no PII.

---

# Dataset · Source & Access

- **9 PDFs** downloaded from S3 into `data/raw_pdfs` (gitignored).
  - Health: **8** · Accident: **1**
  - Period 2013–2021 · Chilean market
- The corpus **does not travel in the repo** (`/data/*` is gitignored): `scripts/setup.sh` rebuilds it reproducibly (download → parser → chunking → index).
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

# Solution · MVP Architecture (components)

MVP baseline: agent + web, **≤2 LLM calls**, answers always cited **+ generation v0 (DEM · #36)**.

```
S3 ─► Parser+cleaning ─► articulos.jsonl (227)
       └─► Chunking 1000/150 ─► chunks.jsonl (758)
                └─► embeddings qwen3-embedding:0.6b (1024d)
                         ▼
                Qdrant · collection `polizas`
                  search()  *pure vector (hybrid BM25/RRF → #42)
                         ▼
                query(): gate UMBRAL_SCORE ─► 1st LLM grounded
                  └─ NEED_WEB + in-domain ─► web_search (DDG) ─► 2nd LLM
                  ≤2 LLM calls · ≤1 web · citations [POL · Art. N · p. X]
                         ▼
                FastAPI: /chat · /chat/stream · /health
                  /policies · /policy-recombine
                *auth (API key · #44)
                         ▼
                Chainlit (sources + streaming)  *session per conversation (#45)
                app/generation/dem.py ─► DEM PDF "DRAFT · not issued"
                  *DEM generation UI (#43)

G1 (cross-cutting) ▶ 146 pytest tests · golden set + RAGAS (#19) · compose · demo
```

- **Data (D1+D2):** S3 → parser/cleaning → 227 articles → 758 chunks (never cross an article).
- **RAG Engine (R1+R2):** Qdrant `polizas` (1024d) → `UMBRAL_SCORE` gate → agent ≤2 calls with citations + marked web.
- **Generation (R3):** DEM recombination v0 → draft PDF (not issued).
- **Exposure (E1):** thin FastAPI + Chainlit with visible sources.
- **Assurance (G1):** QA/eval/ops, cross-cutting.
- **`*` MVP improvements (backlog):** hybrid search #42 · auth #44 · session per conversation #45 · DEM UI #43.

---

# Solution · Data (D1 + D2)

- **D1 · Capture & Cleaning (#4):** PDFs → parser (`extract_articles`, `segment_text`, `canonical_title`) → cleaning → `articulos.jsonl` (227, with metadata).
- **D2 · Chunking (#7):** chunks that **never cross an article**; `RecursiveCharacterTextSplitter` · `chunk_size=1000` · `overlap=150`.
- Metadata **propagated** from articles (mapping `canonico` → `titulo_canonico`).
- Binding format: `docs/CONTRACTS.md` §1.

---

# Solution · RAG Engine — R1: Indexing & Retrieval

- **Qdrant** · collection `polizas` (1024 dims · cosine) + `search(query, top_k)` with **score and metadata** (#9).
- Embeddings **`qwen3-embedding:0.6b`** via Ollama (**self-hosted**, multilingual).
- Deterministic `point_id` (`poliza` + `documento` + `articulo` + `chunk_index`) → **idempotent** index build.
- Metadata **always travels with the chunk** (traceability); `UMBRAL_SCORE` applies downstream.

---

# Solution · RAG Engine — R2: Agent + Web

`query()` = a bounded agent:

1. Retrieve → **`UMBRAL_SCORE` filter** (hard gate in code).
2. **1st call:** *grounded* answer with internal citations.
3. If the context is not enough and it is in-domain → **2nd call** with `web_search` → **web source marked** (`origin: web`).
4. If there is nothing → "not in the sources" + assistant scope.

- LLM **`qwen3:4b-instruct`** self-hosted · domain guardrail · contract in `CONTRACTS.md` §3 (#17 + #8).
- **Market value/price ranges** (the corpus has no prices): answered via **cited** `web_search` as a range, never invented.

---

# Solution · Exposure (E1)

- **FastAPI** (`/chat`, `/health`, `/policies`, **`/policy-recombine`**) — **thin HTTP**: delegates to `query()`, no RAG logic of its own (#16).
- **Chainlit** — chat with **visible sources**; web ones are visually differentiated (#18).
- **Generation v0 (#36):** `/policy-recombine` → **DEM draft PDF** (canonical blocks + profile without PII; marked "DRAFT · not issued").
- Single docker compose · hardened CORS · stack smoke test.

---

# Solution · Assurance & Roadmap (G1)

- **QA:** **146 tests** with pytest without Docker (mocks) — parser, retrieval, API, eval, observability (#20).
- **Eval:** golden set of **100 questions** → `recall@k`, `cita_ok`, web marking + RAGAS (#19) → **pilot n=7 measured**.
- **Ops:** 1-command compose + README + demo (#21, #22).
- **Obs:** self-hosted Langfuse, runtime tracing, **fail-open** (#48).

| Milestone | Scope | Status |
|---|---|---|
| **M1 · Data** | #4, #7 | **delivered** · 227 articles · 758 chunks |
| **M2 · RAG Engine** | #9, #8, #17 | **delivered** · Qdrant + web + agent ≤2 calls |
| **G · Generation v0** | #36 | **delivered** · DEM draft PDF |
| **M3 · Product** | #16, #18, #20, #21, #22 | **delivered** · API + UI + tests + compose |
| **Eval + observability** | #19, #48 | **delivered** · pilot n=7 + Langfuse |

**Open backlog (with issue):** hybrid search #42 · DEM UI #43 · auth #44 · session per conversation #45 · E2E smoke #46 · pytest suite #20 · full golden set run #19.

---

# Solution · G1 · Where the Assurance Lives

G1 is **not runtime**: it is the cross-cutting box of the diagram, **outside the user's hot path**.

```
      RAG Engine ──┐                ┌─ pytest (146) · without Docker
      Generation ──┼─► G1 (offline) ┼─ golden set + RAGAS (#19)
      Exposure ────┘   outside the   └─ compose · README · demo
   (answer, PDF, logs) hot path
        ▲ artifacts (question · contexts · answer · sources)
        └──► feeds back into threshold / chunking / prompts
```

- Runs **offline** over the artifacts the pipeline produces — never inside the user flow.
- **No latency** for the user; it adds a **feedback loop**: results adjust threshold, chunking and prompts.
- Re-scoring a run is **offline and free**: `scripts/rescore_citas.py` recomputes traceability from the stored artifacts.

---

# Solution · G1 · Quality Metrics

| Axis | Metric (RAGAS) | What it measures | Product promise |
|---|---|---|---|
| Retrieval | Context Recall | how much of the ground truth was retrieved | context coverage |
| Retrieval | Context Precision | relevant chunks on top, without boilerplate | slot and ordering quality |
| Generation | **Faithfulness** | does every claim hold against the contexts? | **0 hallucination** |
| Generation | Answer Relevancy / Correctness | does it answer what was asked and match the gold | final answer quality |
| Own metrics | `cita_ok` · web marking | citations `[POL · Art. N · p. X]` valid; `origin: web` correct | traceability (CONTRACTS §3) |

- **RAGAS** is the tool chosen for the #19 eval — **implemented and executed** (pilot n=7 → `docs/eval/PILOTO.md`).
- It does not replace our own metrics: `cita_ok` and web marking are **coded separately** (RAGAS evaluates against contexts, not against the citation format).
- Strict `recall@k` (exact article in the top-5) is reported **next to** context recall: they measure different things.

---

# Numbers · Quality (pilot n=7)

**Measured** in the golden set pilot (n=7 · generator `qwen3:4b-instruct` · judge `gemini-3.5-flash-lite` · `UMBRAL_SCORE=0.6` · `top_k=5`):

| Metric | Result | Range |
|---|---|---|
| Faithfulness | **0.911** | 0.625 – 1.000 |
| Context recall | **0.952** | 0.667 – 1.000 |
| Context precision | **0.823** | 0.367 – 1.000 |
| Traceability (`cita_ok`) | **7/7 rows** | — |
| Citations verifiable against their sources | **26/26 (100 %)** | — |
| Recall@k (exact article in top-5) | **3/7** | — |

**Commitment** (to be proven with the full run, n=100):

| Metric | Target |
|---|---|
| `cita_ok` (rows with a verifiable citation) | **≥ 95 %** |
| Faithfulness | **≥ 0.90** |
| Recall@k (exact article) | **≥ 70 %** |
| Correct abstention cases | **≥ 90 %** |

> Source: `docs/eval/PILOTO.md` · offline re-score without spending API: `uv run python scripts/rescore_citas.py <run_id>`

---

# Numbers · Speed and Behaviour

| Signal | Measured | Where |
|---|---|---|
| Retrieve (p50) | **0.35 s** | Qdrant + self-hosted embeddings |
| First query (cold embeddings) | 2–3 s | embedding cache |
| Full answer (cloud route) | **≈ 2.4 s** | p50 |
| Abstention route | ≈ 2.3 s | no invention, restates scope |
| Full answer (self-hosted **without GPU**) | up to **146 s** | why the demo uses a GPU |
| LLM calls per query | **≤ 2** | contract §3 |
| Queries with a complete trace | **100 %** | Langfuse, 4–6 spans per query |

- The **score gate lives in code**: a chunk below `UMBRAL_SCORE` never reaches the prompt.
- **Fail-open:** if observability goes down, the chat **keeps answering** (availability > telemetry).
- On the GPU VPS the self-hosted route drops from ~146 s to the **1–3 s** range → that is the number we measure during the demo.

---

# Numbers · Cost: self-hosted vs API

| | **Self-hosted** (GPU VPS) | **Third-party API** (Gemini 3.5 Flash Lite) |
|---|---|---|
| Cost per query | **$0** (the VPS is already paid for) | **≈ $0.0007 – $0.0015** |
| What you pay | the VPS, per hour | tokens: ~$0.15–0.30 / 1M in · ~$1.25–2.50 / 1M out\* |
| Volume | unlimited | billed per use |
| Corpus + embeddings | **self-hosted** (no cost) | the same |
| Risk | VPS capacity | dependency + price per token |

\* reference prices, **to be verified against the official pricing table**.

- Measured consumption per query: **~1.2k tokens in / ~450 out** → **650–1,400 queries per USD**.
- **Break-even = monthly VPS cost ÷ cost per query on the API.** With a USD 100/month VPS → **~70,000–140,000 queries/month**. *(we plug in the real VPS price)*.
- **The decision is a business one, not a technical one**: it depends on queries/month and on whether the corpus belongs to the client (→ on-premise).

---

# Numbers · Limits (what we do not know)

What we **do not** claim, because it is not measured:

- **n=7, not 100.** No confidence intervals → the numbers are **trends**, not guarantees.
- **Abstention is unmeasured**: the pilot only covered `answer_from_policy`. The claim *"no hallucination outside coverage"* is **not yet backed by data**.
- **The web route is unmeasured** in the pilot (run with `--no-web`).
- **Recall@k = 3/7**: the retriever brings the **information** (context recall 0.95) but not always the **same article** → addressed by hybrid search (#42).
- **Precision 0.367 in 1 case**: the fixed threshold (0.6) lets marginal context through with `top_k=5`.
- **Cloud judge**: the scores depend on the judge; local ↔ cloud calibration (n=20) is still pending.
- **Public corpus**: no real client data.
- **No GPU in development**: the demo runs on a GPU VPS; the dev team uses CPU.

---

# Solution · Post-MVP: orchestration with LangGraph

Same components and contracts (**≤2 LLM calls**, `UMBRAL_SCORE` in code, `sources[]`): **only the orchestrator changes**.

```
question (thread_id)
     │
     ▼
retrieve ─► gate(UMBRAL) ─► generate
                             │
                ┌────────────┴────────────┐
                │ NEED_WEB and in-domain?  │
                └────────────┬────────────┘
                   yes ──────┘        └────── no ──► answer + sources[]
                    │
                    ▼
           web_search ─► generate_web ─► answer + sources[]

astream_events: status · token · sources  ──►  API / UI
checkpointer: state + conversation history (thread_id)
```

- **One graph, two consumers:** `.invoke()` (sync) and `.astream()` (SSE) → the `query()` / `query_stream()` duplication disappears.
- **Checkpointer:** persistent per-conversation session without writing our own session code (#45).
- **`astream_events`:** per-node events (replaces the manual `NEED_WEB` peek).
- **Per-node traces:** eval of golden set paths (grounded / web / no-source).
- **No new features;** future nodes (intent classifier, DEM→POL) plug into the same graph.

---

# Live Demo

Three queries covering the three paths of the agent:

| # | Query | What to look at |
|---|---|---|
| 1 | What does the deductible of policy X cover? | answer **with citation** `[POL · Art. N · p. X]` + **visible sources** in the UI |
| 2 | A question outside the corpus | **abstention**: "not in the sources" + restated scope, **no invention** |
| 3 | What is the premium range for an individual health policy? | **marked web source** (never presented as a policy citation) |

Optional: `/policy-recombine` → **DEM draft PDF** ("DRAFT · not issued").

- The trace of every query lands in **Langfuse** (same `session_id`): retrieve → gate → generate.
- **Plan B:** pre-recorded video with the same 3 queries.

---

<!-- _class: lead -->

# Next Steps

1. **Full golden set run (n=100)** with the local judge → confirm the quality commitments (#19)
2. **Hybrid search** BM25 + RRF to close the `recall@k` gap (#42)
3. **Session per conversation** with LangGraph + checkpointer (#45)
4. **Auth by API key** on the API (#44) and **DEM generation from the UI** (#43)
5. **E2E smoke test** of the stack in CI (#46)

**Questions?**

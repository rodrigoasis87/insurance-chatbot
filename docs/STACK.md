# ADR-001 · Definición del Stack Técnico

> **Índice de ADRs del proyecto:** este archivo es la **ADR-001** (stack). Las
> demás viven en `docs/adr/`: **ADR-002** (identidad del documento y clave
> única) · **ADR-003** (chunking por frontera de artículo) · **ADR-004**
> (retrieval: colapso por artículo + `UMBRAL_SCORE`) · **ADR-005** (agente
> acotado ≤2 llamadas + `web_search` en el MVP).

- **Estado:** Aceptado
- **Issue vinculada:** #2 — Definir y validar Stack Técnico definitivo
- **Fecha:** 2026-09-28
- **Decisor:** TL (rodrigoasis87)

## 1. Contexto

El chatbot necesita responder sobre pólizas (RAG + retrieval), buscar noticias en
internet y recombinar cláusulas. El enunciado sugiere LangChain, Haystack, Pinecone,
Elasticsearch, OpenAI, etc. Requisitos del equipo:

- **100% gratuito y local** (sin API keys de pago).
- **Sin dependencia de modelos en la nube** (privacidad/costo).
- Cumplir los entregables obligatorios (Agentes/Tools de LangChain, API, UI, Docker).

## 2. Restricciones del entorno (baseline)

| Recurso | Valor |
|---|---|
| SO | WSL2 (kernel 6.6.x) |
| CPU | AMD Ryzen 7 7730U (16 threads) |
| RAM | 16 GB |
| GPU | Integrada (sin NVIDIA); inferencia **CPU-only** |
| Ollama | v0.24.0 instalado |

## 3. Decisión

| Componente | Elección | Versión / modelo |
|---|---|---|
| Framework RAG + Agentes | **LangChain** | `langchain` + `langgraph` (agentes) |
| LLM (generación) | **Ollama (docker compose)** | `qwen3:4b-instruct` (Q4, ~2.5 GB) |
| Embeddings | **Ollama (docker compose)** | `qwen3-embedding:0.6b` (1024d, multilingüe, ~639 MB) |
| Vector store | **Qdrant via Docker** | imagen `qdrant/qdrant:v1.19.1` |
| Búsqueda web | **DuckDuckGo** | `duckduckgo-search` (sin key) |
| UI | **Chainlit** | `chainlit` |
| PDF | **PyMuPDF** | `pymupdf` |
| API | **FastAPI** + `uvicorn` | — |

> **Actualización (2026-09-28):** Ollama corre como servicio de **docker compose**
> (`ollama/ollama:0.24.0`) para que todo el equipo tenga el mismo entorno.
> Los modelos se bajan al volumen `ollama_models` con `docker compose exec ollama
> ollama pull qwen3:4b-instruct` (y `qwen3-embedding:0.6b`). Onboarding completo en
> `scripts/setup.sh`. Imágenes **pinneadas** (no `:latest`) por reproducibilidad.

> **Actualización (2026-09-30):** el **MVP incluye agente + búsqueda web**.
> `query()` (#17) es un agente acotado a **≤2 llamadas LLM** por consulta
> (retrieve → juzgar → `web_search` si falta), con hard gate `UMBRAL_SCORE`
> antes del LLM y fuentes web siempre marcadas (`origen: web`). Detalle en
> `docs/narrative.md` §4 y `docs/CONTRACTS.md` §3.

> **Actualización (2026-10-01, #9):** embeddings `nomic-embed-text` reemplazado por
> `qwen3-embedding:0.6b` (1024d, multilingüe). Su model card indica que nomic es
> solo inglés, y en el test de retrieval en español (`scripts/test_vectordb.py`)
> sacó 3/4 aun con sus prefijos; `qwen3-embedding:0.6b` y `bge-m3` sacaron 4/4, y
> qwen3 separó mejor la respuesta correcta (brecha media 0.29 vs 0.14) con la mitad
> de tamaño. El LLM pasa a `qwen3:4b-instruct`: en Ollama `qwen3:4b` es la variante
> thinking-2507, que siempre razona y no se puede apagar.
>
> Qdrant sube de `v1.15.0` a `v1.19.1`, la misma versión que `qdrant-client`
> (con 1.15 el cliente avisaba que el servidor era incompatible). Qdrant no
> permite saltar versiones menores sobre datos existentes: como la colección se
> regenera desde `chunks.jsonl`, lo simple es borrar el volumen `qdrant_data` y
> volver a indexar (ver README).

Dependencias PyPI a agregar con `uv`:

```bash
uv add langchain langchain-ollama langchain-community langgraph
uv add qdrant-client langchain-qdrant
uv add chainlit fastapi uvicorn
uv add duckduckgo-search pymupdf pandas tqdm
```

## 4. Justificación por componente

- **LangChain:** entregable obligatorio *"Use of LangChain Agents and Tools"* para
  el ruteo (pólizas / noticias / "no sé"). Los agentes modernos se construyen con
  LangGraph (`create_react_agent`).
- **Ollama `qwen3:4b-instruct`:** punto medio velocidad/calidad en CPU-only.
  `qwen3:8b` se descartó por latencia (>15 s en este hardware); `llama3.2:3b` por
  peor desempeño en español legal. Se usa la variante **instruct** porque
  `qwen3:4b` en Ollama es thinking-2507: siempre razona y no se puede apagar
  (nota 2026-10-01).
- **Embeddings `qwen3-embedding:0.6b`:** 1024d, multilingüe y ~639 MB; reemplazó a
  `nomic-embed-text` (solo inglés) tras medir el retrieval en español (4/4 vs 3/4).
  Alternativa evaluada: `bge-m3`.
- **Qdrant (Docker):** vector store real con API REST/gRPC; prepara el entregable
  de docker-compose (#12). Chroma (embedded) queda como alternativa si hubiera
  presión de RAM en dev.
- **DuckDuckGo:** gratis, sin API key. Tavily descartado (tope gratuito y key).
  Nota: es la **única pieza que requiere internet** (requerimiento del deliverable
  de noticias).
- **Chainlit:** UI tipo ChatGPT en Python, conexión directa a la API del chatbot.

## 5. Alternativas evaluadas y descartadas

| Opción | Por qué se descartó |
|---|---|
| OpenAI GPT / `text-embedding-3-small` | Requiere API key de pago; contradice "100% gratuito y local" |
| Azure OpenAI | Setup administrativo adicional, mismo costo |
| Haystack | Gran framework de ingest, pero el entregable pide LangChain Agents/Tools |
| Pinecone | Cloud/plan pagado |
| ElasticSearch | Pesado para el alcance; Qdrant cubre el caso |
| Tavily (web search) | Tope gratuito y API key; DDG alcanza |
| Ollama `qwen3:8b` | Latencia alta en CPU-only |
| Ollama `llama3.2:3b` | Peor calidad en español |

## 6. Consecuencias y trade-offs aceptados

- **Latencia:** respuestas de generación entre ~5–15 s en CPU-only. Aceptable para
  demo/demo-day; se puede acelerar bajando a un modelo menor o subiendo a GPU.
- **Calidad:** por debajo de GPT-4o en redacción; mitigable con prompts y retrieval
  de calidad (issues #4, #7).
- **Runtime:** requiere Docker Compose con **Qdrant y Ollama** corriendo
  (`docker compose up -d`); no se usa el Ollama nativo del SO (el compose es la
  fuente de verdad para que todo el equipo tenga el mismo entorno).
- **Única conexión externa:** búsqueda de noticias (DDG).

## 7. Variables de entorno

No hay API keys de modelos. Solo las del dataset AWS (para descargar PDFs):

```
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

## 8. Setup y validación inicial (smoke test)

```bash
# Entorno completo (uv + docker compose + modelos + smoke test)
bash scripts/setup.sh

# Manualmente:
docker compose up -d                     # Qdrant (6333) + Ollama (11434)
docker compose exec ollama ollama pull qwen3:4b-instruct      # LLM del RAG (#9)
docker compose exec ollama ollama pull qwen3-embedding:0.6b   # embeddings del RAG (#9)
uv run python scripts/smoke_stack.py     # integración ChatOllama/OllamaEmbeddings/Qdrant
```

*Smoke test* verifica integración `ChatOllama` / `OllamaEmbeddings` / `Qdrant` antes
de avanzar con las issues #4, #7, #8 y #9.
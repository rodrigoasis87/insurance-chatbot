# Insurance Policy Generation Chatbot

Chatbot asistente para el mercado asegurador chileno (QuePlan.cl). Responde
preguntas sobre pólizas consultando una base de documentos, busca noticias del
sector en internet y puede recombinar cláusulas de pólizas existentes para
generar nuevas.

## Stack

Stack **100% local y gratuita** (ver `docs/STACK.md` — ADR-001):

- **Modelos:** Ollama (`qwen3:4b-instruct` generación · `qwen3-embedding:0.6b` embeddings)
- **RAG + Agentes:** LangChain (+ LangGraph)
- **Vector store:** Qdrant (Docker)
- **Búsqueda web:** DuckDuckGo (sin API key)
- **Backend / UI:** FastAPI · Chainlit
- **Herramientas:** Python 3.12 (uv) · boto3 · PyMuPDF · Docker

## Estructura

```
app/
├── data/        # descarga, preprocesado y EDA
├── retrieval/   # indexado y búsqueda
├── generation/  # pipeline RAG + agentes
├── api/         # FastAPI
│   └── ui/      # interfaz de usuario
data/
├── raw_pdfs/    # PDFs descargados (gitignored)
├── processed/
└── indexes/
```

## Setup

El stack corre **100% via Docker** para que todo el equipo tenga el mismo entorno.

```bash
bash scripts/setup.sh        # uv sync + docker compose up + modelos + smoke test
```

O manualmente, paso a paso:

```bash
uv sync                       # instala dependencias y crea .venv
cp .env.example .env          # completa tus credenciales AWS S3
docker compose up -d          # levanta Qdrant (6333) y Ollama (11434)
docker compose exec ollama ollama pull qwen3:4b
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull qwen3:4b-instruct      # LLM del RAG (#9)
docker compose exec ollama ollama pull qwen3-embedding:0.6b   # embeddings del RAG (#9)
uv run python scripts/smoke_stack.py   # valida el stack
uv run python -m app.data.download     # descarga los PDFs a data/raw_pdfs
```

> Si tenés Ollama nativo instalado y corriendo, apagalo (`ollama stop`) para
> no chocar con el puerto 11434 del contenedor.

**Si ya tenías Qdrant 1.15 corriendo:** la imagen pasó a `v1.19.1`, que no puede
abrir los datos guardados por 1.15 (el contenedor se cae al arrancar). La colección
se regenera desde `chunks.jsonl`, así que borrá solo el volumen de Qdrant y volvé a
indexar. No uses `docker compose down -v`: también borra los modelos de Ollama.

```bash
docker compose rm -s -f qdrant                   # detiene y borra solo el contenedor de Qdrant
docker volume rm insurance-chatbot_qdrant_data   # nombre exacto en: docker volume ls
docker compose up -d qdrant                      # baja v1.19.1 y arranca limpio
uv run python -m app.rag.indexer                 # vuelve a indexar chunks.jsonl
```

## Estado

- [x] Repo inicializado con uv, estructura modular y descarga S3
- [x] Stack técnico definido (`docs/STACK.md` — ADR-001)
- [ ] EDA y extracción de texto
- [ ] Indexado y búsqueda (retrieval)
- [ ] Pipeline RAG + agentes (pólizas / noticias web)
- [ ] API FastAPI
- [ ] UI
- [ ] Docker
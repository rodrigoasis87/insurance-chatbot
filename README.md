# Insurance Policy Generation Chatbot

Chatbot asistente para el mercado asegurador chileno (QuePlan.cl). Responde
preguntas sobre pólizas consultando una base de documentos, busca noticias del
sector en internet y puede recombinar cláusulas de pólizas existentes para
generar nuevas.

## Stack

Stack **100% local y gratuita** (ver `docs/STACK.md` — ADR-001):

- **Modelos:** Ollama (`qwen3:4b` generación · `nomic-embed-text` embeddings)
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
uv run python scripts/smoke_stack.py   # valida el stack
uv run python -m app.data.download     # descarga los PDFs a data/raw_pdfs
```

> Si tenés Ollama nativo instalado y corriendo, apagalo (`ollama stop`) para
> no chocar con el puerto 11434 del contenedor.

## Estado

- [x] Repo inicializado con uv, estructura modular y descarga S3
- [x] Stack técnico definido (`docs/STACK.md` — ADR-001)
- [ ] EDA y extracción de texto
- [ ] Indexado y búsqueda (retrieval)
- [ ] Pipeline RAG + agentes (pólizas / noticias web)
- [ ] API FastAPI
- [ ] UI
- [ ] Docker
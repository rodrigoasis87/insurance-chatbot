# Insurance Policy Generation Chatbot

Chatbot asistente para el mercado asegurador chileno (QuePlan.cl). Responde
preguntas sobre pólizas consultando una base de documentos, busca noticias del
sector en internet y puede recombinar cláusulas de pólizas existentes para
generar nuevas.

## Stack

Python 3.12 (uv) · boto3 · RAG (retrieval + LLM) · FastAPI · Docker

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

```bash
uv sync                       # instala dependencias y crea .venv
cp .env.example .env          # completa tus credenciales AWS S3
uv run python -m app.data.download   # descarga los PDFs a data/raw_pdfs
```

## Estado

- [x] Repo inicializado con uv, estructura modular y descarga S3
- [ ] EDA y extracción de texto
- [ ] Indexado y búsqueda (retrieval)
- [ ] Pipeline RAG + agentes (pólizas / noticias web)
- [ ] API FastAPI
- [ ] UI
- [ ] Docker
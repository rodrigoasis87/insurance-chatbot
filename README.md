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
├── data/        # descarga S3, parser, EDA y artefactos (PDFs → articulos.jsonl → chunks.jsonl)
├── rag/         # retrieval: embeddings, indexer Qdrant, vectordb (search + colapso), config, llm
├── generation/  # Recombinación DEM demo v0 (#36)
├── api/         # FastAPI (#16)
└── ui/          # interfaz de usuario (#18)
data/
├── raw_pdfs/    # PDFs descargados (gitignored)
├── processed/   # articulos.jsonl, chunks.jsonl, umbral_raw.json (gitignored)
├── indexes/     # reservado (vector stores locales si hicieran falta)
└── generated/   # borradores DEM de prueba (gitignored)
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
docker compose exec ollama ollama pull qwen3:4b-instruct      # LLM del RAG (#9)
docker compose exec ollama ollama pull qwen3-embedding:0.6b   # embeddings del RAG (#9)
uv run python scripts/smoke_stack.py   # valida el stack
uv run python -m app.data.download     # descarga los PDFs a data/raw_pdfs
```

> Si tenés Ollama nativo instalado y corriendo, apagalo con `sudo systemctl stop
> ollama` para no chocar con el puerto 11434 del contenedor. Ojo: `ollama stop`
> solo descarga el modelo, el server sigue escuchando en 11434.

**Si ya tenías Qdrant 1.15 corriendo:** la imagen pasó a `v1.19.1`, que no puede
abrir los datos guardados por 1.15 (el contenedor se cae al arrancar). La colección
se regenera desde `chunks.jsonl`, así que borrá solo el volumen de Qdrant y volvé a
indexar. No uses `docker compose down -v`: también borra los modelos de Ollama.

```bash
docker compose rm -s -f qdrant                   # detiene y borra solo el contenedor de Qdrant
docker volume rm "$(docker volume ls -q --filter name=qdrant_data)"   # prefijo = nombre del proyecto de compose (directorio), p. ej. finalproject_qdrant_data
docker compose up -d qdrant                      # baja v1.19.1 y arranca limpio
uv run python -m app.rag.indexer                 # vuelve a indexar chunks.jsonl
```

## Preparar los datos

Después de descargar los PDFs, generar los artefactos procesados en este orden:

```bash
uv run python -m app.data.build_articulos  # PDFs → articulos.jsonl
uv run python -m app.data.chunker          # articulos.jsonl → chunks.jsonl
uv run python -m app.rag.indexer           # chunks.jsonl → Qdrant
```

Los archivos generados quedan en `data/processed/` y están ignorados por Git:

```text
data/processed/articulos.jsonl   # 227 artículos limpios
data/processed/chunks.jsonl      # chunks de 1000 caracteres, overlap 150
```

El retrieval filtra por un score mínimo configurable (env `UMBRAL_SCORE`, default
`0.60`) y colapsa resultados duplicados por `(poliza, articulo)`. La elección del
umbral y cómo re-medirlo al cambiar de embeddings/chunking: `docs/umbral_score.md`
(ADR-004).

Para validar el parser, el retrieval y ejecutar la suite de pruebas:

```bash
uv run python scripts/test_parser.py      # parser: 227 artículos + familias
uv run python scripts/test_vectordb.py    # smoke del index/retrieval contra Qdrant
uv run pytest                             # suite con mocks (sin Docker)
uv run python scripts/analisis_umbral.py  # re-mide scores → data/processed/umbral_raw.json
```

También se pueden especificar rutas alternativas para los dos primeros pasos:

```bash
uv run python -m app.data.build_articulos \
  --pdf-dir otro/directorio/con/pdfs \
  --out otro/articulos.jsonl

uv run python -m app.data.chunker \
  --input otro/articulos.jsonl \
  --output otro/chunks.jsonl
```

## Documentación

- `docs/ARCHITECTURE.md` — arquitectura del MVP y post-MVP, con ADRs y estado por célula.
- `docs/CONTRACTS.md` — contratos de datos, runtime y agente (`query()` ≤2 llamadas).
- `docs/ONTOLOGIA.md` — ontología del dominio (claves, PII, intenciones).
- `docs/narrative.md` — narrativa, actores y roadmap.
- `docs/umbral_score.md` — `UMBRAL_SCORE` empírico (ADR-004).
- `docs/STACK.md` (ADR-001) y `docs/adr/` (ADR-002…005) — decisiones de arquitectura.

## Estado

- [x] Repo, stack técnico e infra Docker (Qdrant `v1.19.1` + Ollama) — ADR-001
- [x] Datos: descarga S3, EDA, parser y artefactos (227 artículos · 758 chunks) — #4, #7
- [x] Retrieval: indexado Qdrant + `search()` con colapso por `(poliza, articulo)` y `UMBRAL_SCORE` — #9 · ADR-002/003/004
- [ ] RAG + agentes (pólizas / noticias web, ≤2 llamadas LLM) — #17, #8
- [ ] Generación DEM (recombinación demo v0) — #36
- [ ] API FastAPI — #16
- [ ] UI — #18
- [ ] QA/eval (golden set, demo day) — #19, #20, #21, #22

# Insurance Policy Generation Chatbot

Chatbot asistente para el mercado asegurador chileno (QuePlan.cl). Responde
preguntas sobre pólizas consultando una base de documentos, busca noticias del
sector en internet y puede recombinar cláusulas de pólizas existentes para
generar nuevas.

## Stack

Stack **100% local y gratuita** (ver `docs/STACK.md` — ADR-001):

- **Modelos:** Ollama (`qwen3:4b-instruct` generación · `qwen3-embedding:0.6b` embeddings)
- **LLM de chat: intercambiable** (ADR-006): default Ollama local; cloud (`google` →
  `gemini-3.5-flash-lite`, API key) disponible como **opt-in de demo**. Embeddings
  y corpus **siempre locales**; solo la modalidad cloud envía la consulta.
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

**Levantar todo de una** (Qdrant + Ollama + API + UI; requiere index previo, ver abajo):

```bash
docker compose up -d --build          # UI → http://localhost:8001 · API → http://localhost:8000/docs
```

```bash
bash scripts/setup.sh        # uv sync + docker compose up + modelos + smoke test
```

O manualmente, paso a paso:

```bash
uv sync                       # instala dependencias y crea .venv
cp .env.example .env          # completa tus credenciales AWS S3
docker compose up -d          # levanta Qdrant (6333), Ollama (11434), API (8000) y UI (8001)
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

Para evaluar el RAG con el conjunto RAGAS (requiere Qdrant y Ollama activos;
`uv` instala el grupo `eval` si hace falta):

```bash
uv run --group eval python scripts/evaluate_ragas.py
```

Para un piloto rápido de una pregunta de póliza, sin búsqueda web:

```bash
uv run --group eval python scripts/evaluate_ragas.py \
  --limit 1 --behavior answer_from_policy --no-web --metrics faithfulness
```

Para evaluar dos preguntas aleatorias de póliza; agrega `--seed 42` si quieres
repetir exactamente la misma muestra:

```bash
uv run --group eval python scripts/evaluate_ragas.py \
  --n=2 --behavior answer_from_policy --no-web --metrics faithfulness
```

Los resultados se guardan en `data/evaluation/results/`.

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

## Demo (R3 · #36)

El agente `query()` (CONTRACTS §3) aplica el **hard gate `UMBRAL_SCORE`** en
código, responde *grounded* con citas internas `[fuente: POL · Art. N]` y, solo
si la pregunta es del rubro y el corpus no alcanza, consulta una vez la web
(`web_search`, DuckDuckGo) y cita la fuente externa como `[web]` (ADR-004/005,
≤2 llamadas LLM por consulta).

```bash
docker compose up -d --build            # todo arriba → UI en http://localhost:8001
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"question":"¿Cuál es el plazo para denunciar un siniestro?"}'   # API directo
uv run python -m scripts.demo_recorrido  # 5 preguntas + generación DEM (§4.1) (ver nota)
uv run pytest tests/test_rag_query.py tests/test_api.py        # tests del agente y del API
```

> `demo_recorrido` usa `query()` directo para las 5 preguntas (sin Docker); el
> **paso 6 (Recombinación DEM)** llama al API (`POST /policy-recombine`, §4.1), así
> que necesita el stack arriba. Para probar el API local por fuera de Docker:
> `uv run uvicorn app.api.main:app --port 8000`.

### Demo: streaming y ambas modalidades (ADR-006)

La UI (`Chainlit`) tiene un **selector lateral** que cambia el LLM por petición
sin reiniciar (local `ollama` ↔ cloud `google`, etc.), y consume el endpoint
**SSE** `POST /chat/stream` (`status` → `token…` → `sources`) que muestra la
respuesta en vivo manteniendo el límite de ≤2 llamadas LLM (peek de `NEED_WEB`).

- Modalidad local (default): anda sin configurar nada.
- Modalidad cloud: pegá tu `GOOGLE_API_KEY` en `.env` (o usá la otra clave del
  bloque), luego recreá el contenedor del API para leer la env:

```bash
# cloud: GOOGLE_API_KEY=... y, opcionalmente, LLM_PROVIDER=google en .env
docker compose up -d api           # ~10 s, sin rebuild
curl localhost:8000/health         # → {"provider": "google", "model": "gemini-3.5-flash-lite", ...}
```

O volvés a local cambiando `LLM_PROVIDER=ollama` en `.env` + `docker compose up -d api`.
En la UI, aún con default local, el selector permite cambiar modalidad por consulta
(grabá latencia y citas de las 5 preguntas en ambos modos para el demo-day).

### Demo: generación de borrador DEM (#36)

`POST /policy-recombine` (CONTRACTS §4.1) recombina bloques de cláusulas de un
**molde base** del catálogo + **perfil curado sin PII** (opciones del dominio:
edad, preexistencias, fonasa/isapre, etc.) → borrador **JSON + PDF** con marca
`BORRADOR · no emitida` y cita de origen por sección:

```bash
curl -X POST localhost:8000/policy-recombine -H 'Content-Type: application/json' \
  -d '{"molde":"POL320200071","perfil":{"edad":"30-40","preexistencias":"no",\
       "deportes_riesgo":"no","fonasa_isapre":"isapre","embarazo":"no",\
       "cronicas":"no","colectivo":"no","residencia":"chile"}}'
# → codigo DEM2026…, secciones con cita, pdf_url "/generated/DEM….pdf", aviso
```

El PDF se sirve en `http://localhost:8000/generated/<codigo>.pdf` (el API monta
`data/generated`). También corre como CLI: `uv run python -m app.generation.dem --help`.
La demo lo muestra en el **paso 6** de `demo_recorrido`.

## Documentación

- `docs/ARCHITECTURE.md` — arquitectura del MVP y post-MVP, con ADRs y estado por célula.
- `docs/CONTRACTS.md` — contratos de datos, runtime y agente (`query()` ≤2 llamadas).
- `docs/ONTOLOGIA.md` — ontología del dominio (claves, PII, intenciones).
- `docs/narrative.md` — narrativa, actores y roadmap.
- `docs/umbral_score.md` — `UMBRAL_SCORE` empírico (ADR-004).
- `docs/STACK.md` (ADR-001) y `docs/adr/` (ADR-002…006) — decisiones de arquitectura.

## Estado

- [x] Repo, stack técnico e infra Docker (Qdrant `v1.19.1` + Ollama) — ADR-001
- [x] Datos: descarga S3, EDA, parser y artefactos (227 artículos · 758 chunks) — #4, #7
- [x] Retrieval: indexado Qdrant + `search()` con colapso por `(poliza, articulo)` y `UMBRAL_SCORE` — #9 · ADR-002/003/004
- [x] Agente RAG demo v0: `query()` con hard gate, citas y `web_search` (≤2 llamadas LLM) — #17, #8 · ADR-004/005
- [x] API FastAPI delgado: `POST /chat` · `GET /health` · `GET /policies`, delega en `query()` — #16
- [x] UI demo: Chainlit consumiendo el API por HTTP (no `query()` directo) — #18 · CONTRACTS §4
- [x] Ops demo: `docker compose` único (Qdrant + Ollama + API + UI) — #21
- [x] Demo ext: streaming SSE (`/chat/stream`) + LLM intercambiable con toggle en la UI (local ↔ cloud) — ADR-006
- [x] Generación DEM (recombinación demo v0): CLI + `POST /policy-recombine` + PDF borrador — #36
- [ ] QA/eval (golden set, demo day) — #19, #20, #22

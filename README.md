# Insurance Policy Generation Chatbot

Chatbot asistente para el mercado asegurador chileno (QuePlan.cl). Responde
preguntas sobre pólizas consultando una base de documentos, busca noticias del
sector en internet y puede recombinar cláusulas de pólizas existentes para
generar nuevas.

## Stack

Stack **autoalojado (self-hosted)** y **gratis en el default**: la inferencia
corre en infraestructura que administramos nosotros, **sin APIs de IA de
terceros** (ver `docs/STACK.md` — ADR-001):

- **Modelos:** Ollama (`qwen3:4b-instruct` generación · `qwen3-embedding:0.6b` embeddings)
- **LLM de chat: intercambiable** (ADR-006): default autoalojado (Ollama); cloud (`google` →
  `gemini-3.5-flash-lite`, API key) disponible como **opt-in de demo**. Embeddings
  y corpus **siempre autoalojados**; solo la modalidad cloud envía la consulta.
- **RAG + Agentes:** LangChain (+ LangGraph)
- **Vector store:** Qdrant (Docker)
- **Retrieval:** denso (default) o híbrido denso + BM25 (`rank-bm25`) fusionado con RRF (`RETRIEVAL_MODE`, #42)
- **Búsqueda web:** DuckDuckGo (sin API key)
- **Backend / UI:** FastAPI · Chainlit
- **Observabilidad:** Langfuse (opcional; tracing en runtime, noop si no se configura)
- **Herramientas:** Python 3.12 (uv) · boto3 · PyMuPDF · Docker

### Dónde corre (modos de despliegue)

La **arquitectura es la misma** en los tres modos; lo que cambia es dónde se
despliega el stack y quién opera la máquina.

| Modo | El modelo corre en | La consulta sale de | Coste |
|---|---|---|---|
| **On-premise** | tu oficina / datacenter | nada | CAPEX + operación |
| **Autoalojado en nube** (el de la demo: VPS con GPU) | una VPS dedicada que administramos | nuestra VPS | fijo (USD/hora) |
| **API de terceros** | datacenter de OpenAI/Gemini/… | hacia el proveedor | por token |

El claim que el stack sostiene en los dos primeros modos es *"la consulta **no
llega a ningún proveedor de IA de terceros**"*. El corpus del MVP es público
(Depósito CMF); con datos de clientes reales, la respuesta es **on-premise con
la misma imagen Docker**.

> Overlay de GPU para la VPS de demo: `docker compose -f docker-compose.yml
> -f docker-compose.gpu.yml up -d` (ver `docker-compose.gpu.yml`).

## Estructura

```
app/
├── data/        # descarga S3, parser, EDA y artefactos (PDFs → articulos.jsonl → chunks.jsonl)
├── rag/         # retrieval: embeddings, indexer Qdrant, vectordb (search + RRF + colapso), bm25, config, llm
├── observability/  # tracing en runtime con Langfuse (opcional, noop por defecto) — #48
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
cp .env.example .env          # completa tus credenciales AWS S3 (y API_KEY, ver "Autenticación del API")
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
# Corrida base recomendada: póliza + abstención, sin web (80 filas),
# juez local, y genera docs/eval/LATEST.md
uv run --group eval python scripts/evaluate_ragas.py \
  --no-web --exclude-behavior answer_from_web \
  --report-doc docs/eval/LATEST.md
```

La corrida base deja fuera los 20 casos `answer_from_web`; van en una corrida
aparte (opcional, requiere red), y conviene un juez independiente:

```bash
# Casos web (20), juez Gemini (más independiente del generador)
uv run --group eval python scripts/evaluate_ragas.py \
  --behavior answer_from_web --judge google
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

Los resultados crudos se guardan en `data/evaluation/results/` (ignorados por
Git) y el último resumen versionado en `docs/eval/LATEST.md`. El juez por
defecto es `qwen3:4b-instruct` local; con `--judge google` se usa Gemini (ya
configurado en `.env`).

Los archivos generados quedan en `data/processed/` y están ignorados por Git:

```text
data/processed/articulos.jsonl   # 227 artículos limpios
data/processed/chunks.jsonl      # chunks de 1000 caracteres, overlap 150
```

El retrieval filtra por un score mínimo configurable (env `UMBRAL_SCORE`, default
`0.60`) y colapsa resultados duplicados por `(poliza, articulo)`. La elección del
umbral y cómo re-medirlo al cambiar de embeddings/chunking: `docs/umbral_score.md`
(ADR-004).

### Búsqueda híbrida (BM25 + denso, #42)

`RETRIEVAL_MODE` elige el retrieval sin tocar `query()` ni el contrato de
`search()` (CONTRACTS §2):

| `RETRIEVAL_MODE` | Qué hace | `score` | Hard gate |
|---|---|---|---|
| `dense` (default) | similitud coseno en Qdrant | coseno | `UMBRAL_SCORE=0.60` |
| `hybrid` | ranking denso + ranking BM25 (índice en memoria sobre `data/processed/chunks.jsonl`) fusionados con Reciprocal Rank Fusion (k=60) | RRF normalizado a (0, 1] | `UMBRAL_SCORE` como piso semántico antes de fusionar + `UMBRAL_SCORE_HYBRID=0.40` sobre la fusión |

El modo `hybrid` no requiere reindexar Qdrant: BM25 se construye al primer
`search()` desde `chunks.jsonl` (si el archivo falta, `search()` falla con un
error explícito). Con Docker, el API lee `RETRIEVAL_MODE` del `.env` y usa el
`./data` montado. Para comparar ambos modos (A/B):

```bash
uv run python scripts/ab_retrieval.py                       # recall@k/MRR/abstención en el golden set, sin LLM
uv run python scripts/analisis_umbral.py --mode hybrid      # distribución y barrido del gate fusionado
RETRIEVAL_MODE=hybrid uv run --group eval python scripts/evaluate_ragas.py \
  --no-web --exclude-behavior answer_from_web --metrics context_recall context_precision
```

Resultados del A/B y calibración de `UMBRAL_SCORE_HYBRID`: `docs/umbral_score.md` §7–8.

Para validar el parser, el retrieval y ejecutar la suite de pruebas:

```bash
uv run python scripts/test_parser.py      # parser: 227 artículos + familias
uv run python scripts/test_vectordb.py    # smoke del index/retrieval contra Qdrant
uv run pytest                             # suite con mocks (sin Docker)
uv run python scripts/analisis_umbral.py  # re-mide scores → data/processed/umbral_raw.json (--mode hybrid: umbral_raw_hybrid.json)
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
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"¿Cuál es el plazo para denunciar un siniestro?"}'   # API directo
uv run python -m scripts.demo_recorrido  # 5 preguntas + generación DEM (§4.1) (ver nota)
uv run pytest tests/test_rag_query.py tests/test_api.py tests/test_api_auth.py  # agente, API y auth
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
  -H "X-API-Key: $API_KEY" \
  -d '{"molde":"POL320200071","perfil":{"edad":"30-40","preexistencias":"no",\
       "deportes_riesgo":"no","fonasa_isapre":"isapre","embarazo":"no",\
       "cronicas":"no","colectivo":"no","residencia":"chile"}}'
# → codigo DEM2026…, secciones con cita, pdf_url "/generated/DEM….pdf", aviso
```

El PDF se sirve en `http://localhost:8000/generated/<codigo>.pdf` (el API monta
`data/generated`). También corre como CLI: `uv run python -m app.generation.dem --help`.
La demo lo muestra en el **paso 6** de `demo_recorrido`.

### Demo: observabilidad con Langfuse (#48)

Langfuse traza **cada consulta en vivo** (retrieval → hard gate → LLM → web →
respuesta). Es **opcional**: sin configurarlo, el pipeline corre igual y no se
toca nada del stack por defecto.

Con Langfuse self-host (overlay: agrega web, worker, postgres, clickhouse,
redis y minio):

```bash
# 1) Levantar el stack con Langfuse (la UI queda en http://localhost:3000)
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d

# 2) Crear el primer usuario en http://localhost:3000 y generar las API keys
#    (Settings → API Keys) → copiarlas al .env con LANGFUSE_ENABLED=true

# 3) Reiniciar el API para que lea las keys
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d api

# 4) Preguntar algo y ver el trace en la UI de Langfuse
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" \
  -d '{"question":"¿Cuál es el plazo para denunciar un siniestro?"}'
```

También sirve **Langfuse Cloud**: creá un proyecto en `https://cloud.langfuse.com`,
copiá las keys al `.env` con `LANGFUSE_BASE_URL=https://cloud.langfuse.com` y
listo (sin Docker).

Variables (`.env`, ver `.env.example`):

```bash
LANGFUSE_ENABLED=false        # false = noop, el pipeline corre igual
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=http://127.0.0.1:3000
LANGFUSE_ENVIRONMENT=local
```

`POST /chat` y `POST /chat/stream` aceptan además un `session_id` **opcional**
que agrupa los traces de una misma conversación (la UI de Chainlit lo manda
solo). Detalle completo en `docs/OBSERVABILITY.md`.

### Autenticación del API (#44)

`POST /chat`, `POST /chat/stream` y `POST /policy-recombine` exigen el header
**`X-API-Key`** con el valor de `API_KEY` del `.env` (sin servicio de identidad).
`GET /health` queda **público** (lo usa el smoke test). Sin header o con una key
distinta el API responde **401**. Contrato completo en `docs/CONTRACTS.md` §4.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # pegala en .env como API_KEY=...
docker compose up -d api ui                     # el API y la UI leen la misma API_KEY

export API_KEY=<la misma del .env>              # para los curl de este README
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/chat \
  -H 'Content-Type: application/json' -d '{"question":"¿plazo?"}'   # → 401
curl -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -H "X-API-Key: $API_KEY" -d '{"question":"¿plazo?"}'             # → 200
curl localhost:8000/health                                           # → 200, sin key
```

- La **UI** (Chainlit) y `scripts/demo_recorrido.py` mandan la key solos si
  `API_KEY` está definida. En Swagger (`/docs`) usá el botón **Authorize**.
- **Modo dev**: con `API_KEY` vacío no hay auth y el API lo avisa con un warning
  en los logs al arrancar (`docker compose logs api`).

Variable (`.env`, ver `.env.example`):

```bash
API_KEY=                      # vacío = modo dev sin auth (warning en logs)
```

### Login de la UI

La UI (http://localhost:8001) abre con una pantalla de login de Chainlit.
Credenciales de la demo: **`admin` / `admin`** (se cambian con `UI_USERNAME` y
`UI_PASSWORD`). Chainlit firma la sesión con `CHAINLIT_AUTH_SECRET` y **no
arranca sin ella**:

```bash
uv run chainlit create-secret        # pegá CHAINLIT_AUTH_SECRET=... en .env
docker compose up -d --build ui
```

```bash
CHAINLIT_AUTH_SECRET=         # obligatoria; cambiarla cierra las sesiones abiertas
UI_USERNAME=admin             # vacío = admin
UI_PASSWORD=admin             # vacío = admin
```

## Documentación

- `docs/ARCHITECTURE.md` — arquitectura del MVP y post-MVP, con ADRs y estado por célula.
- `docs/CONTRACTS.md` — contratos de datos, runtime y agente (`query()` ≤2 llamadas).
- `docs/ONTOLOGIA.md` — ontología del dominio (claves, PII, intenciones).
- `docs/narrative.md` — narrativa, actores y roadmap.
- `docs/umbral_score.md` — `UMBRAL_SCORE` empírico (ADR-004).
- `docs/EVAL.md` — evaluación de calidad (golden set + RAGAS, offline).
- `docs/OBSERVABILITY.md` — tracing en runtime con Langfuse (opcional, #48).
- `docs/STACK.md` (ADR-001) y `docs/adr/` (ADR-002…006) — decisiones de arquitectura.

## Estado

- [x] Repo, stack técnico e infra Docker (Qdrant `v1.19.1` + Ollama) — ADR-001
- [x] Datos: descarga S3, EDA, parser y artefactos (227 artículos · 758 chunks) — #4, #7
- [x] Retrieval: indexado Qdrant + `search()` con colapso por `(poliza, articulo)` y `UMBRAL_SCORE` — #9 · ADR-002/003/004
- [x] Búsqueda híbrida opcional: BM25 + denso con RRF (`RETRIEVAL_MODE=hybrid`), gate re-calibrado y A/B con el golden set — #42
- [x] Agente RAG demo v0: `query()` con hard gate, citas y `web_search` (≤2 llamadas LLM) — #17, #8 · ADR-004/005
- [x] API FastAPI delgado: `POST /chat` · `GET /health` · `GET /policies`, delega en `query()` — #16
- [x] UI demo: Chainlit consumiendo el API por HTTP (no `query()` directo) — #18 · CONTRACTS §4
- [x] Ops demo: `docker compose` único (Qdrant + Ollama + API + UI) — #21
- [x] Demo ext: streaming SSE (`/chat/stream`) + LLM intercambiable con toggle en la UI (local ↔ cloud) — ADR-006
- [x] Generación DEM (recombinación demo v0): CLI + `POST /policy-recombine` + PDF borrador — #36
- [x] Observabilidad en runtime: tracing con Langfuse (opcional, noop por defecto) + overlay self-host — #48
- [x] Auth mínima del API: header `X-API-Key` en `/chat`, `/chat/stream` y `/policy-recombine`; `/health` público — #44
- [x] QA/eval: golden set de 100 preguntas + RAGAS + `cita_ok` propio; **piloto n=7 medido y re-scored** (`docs/eval/PILOTO.md`) — #19, #20
- [ ] Corrida completa del golden set (n=100) con juez local + demo en vivo con video de respaldo — #19, #22

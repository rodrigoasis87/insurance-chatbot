# Observabilidad en runtime · Langfuse (Issue #48)

> **Estado**: implementado en `feature/issue-48-langfuse-observability`.
> Langfuse es **opcional**: sin configurarlo, el pipeline corre igual (tracer noop).

Esta capa responde una pregunta distinta a la del eval: **qué pasó en una
consulta concreta, en vivo**. El eval (G1, `docs/EVAL.md`) mide la calidad
agregada de un lote de preguntas; Langfuse deja la traza de *esta* consulta:
qué se recuperó, qué pasó el hard gate, qué se le preguntó al modelo, si hubo
web, cuánto tardó y si falló.

Las dos capas **no se mezclan**: el eval corre offline sobre el golden set, sin
red y fuera del hot path; el tracing ocurre **dentro** de `query()` /
`query_stream()`, en la request que el usuario está esperando.

---

## 1. Objetivo y alcance

- Trazar cada consulta del agente: retrieval → hard gate → LLM → web → respuesta.
- Poder ver, en la UI de Langfuse, **qué respondió el modelo y con qué citas**.
- Poder detectar degradaciones en producción: latencia alta, `web_search` caído,
  demasiadas abstenciones, umbrales de score que bajan.
- **No** enviar datos sensibles: el corpus es público (Depósito de Pólizas de la
  CMF) y las preguntas son de la demo; no hay PII en el flujo (ADR-005, §4.1 de
  `docs/CONTRACTS.md`).

**Lo que NO hace**: no reemplaza el golden set ni las métricas de G1; no guarda
las respuestas para entrenar ni las versiona; no instrumenta el `web_search` por
dentro del proveedor.

## 2. Diseño

### 2.1 Principio: la instrumentación no puede romper el producto

La regla que gobierna todo el módulo: **ningún fallo de Langfuse puede romper
una consulta**. Si el backend está caído, si las keys están malas o si el SDK
lanza, la consulta sigue respondiendo igual, solo que sin traza.

Por eso la integración vive detrás de una interfaz propia (`app/observability/`)
y no se importa el SDK de Langfuse en el código de negocio:

| Capa | Ruta | Rol |
|---|---|---|
| Interfaz | `app/observability/tracing.py` → `Tracer` | Tracer **noop** (por defecto). No importa el SDK. |
| Implementación | `app/observability/tracing.py` → `LangfuseTracer` | Habla con el SDK de Langfuse. Todos los `try/except` degradan a noop. |
| Fábrica | `app/observability/tracing.py` → `get_tracer()` | Cachea el cliente; construye el tracer según la config. |
| Config | `app/rag/config.py` → `Settings` | Lee `LANGFUSE_*` del entorno. |
| Pipeline | `app/rag/query.py` | Abre los spans; recibe el `tracer` por parámetro (inyectable). |
| Exposición | `app/api/main.py` · `app/ui/chat.py` | Propagan `session_id` (opcional). |

`app/rag/query.py` **no importa `langfuse`**: solo conoce la interfaz `Tracer`.
Eso mantiene el hot path limpio y permite testear con un tracer fake.

### 2.2 Activación

`get_tracer()` decide en runtime:

| `LANGFUSE_ENABLED` | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | Tracer |
|---|---|---|
| `false` (default) | — | **noop** (no se importa el SDK) |
| `true` | faltan | **noop** (avisa por log) |
| `true` | completos | **Langfuse** |

El `noop` implementa la misma interfaz (`span()` como context manager que no
hace nada), así que el pipeline **no tiene ramas especiales**: el código
instrumentado es el mismo con y sin Langfuse.

### 2.3 Spans emitidos

Cada paso del pipeline es una observación (span). Los hijos cuelgan del span raíz
(`rag.query`), que se abre al principio de `query()` / `query_stream()`.

| Span | Tipo Langfuse | Qué registra |
|---|---|---|
| `rag.query` | `span` (raíz) | Pregunta, respuesta final y metadata: `route`, `n_fuentes`, `n_fuentes_poliza`, `n_fuentes_web` |
| `rag.retrieve` | `retriever` | `top_k`, `n_candidatos`, `n_hits` y el resumen de los hits que pasaron el gate |
| `rag.hard_gate` | `span` | `umbral`, `n_candidatos`, `n_hits` (el hard gate de ADR-004, explícito en la traza) |
| `rag.llm_generate` | `generation` | 1.ª llamada grounded: prompt, modelo, respuesta, `need_web` |
| `rag.web_search` | `tool` | Búsqueda externa: consulta, resultados (`titulo`/`url`), `n_resultados` |
| `rag.llm_generate_web` | `generation` | 2.ª llamada con fuentes web: prompt, modelo, respuesta |

El `metadata.route` del span raíz usa las **mismas cuatro rutas** que el eval
registra en `trace["route"]` (`policy` · `web` · `abstain` · `web_failed`), de
modo que un trace de producción y una fila del golden set se leen igual.

`session_id` (opcional) se propaga con `propagate_attributes()` del SDK: agrupa
todos los traces de una misma conversación en la UI.

### 2.4 Diagrama

```text
                    POST /chat  (o /chat/stream)   session_id?
                              │
                              ▼
              ┌── app/rag/query.py  (query) ───────────────────────────────┐
              │                                                            │
              │  ┌── rag.query (raíz) ──────────────────────────────────┐  │
              │  │  metadata.route: policy|web|abstain|web_failed       │  │
              │  │                                                      │  │
              │  ┌── rag.retrieve ──────────────────────────────────┐      │
              │  │  top_k · n_candidatos · n_hits                   │      │
              │  │  ┌ rag.hard_gate ┐  umbral · n_hits              │      │
              │  └──────────────────────────────────────────────────┘      │
              │  ┌── rag.llm_generate ──────────────────────────────┐      │
              │  │  prompt · modelo · respuesta · need_web          │      │
              │  └──────────────────────────────────────────────────┘      │
              │  ┌── rag.web_search ────────────────────────────────┐      │
              │  │  consulta · resultados · n_resultados            │      │
              │  └──────────────────────────────────────────────────┘      │
              │  ┌── rag.llm_generate_web ──────────────────────────┐      │
              │  │  prompt · modelo · respuesta (web)               │      │
              │  └──────────────────────────────────────────────────┘      │
              │  └──────────────────────────────────────────────────────┘  │
              └────────────────────────────────────────────────────────────┘
                                   │  (si Langfuse no está: noop, 0 impacto)
                                   ▼
                        ┌───────────────────┐
                        │  Langfuse (API)   │  → UI http://localhost:3000
                        └───────────────────┘
```

## 3. Configuración

### 3.1 Variables de entorno

En `.env` (copiar de `.env.example`):

```bash
# Langfuse · Issue #48 (opcional: false = noop, el pipeline corre igual)
LANGFUSE_ENABLED=false
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=http://127.0.0.1:3000
LANGFUSE_ENVIRONMENT=local
```

- `LANGFUSE_BASE_URL`: URL del backend. Self-host → `http://127.0.0.1:3000`
  (local) o `http://langfuse-web:3000` (dentro de Docker). Cloud →
  `https://cloud.langfuse.com`.
- `LANGFUSE_ENVIRONMENT`: etiqueta del entorno en la UI (`local`, `staging`…).

### 3.2 Langfuse self-host (Docker)

El stack principal (`docker-compose.yml`: qdrant, ollama, api, ui) **no se
toca**. Langfuse arrastra postgres + clickhouse + redis + minio, así que va en
un **overlay** aparte que se levanta solo cuando se quiere:

```bash
# 1) Levantar el stack completo (incluye Langfuse)
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d

# 2) Crear el primer usuario en http://localhost:3000 (no hay login por defecto)

# 3) En la UI: Settings → API Keys → crear un proyecto y copiar
#    LANGFUSE_PUBLIC_KEY (pk-lf-…) y LANGFUSE_SECRET_KEY (sk-lf-…)

# 4) Pegarlas en el .env con LANGFUSE_ENABLED=true y reiniciar el API
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d api
```

Para **apagarlo** y volver al stack liviano: `docker compose up -d` (sin el
overlay). Los datos de Langfuse quedan en volúmenes (`langfuse_postgres_data`,
`langfuse_clickhouse_data`, `langfuse_minio_data`, `langfuse_redis_data`).

> **Nota sobre `depends_on`**: en un overlay de Compose, `depends_on` *reemplaza*
> al del archivo base (no concatena). Por eso el overlay repite `qdrant` y
> `ollama` junto a `langfuse-web`; si no, el API dejaría de depender de ellos.

Secrets del stack (SALT, ENCRYPTION_KEY, NEXTAUTH_SECRET, passwords) tienen
valores por defecto **solo para desarrollo**: en un despliegue real hay que
cambiarlos (y no subirlos al repo).

### 3.3 Langfuse Cloud

Sin Docker: crear una cuenta en `https://cloud.langfuse.com`, generar las keys
del proyecto y poner `LANGFUSE_BASE_URL=https://cloud.langfuse.com` en el
`.env`. El resto de la configuración es idéntica.

## 4. Uso

### 4.1 Ver un trace

1. Preguntar algo en la UI (o `curl` a `POST /chat`).
2. Abrir `http://localhost:3000` → proyecto → **Tracing** → la consulta aparece
   como `rag.query`.
3. Al desplegarlo se ve el árbol de spans: retrieval, hard gate, LLM, web, con
   el prompt y la respuesta de cada llamada.

Preguntas que responde de un vistazo:

- ¿La consulta se abstuvo o respondió? → `metadata.route` del span raíz.
- ¿El hard gate dejó pasar los artículos correctos? → `rag.hard_gate`.
- ¿El modelo pidió web (`NEED_WEB`)? → `rag.llm_generate.metadata.need_web`.
- ¿La web falló? → `rag.web_search` en error y `route=web_failed`.
- ¿Cuánto tardó cada paso? → tiempos en la UI (spans anidados).

### 4.2 Sesiones

`POST /chat` y `POST /chat/stream` aceptan un campo **opcional** `session_id`
(≤200 chars). La UI de Chainlit lo manda con el id de sesión del navegador, así
que las preguntas de una misma conversación quedan agrupadas en Langfuse.

```jsonc
POST /chat  {"question": "¿plazo de denuncia?", "session_id": "conv-42"}
```

El campo es **aditivo**: el body anterior sigue siendo válido y la respuesta no
cambia. `session_id` solo agrupa trazas; no afecta el pipeline.

## 5. Tests

`tests/test_observability.py` (23 tests, sin red y sin Langfuse instalado):

- **modo noop**: sin configuración el tracer es noop y `query()` devuelve
  exactamente lo mismo;
- **activación**: con `LANGFUSE_ENABLED=true` hacen falta las dos keys;
- **spans**: `query()` y `query_stream()` emiten retrieve, hard gate, LLM, web y
  LLM-web, con la metadata de la ruta (`policy` / `web` / `abstain` /
  `web_failed`);
- **robustez**: un cliente de Langfuse roto **no** rompe la consulta (ni en
  streaming) y una excepción del pipeline se sigue propagando;
- **`session_id`**: llega al span raíz, se propaga a los hijos y es opcional en
  la API.

```bash
uv run pytest tests/test_observability.py -q
```

## 6. Límites conocidos

- **Sin traza de las llamadas al modelo cuando el span falla**: si el SDK no
  puede abrir la observación, la consulta sigue pero sin registro (fail-open).
- **El `input` de los spans LLM contiene el prompt completo** (fragmentos de la
  póliza). Es aceptable para la demo (corpus público), pero en un despliegue
  con datos sensibles habría que redactar antes de enviar.
- **Langfuse no agrupa por usuario**: solo por `session_id` (conversación). No
  hay autenticación en la demo.
- **El stack self-host es pesado** (6 contenedores). Por eso es un overlay
  opcional y no parte del compose por defecto.
- **No se miden tokens ni costo**: el SDK los calcularía si el modelo los
  reporta; hoy el pipeline no los expone.

## 7. Referencias

- `app/observability/` — tracer noop + tracer de Langfuse.
- `app/rag/query.py` — pipeline instrumentado.
- `docs/ARCHITECTURE.md` §2.2 — el bloque de observabilidad en el diagrama.
- `docs/EVAL.md` — el otro lado de la garantía G1 (eval batch, offline).
- `docs/CONTRACTS.md` §4 — contrato de la API (campo opcional `session_id`).
- SDK: [`langfuse` en PyPI](https://pypi.org/project/langfuse/) · compose
  oficial de Langfuse v4.

---
marp: true
theme: default
paginate: true
lang: es
footer: "Chatbot RAG de Pólizas de Seguros · Proyecto Final · AnyoneAI"
---

<!-- _class: lead -->

# Chatbot RAG de Pólizas de Seguros

Respuestas con citas verificables sobre pólizas de salud chilenas

**Proyecto Final · AnyoneAI** — Presentación de prototipo · Sep 2026

---

# Agenda

1. **Problem Statement** — contexto y motivación
2. **Dataset Description** — recursos y cómo los aprovechamos
3. **Proposed Solution** — arquitectura, componentes clave e integración
4. **Roadmap** — hitos y estado actual

---

# Contexto y regla de negocio

- Las pólizas de salud chilenas son **documentos legales densos en PDF**, con estilos de cabecera heterogéneos y, en algunos casos, **documentos compuestos** (varias pólizas/anexos anidados).
- El asesor debe ubicar **el contrato correcto y el artículo correcto cada vez** — lento y propenso a error.
- El problema no es "generar", es **encontrar el fragmento fiel** dentro de la documentación y **devolverlo citando la fuente**.
- **Regla de negocio:** ante una pregunta sobre pólizas, devolver el fragmento fiel **con su cita** (póliza · artículo · página), sin inventar nada.

---

# Persona: el asesor/a de una corredora de seguros de salud

**Persona primaria (B2B),* con el asegurado como secundaria.

- **Tareas:** atender consultas de los asegurados y **validar la respuesta contra el contrato** antes de comunicarla.
- **Preguntas típicas:** ¿cubre X? ¿Por qué no me cubre Y? Prima/carencia, vigencia/renovación, plazos de siniestro, caso COVID.
- **Necesita:** respuesta clara · **fragmento textual original** · **cita verificable** · cobertura de **todas** las cláusulas · privacidad de la consulta.
- **Valor:** confianza para responder **sin releer el PDF**.

---

# El problema en números

Hallazgos del **EDA** (dimensionan el problema, no lo definen):

- **9 pólizas** (2013–2021) · salud (8) + accidentes (1)
- **227 artículos** segmentados en el corpus
- **36 cláusulas canónicas** — de cobertura a vigencias
- Longitud por artículo: mediana **~1.200 chars**; hasta **25.7k chars**
- Lo que importa: **qué contiene la documentación y cómo la ordenamos** para recuperar el fragmento fiel.

---

# Requisitos → prioridades (orden = criterio de diseño)

1. **Seguridad** — stack **100% local**; la consulta no sale del sistema.
2. **Trazabilidad** — la respuesta va **siempre con sus fuentes**; la UI las muestra.
3. **0 alucinación** — solo cita lo recuperado; umbral de score; fuentes web marcadas.
4. **Velocidad** (si queda) — local, `top_k=5`, respuesta en segundos.

> Trade-off explícito: **trazabilidad y cero alucinación > velocidad.**

---

# Alcance y guardrails

- **Dominio (dentro de las pólizas):** respondemos con citas del corpus.
- **Relacionado (del rubro, fuera del corpus):** web del **agente** — precios de competencia, normativa vigente — con **fuente externa siempre marcada**.
- **Fuera de dominio:** no respondemos contenido; explicamos por qué y reiteramos el alcance.
- **Guardrail:** `UMBRAL_SCORE` filtra en código + instrucción de no inventar en la propia llamada · **máx. 2 llamadas LLM por consulta**.

---

# Dataset · Fuente y acceso

- **9 PDFs** descargados de S3 a `data/raw_pdfs` (gitignored).
  - Salud: **8** · Accidentes: **1**
  - Periodo 2013–2021 · mercado chileno
- Descarga **reproducible** (pinned en `scripts/setup.sh`).
- Lenguaje: español legal chileno · **sin PII** en la muestra.

---

# Dataset · Estructura descubierta (EDA)

- **Matriz esqueleto**: el orden de cláusulas es compatible entre pólizas (posición 2 = cobertura, con excepciones).
- **36 claves canónicas** normalizan estilos de escritura distintos.
- Casos borde detectados y caracterizados:
  - **Póliza COVID** (Ley 21.342) — sintaxis de cabecera atípica.
  - **POL320190074** — documento compuesto con **5 pólizas/anexos anidados**.

---

# Dataset · Calidad (EDA)

- **5 casos de suciedad** formalizados en reglas de limpieza:
  1. Bytes de control
  2. Líneas vacías
  3. Palabras duplicadas ("de de")
  4. Guiones de fin de línea mal unidos
  5. Cabecera del artículo inline en el cuerpo
- La limpieza convierte el texto ruidoso en un `articulos.jsonl` limpio.
- El boilerplate legal y las referencias inline **se conservan** (son contenido útil).

---

# Dataset · Cómo la aprovechamos

- **Segmentación por artículo** (227 registros) + metadata:
  `poliza`, `ramo`, `año`, `canonico`, `pagina`, `chars`.
- La metadata es la **capa de filtrado** del retrieval (por cláusula).
- Artefactos versionados: `docs/EDA.md` + matrices (CSV/JSON).
- Los artículos limpios son la **entrada directa** del chunking y del índice.

---

# Solución · Arquitectura en células

Baseline del MVP: agent + web, **≤2 llamadas LLM**, respuestas siempre citadas.

```
Datos (D1→D2) ─► Motor RAG (R1→R2) ─► Exposición (E1)
                                    ▲
Garantías (G1) ─── valida / asegura ─┘
```

- **Datos:** D1 captura y limpieza → D2 chunking
- **Motor RAG:** R1 indexación y retrieval → **R2 agente + web**
- **Exposición:** E1 API + UI
- **Garantías:** G1 QA, eval y ops (transversal)

---

# Solución · Datos (D1 + D2)

- **D1 · Captura y limpieza (#4):** PDFs → parser (`extract_articles`, `segment_text`, `canonical_title`) → limpieza → `articulos.jsonl` (227, con metadata).
- **D2 · Chunking (#7):** chunks que **no cruzan de artículo**; `RecursiveCharacterTextSplitter` · `chunk_size=1000` · `overlap=150`.
- Metadata **propagada** desde los artículos (mapeo `canonico` → `titulo_canonico`).
- Formato vinculante: `docs/CONTRACTS.md` §1.

---

# Solución · Motor RAG — R1: indexación y retrieval

- **Qdrant** × colección `polizas` (768 dims · coseno) + `search(query, top_k)` con **score y metadata** (#9).
- Embeddings **`nomic-embed-text`** vía Ollama (local).
- `point_id` determinístico → index build **idempotente**.
- Los metadatos **viajan con el chunk** (trazabilidad); `UMBRAL_SCORE` se aplica aguas abajo.

---

# Solución · Motor RAG — R2: agente + web

`query()` = agente acotado:

1. Retrieve → **filtro `UMBRAL_SCORE`** (hard gate en código).
2. **1.ª llamada:** respuesta *grounded* con citas internas.
3. Si el contexto no alcanza y es del rubro → **2.ª llamada** con `web_search` → **fuente web marcada** (`origen: web`).
4. Si no hay nada → "no está en las fuentes" + alcance del asistente.

- LLM **`qwen3:4b`** local · guardrail de dominio · contrato en `CONTRACTS.md` §3 (#17 + #8).

---

# Solución · Exposición (E1)

- **FastAPI** (`/chat`, `/health`, `/policies`) — **HTTP delgado**: delega en `query()`, sin lógica RAG propia (#16).
- **Chainlit** — chat con **fuentes visibles**; las web se diferencian visualmente (#18).
- Docker compose único · CORS acotado · smoke test del stack.

---

# Solución · Garantías y roadmap (G1)

- **QA:** pytest sin Docker (mocks) — parser, retrieval, API (#20).
- **Eval:** golden set → `recall@k`, `cita_ok`, marcación de web (#19).
- **Ops:** compose de 1 comando + README + demo en video (#21, #22).
- **Demo MVP:** respuesta con cita interna + **1 ejemplo de fuente web marcada**.

| Hito | Alcance | Estado |
|---|---|---|
| **M1 · Datos** | #4, #7 | en curso (#4) |
| **M2 · Motor RAG** | #9, #8, #17, #19 | próximo |
| **M3 · Producto** | #16, #18, #20, #21, #22 | planificado |

---

<!-- _class: lead -->

# Próximos pasos

1. Terminar `articulos.jsonl` (#4) y `chunks.jsonl` (#7)
2. Index build + `search()` (#9) y tool web (#8)
3. `query()` del agente con citas (#17) → primeras demos
4. Golden set + eval (#19) y producto (API/UI/compose · #16–#22)

**¿Preguntas?**
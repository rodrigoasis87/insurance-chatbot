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

**Proyecto Final · AnyoneAI** — Presentación de prototipo · Oct 2026

---

# Agenda - Rodrigo

1. **Problem Statement** — contexto, actores y motivación
2. **Dataset Description** — recursos y cómo los aprovechamos
3. **Proposed Solution** — arquitectura, componentes clave e integración
4. **Evidencia** — números medidos: calidad, velocidad y costo
5. **Roadmap** — lo entregado, lo pendiente y próximos pasos

---

# Contexto y regla de negocio - Rodrigo

- Las pólizas de salud chilenas son **documentos legales densos en PDF**, con estilos de cabecera heterogéneos y, en algunos casos, **documentos compuestos** (varias pólizas/anexos anidados).
- El asesor debe ubicar **el contrato correcto y el artículo correcto cada vez** — lento y propenso a error.
- El problema no es "generar", es **encontrar el fragmento fiel** dentro de la documentación y **devolverlo citando la fuente**.
- **Regla de negocio:** ante una pregunta sobre pólizas, devolver el fragmento fiel **con su cita** (póliza · artículo · página), sin inventar nada.
- **Suscripción documental:** el asistente informa lo que exige/condiciona el contrato para un perfil; **no decide, no tarifica y no pide datos personales**.

---

# Mapa de actores - Rodrigo

El chatbot es una **pieza móvil**: está parado **sobre la corredora** y asiste al **asesor/a interno** (que tiene **dos tareas**: responder y recombinar).

```
[REGULADOR · Depósito CMF] ──► catálogo de moldes ◄── [ASEGURADORAs]
                                    │
                   [CORREDORA ◉ bot]  ← parada: asiste al asesor/a interno
                          │              │
             asesora clientes     asesora aseguradoras
                          ▼
                   [CLIENTE FINAL]
```

**Cuándo opera (ciclo de vida):** SUSCRIPCIÓN (perfil + respuesta documental) · EMISIÓN (recombinar → DEM) · VIGENCIA (responder consultas) · SINIESTRO (citas/plazos).

- Corredora = **intermediario central**: asesora a **aseguradoras** y a **clientes finales**.
- **Regulador** = envolvente (Depósito de Pólizas): el catálogo son moldes de condiciones generales depositadas.
- Cliente final = usuario **indirecto** (lo atiende el asesor) · **B2C = evolución futura**.

---

# Persona: el asesor/a de la corredora (dos tareas) - Rodrigo

**Persona primaria (B2B):** el bot asiste al **humano interno**; el cliente final es usuario indirecto (B2C = evolución).

1. **Responder consultas** de asegurados y **validar contra el contrato** antes de comunicarla (cita verificable).
2. **Recombinar** pólizas desde casos del mercado: arma borradores **DEM** (estándar propio de la corredora) para proponérselos a aseguradoras.

- Preguntas típicas: ¿cubre X? ¿por qué no Y? vigencia/renovación, plazos de siniestro, COVID, **rangos de precios de mercado** (vía web citada).
- Valor: responder **sin releer el PDF** y producir propuestas nuevas en minutos.

---

# Perfil del cliente: sin datos personales - Rodrigo/Joel

El bot fija el **perfil mínimo del cliente sin pedir datos identificadores ni guardar nada**: solo las condiciones que las pólizas requieren para acotar cobertura (verificadas en el corpus):

- **edad** (9/9) · **preexistencias** (8/9) · **deportes de riesgo** (7/9) · **Fonasa/Isapre** (7/9) · **embarazo/maternidad** (7/9) · **enfermedades crónicas** (2/9) · **colectivo** (3/9) · **residencia** (1/9).

- **Opciones curadas**, no texto libre · **in-memory (no persiste)** · lo **confirma el asesor** (ya lo conoce por CRM).
- Varias son **datos sensibles** (salud, Ley 19.628) → solo selector de cláusula, nunca retención.
- Salida **condicional y textual** — "según este perfil, el texto condiciona X" — **nunca un precio ni una decisión** (precio → búsqueda web citada).

---

# El problema, en números - Rodrigo

El dolor es **tiempo de búsqueda + riesgo de responder sin respaldo**. Separamos lo que **medimos** de lo que hay que **medir con el negocio**.

| Lo que ya medimos en el MVP | Lo que falta medir con el negocio |
|---|---|
| **2,4 s** para responder con cita (p50 medido, ruta cloud) | **[ ] minutos hoy por consulta** del asesor |
| **227 artículos** en 9 pólizas de depósito: el fragmento fiel está diluido en ese volumen | **[ ] consultas por asesor por día** |
| **100 %** de las respuestas con **fuente verificable** (no opinión) | **[ ] horas/mes** buscando cláusulas |
| artículos de hasta **25,7k chars**: releer el contrato no escala | **[ ] costo de una respuesta sin respaldo** (reclamación) |

**Las 4 preguntas para el cliente** (5 minutos, en la sesión de validación): cuánto tarda hoy una consulta · cuántas hace al día · qué pasa cuando se responde mal · qué parte del tiempo es buscar en el contrato.

> Con estas respuestas el "problema en números" deja de ser un dato de EDA y pasa a ser **el costo del proceso que automatizamos**.

---

# Requisitos → prioridades (orden = criterio de diseño) - Joel

1. **Seguridad** — stack **autoalojado**: la consulta **no llega a ningún proveedor de IA de terceros**.
2. **Trazabilidad** — la respuesta va **siempre con sus fuentes**; la UI las muestra.
3. **0 alucinación** — solo cita lo recuperado; umbral de score; fuentes web marcadas.
4. **Velocidad** (si queda) — `top_k=5`, respuesta en segundos (GPU en la demo).

> Trade-off explícito: **trazabilidad y cero alucinación > velocidad.**

---

# Dónde corre (y qué prometemos) - Rodrigo

Misma arquitectura, mismo corpus, mismos modelos; lo que cambia es **quién opera la máquina**.

| Modo | El modelo corre en | La consulta sale de | Cuándo |
|---|---|---|---|
| **On-premise** | tu oficina / datacenter | nada | datos de clientes reales |
| **Autoalojado en nube** *(el de la demo: VPS con GPU)* | una VPS que administramos | nuestra VPS | demo, piloto, desarrollo |
| **API de terceros** | datacenter de OpenAI/Gemini/… | hacia el proveedor | modo cloud opt-in |

- El claim que sostenemos en los dos primeros modos: **"la consulta no llega a ningún proveedor de IA de terceros"**.
- El corpus del MVP es **público** (Depósito CMF). Con datos de clientes reales la respuesta es **on-premise con la misma imagen Docker**.
- Embeddings, corpus e índice **siempre autoalojados** — en los tres modos.

---

# Alcance y guardrails - Joel

- **Dominio (dentro de las pólizas):** respondemos con citas del corpus.
- **Relacionado (del rubro, fuera del corpus):** web del **agente** — precios y **rangos de valores/precios de mercado** para un tipo de póliza, normativa, compañías reales — con **fuente externa siempre marcada**; **nunca se inventa una cifra**.
- **Fuera de dominio:** no respondemos contenido; explicamos por qué y reiteramos el alcance.
- **Guardrail:** filtro de score (0,6) en código + instrucción de no inventar en la propia llamada · **máx. 2 llamadas LLM por consulta** · sin PII.

---

# Dataset · Fuente y acceso - Cris

- **9 PDFs** descargados de un bucket S3 (los PDFs no se versionan en el repo).
  - Salud: **8** · Accidentes: **1**
  - Periodo 2013–2021 · mercado chileno
- El corpus se reconstruye de forma **reproducible** con un solo comando (descarga → parser → chunking → índice).
- Lenguaje: español legal chileno · **sin PII** en la muestra.

---

# Dataset · Estructura descubierta (EDA) - Cris

- **Matriz esqueleto**: el orden de cláusulas es compatible entre pólizas (posición 2 = cobertura, con excepciones).
- **36 claves canónicas** normalizan estilos de escritura distintos.
- Casos borde detectados y caracterizados:
  - **Póliza COVID** (Ley 21.342) — sintaxis de cabecera atípica.
  - **POL320190074** — documento compuesto con **5 pólizas/anexos anidados**.

---

# Dataset · Calidad (EDA) - Jimmy

- **5 casos de suciedad** formalizados en reglas de limpieza:
  1. Bytes de control
  2. Líneas vacías
  3. Palabras duplicadas ("de de")
  4. Guiones de fin de línea mal unidos
  5. Cabecera del artículo inline en el cuerpo
- La limpieza convierte el texto ruidoso en un corpus limpio y normalizado.
- El boilerplate legal y las referencias inline **se conservan** (son contenido útil).

---

# Dataset · Cómo lo aprovechamos - Jimmy

- **Segmentación por artículo** (227 registros) + metadata:
  `poliza`, `ramo`, `año`, `canonico`, `pagina`, `chars`.
- La metadata es la **capa de filtrado** del retrieval (por cláusula).
- EDA documentado con sus matrices (CSV/JSON).
- Los artículos limpios son la **entrada directa** del chunking y del índice.

---

# Solución · Arquitectura del MVP (componentes) - Julian

Baseline del MVP: agente + web, **≤2 llamadas LLM**, respuestas siempre citadas **+ generación v0 (DEM)**.

```
S3 ─► Parser+limpieza ─► articulos.jsonl (227)
        └─► Chunking 1000/150 ─► chunks.jsonl (758)
                 └─► embeddings qwen3-embedding:0.6b (1024d)
                          ▼
                 Qdrant · colección `polizas`
                   recuperación vectorial  *híbrido BM25/RRF pendiente
                          ▼
                 agente: gate de score (0,6) ─► 1.ª LLM grounded
                   └─ ¿web y es del rubro? ─► búsqueda web (DDG) ─► 2.ª LLM
                   ≤2 llamadas LLM · ≤1 web · citas [POL · Art. N · pág. X]
                          ▼
                 FastAPI: /chat · /chat/stream · /health
                   /policies · /policy-recombine
                 *auth (API key)
                          ▼
                 Chainlit (fuentes + streaming)   *sesión por conversación
                 Generación DEM ─► PDF "BORRADOR · no emitida"
                   *UI de generación DEM

Garantías (transversal) ▶ 146 tests pytest · conjunto de referencia + RAGAS · compose · demo
```

- **Datos:** S3 → parser/limpieza → 227 artículos → 758 chunks (no cruzan artículo).
- **Motor RAG:** Qdrant `polizas` (1024d) → gate de score (0,6) → agente ≤2 llamadas con citas + web marcada.
- **Generación:** recombinación DEM v0 → PDF borrador (sin emisión).
- **Exposición:** FastAPI delgado + Chainlit con fuentes visibles.
- **Garantías:** QA/eval/ops transversal.
- **`*` Mejoras MVP:** búsqueda híbrida · auth · sesión por conversación · UI de DEM.

---

# Solución · Datos - Julian

- **Captura y limpieza:** PDFs → parser (segmentación de artículos + títulos canónicos) → limpieza → 227 artículos con metadata.
- **Chunking:** chunks que **no cruzan de artículo**; `RecursiveCharacterTextSplitter` · `chunk_size=1000` · `overlap=150`.
- Metadata **propagada** desde los artículos (mapeo `canonico` → `titulo_canonico`).
- Formato de datos documentado y versionado.

---

# Solución · Motor RAG — Indexación y retrieval - Marlon

- **Qdrant** × colección `polizas` (1024 dims · coseno) + recuperación vectorial con **score y metadata**.
- Embeddings **`qwen3-embedding:0.6b`** vía Ollama (**autoalojado**, multilingüe).
- `point_id` determinístico (`poliza` + `documento` + `articulo` + `chunk_index`) → index build **idempotente**.
- Los metadatos **viajan con el chunk** (trazabilidad); el umbral de score se aplica aguas abajo.

---

# Solución · Motor RAG — Agente + web - Marlon

El agente es acotado:

1. Recuperación → **filtro de score (0,6)** en código (hard gate).
2. **1.ª llamada:** respuesta *grounded* con citas internas.
3. Si el contexto no alcanza y es del rubro → **2.ª llamada** con búsqueda web → **fuente web marcada** (`origen: web`).
4. Si no hay nada → "no está en las fuentes" + alcance del asistente.

- LLM **`qwen3:4b-instruct`** autoalojado · guardrail de dominio · contrato de citas documentado.
- **Rangos de valores/precios de mercado** (el corpus no tiene precios): se responden por búsqueda web **citada** como rango, nunca inventados.

---

# Solución · Exposición - Luis

- **FastAPI** (`/chat`, `/health`, `/policies`, **`/policy-recombine`**) — **HTTP delgado**: delega en el agente, sin lógica RAG propia.
- **Chainlit** — chat con **fuentes visibles**; las web se diferencian visualmente.
- **Generación v0:** `/policy-recombine` → **PDF borrador DEM** (bloques canónicos + perfil sin PII; marcado "BORRADOR · no emitida").
- Docker compose único · CORS acotado · smoke test del stack.

---

# Solución · Garantías y roadmap - Luis

- **QA:** **146 tests** pytest sin Docker (mocks) — parser, retrieval, API, eval, observabilidad.
- **Eval:** conjunto de referencia de **100 preguntas** → `recall@k`, `cita_ok`, marcación web + RAGAS → **piloto n=7 medido**.
- **Ops:** un comando de despliegue + documentación + demo.
- **Obs:** Langfuse autoalojado, tracing en runtime, **fail-open**.

| Hito | Alcance | Estado |
|---|---|---|
| **Datos** | captura, limpieza y chunking | **entregado** · 227 artículos · 758 chunks |
| **Motor RAG** | retrieval + búsqueda web + agente acotado | **entregado** · Qdrant + web + agente ≤2 llamadas |
| **Generación v0** | recombinación de cláusulas | **entregado** · PDF borrador DEM |
| **Producto** | API + UI + tests + despliegue | **entregado** · FastAPI + Chainlit + 146 tests + compose |
| **Eval + observabilidad** | calidad y tracing en runtime | **entregado** · piloto n=7 + Langfuse |

**Backlog abierto:** búsqueda híbrida · DEM en la UI · auth · sesión por conversación · smoke E2E · corrida completa del conjunto de referencia.

---

# Solución · Garantías · Dónde viven las garantías - Luis

Las garantías **no son runtime**: son la caja transversal del diagrama, **fuera del hot path** del usuario.

```
      Motor RAG ──┐               ┌─ pytest (146) · sin Docker
      Generación ─┼─► Garantías   ┼─ conjunto de referencia + RAGAS
      Exposición ─┘   fuera del   └─ compose · documentación · demo
   (answer, PDF, logs) hot path
        ▲ artefactos (question · contexts · answer · sources)
        └──► retroalimenta umbral / chunking / prompts
```

- Corre **offline** sobre los artefactos que produce el pipeline — nunca dentro del flujo del usuario.
- **Sin latencia** para el usuario; sí agrega un **circuito de retroalimentación**: sus resultados ajustan umbral, chunking y prompts.
- El re-score de una corrida es **offline y sin costo**: la trazabilidad se recalcula desde los artefactos guardados, sin llamar al juez.

---

# Solución · Garantías · Métricas de calidad - Luis

| Eje | Métrica (RAGAS) | Qué mide | Promesa del producto |
|---|---|---|---|
| Retrieval | Context Recall | ¿cuánta de la ground truth recuperó? | cobertura del contexto |
| Retrieval | Context Precision | chunks relevantes arriba, sin boilerplate | calidad de slots y orden |
| Generación | **Faithfulness** | ¿cada afirmación se sostiene en los contexts? | **0 alucinación** |
| Generación | Answer Relevancy / Correctness | responde lo preguntado y coincide con la gold | calidad de la respuesta final |
| Propias | `cita_ok` · marcación web | citas `[POL · Art. N · pág. X]` válidas; `origen: web` correcto | trazabilidad |

- **RAGAS** = herramienta elegida para el eval — **implementada y ejecutada** (piloto n=7 medido).
- No reemplaza lo propio: `cita_ok` y la marcación de web se **codean aparte** (RAGAS evalúa contra contexts, no contra el formato de cita).
- `recall@k` estricto (artículo exacto en el top-5) se reporta **junto** al context recall: miden cosas distintas.

---

# Números · Calidad (piloto n=7) - Luis

**Medido** en el piloto del conjunto de referencia (n=7 · generador `qwen3:4b-instruct` · juez `gemini-3.5-flash-lite` · umbral de score 0,6 · `top_k=5`):

| Métrica | Resultado | Rango |
|---|---|---|
| Faithfulness | **0,911** | 0,625 – 1,000 |
| Context recall | **0,952** | 0,667 – 1,000 |
| Context precision | **0,823** | 0,367 – 1,000 |
| Trazabilidad (`cita_ok`) | **7/7 filas** | — |
| Citas verificables contra sus fuentes | **26/26 (100 %)** | — |
| Recall@k (artículo exacto en top-5) | **3/7** | — |

**Compromiso** (a demostrar con la corrida completa, n=100):

| Métrica | Objetivo |
|---|---|
| `cita_ok` (filas con cita verificable) | **≥ 95 %** |
| Faithfulness | **≥ 0,90** |
| Recall@k (artículo exacto) | **≥ 70 %** |
| Casos de abstención correctos | **≥ 90 %** |

> Los números se re-validan offline sobre la corrida guardada, sin costo de API.

---

# Números · Velocidad y funcionamiento - Marlon

| Señal | Medido | Dónde |
|---|---|---|
| Retrieve (p50) | **0,35 s** | Qdrant + embeddings autoalojados |
| Primera consulta (embedding en frío) | 2–3 s | cache de embeddings |
| Respuesta completa (ruta cloud) | **≈ 2,4 s** | p50 |
| Ruta de abstención | ≈ 2,3 s | sin inventar, reitera alcance |
| Respuesta completa (autoalojado **sin GPU**) | hasta **146 s** | por eso la demo usa GPU |
| Llamadas LLM por consulta | **≤ 2** | límite del diseño |
| Consultas con traza completa | **100 %** | Langfuse, 4–6 spans por consulta |

- El **gate por score es en código**: un chunk bajo el umbral (0,6) nunca llega al prompt.
- **Fail-open**: si la observabilidad se cae, el chat **sigue respondiendo** (disponibilidad > telemetría).
- En la VPS con GPU, la ruta autoalojada baja de ~146 s al orden de **1–3 s** → es la cifra que se mide en la demo.

---

# Números · Costo: autoalojado vs API - Rodrigo

| | **Autoalojado** (VPS con GPU) | **API de terceros** (Gemini 3.5 Flash Lite) |
|---|---|---|
| Costo por consulta | **$0** (ya está pagada la VPS) | **≈ $0,0007 – $0,0015** |
| Qué se paga | la VPS, por hora | tokens: ~$0,15–0,30 / 1M in · ~$1,25–2,50 / 1M out\* |
| Volumen | ilimitado | se factura por uso |
| Corpus + embeddings | **autoalojados** (sin costo) | los mismos |
| Riesgo | capacidad de la VPS | dependencia + precio por token |

\* precios de referencia, **a verificar contra la tabla oficial vigente**.

- Consumo real medido por consulta: **~1,2k tokens in / ~450 out** → **650–1.400 consultas por USD**.
- **Punto de equilibrio = costo mensual de la VPS ÷ costo por consulta de la API.** Con una VPS de USD 100/mes → **~70.000–140.000 consultas/mes**. *(ponemos el precio real de la VPS)*.
- **La decisión es de negocio, no técnica**: depende de las consultas/mes y de si el corpus es del cliente (→ on-premise).

---

# Números · Límites (lo que NO sabemos) - Rodrigo

Lo que **no** afirmamos, porque no está medido:

- **n=7, no 100.** Sin intervalos de confianza → los números son **tendencias**, no garantía.
- **Abstención sin medir**: el piloto solo cubrió `answer_from_policy`. El claim *"no alucina fuera de cobertura"* **todavía no está respaldado por datos**.
- **Ruta web sin medir** en el piloto (corrida sin búsqueda web).
- **Recall@k = 3/7**: el retriever trae la **información** (context recall 0,95) pero no siempre el **mismo artículo** → se ataca con búsqueda híbrida.
- **Precision 0,367 en 1 caso**: el umbral fijo (0,6) deja pasar contexto marginal con `top_k=5`.
- **Juez cloud**: los scores dependen del juez; la calibración local ↔ cloud (n=20) quedó pendiente.
- **Corpus público**: no hay datos de clientes reales.
- **Sin GPU en desarrollo**: la demo corre en una VPS con GPU; el equipo de desarrollo usa CPU.

---

# Solución · Post-MVP: orquestación con LangGraph - Rodrigo

Mismos componentes y contratos (**≤2 llamadas LLM**, filtro de score en código, respuesta con sus fuentes): cambia **solo el orquestador**.

```
pregunta (thread_id)
     │
     ▼
recuperación ─► gate de score ─► generar
                                       │
                         ┌─────────────┴─────────────┐
                         │ ¿web y es el rubro?       │
                         └─────────────┬─────────────┘
                            sí ─────────┘        └─────── no ──► answer + sources[]
                                       │
                                       ▼
                              búsqueda web ─► generar ─► answer + sources[]

astream_events: status · token · sources  ──►  API / UI
checkpointer: estado + historial por conversación (thread_id)
```

- **Un grafo, dos consumos:** `.invoke()` (sync) y `.astream()` (SSE) → desaparece la duplicación entre el camino sincrónico y el streaming.
- **Checkpointer:** sesión por conversación persistente sin código propio de sesiones.
- **`astream_events`:** eventos por nodo (reemplaza la inspección manual de la decisión de búsqueda web).
- **Trazas por nodo:** eval de caminos del conjunto de referencia (grounded / web / no-fuente).
- **Sin features nuevos;** los nodos futuros (clasificador de intención, DEM→POL) se enchufan al mismo grafo.

---

# Demo en vivo - Rodrigo

Tres consultas que cubren los tres caminos del agente:

| # | Consulta | Qué hay que mirar |
|---|---|---|
| 1 | ¿Qué cubre el deducible de la póliza X? | respuesta **con cita** `[POL · Art. N · pág. X]` + **fuentes visibles** en la UI |
| 2 | Pregunta fuera del corpus | **abstención**: "no está en las fuentes" + reitera alcance, **sin inventar** |
| 3 | ¿En qué rango está la prima de una póliza de salud individual? | **fuente web marcada** (nunca igualada a cita de póliza) |

Opcional: `/policy-recombine` → **PDF borrador DEM** ("BORRADOR · no emitida").

- Traza de cada consulta en **Langfuse** (misma sesión): recuperación → gate → generación.
- **Plan B:** video pregrabado con las mismas 3 consultas.

---

<!-- _class: lead -->

# Próximos pasos

1. **Corrida completa del conjunto de referencia (n=100)** con juez local → confirmar los compromisos de la slide de calidad
2. **Búsqueda híbrida** (BM25 + RRF) para cerrar el `recall@k`
3. **Sesión por conversación** con LangGraph + checkpointer
4. **Auth por API key** en el API y **generación DEM desde la UI**
5. **Smoke E2E** del stack en CI

**¿Preguntas?**

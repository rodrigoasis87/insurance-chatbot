# Evaluación de calidad del RAG (célula G1)

> **Estado**: runner implementado en `feature/ragas` (#19); corrida completa
> aún pendiente por el costo del juez local. Este documento describe la
> arquitectura completa del eval, con y sin RAGAS.

## 1. Objetivo y alcance

El eval responde, de forma reproducible, qué tan bien funciona el pipeline RAG
(#19, #20):

- **¿Recupera los artículos correctos?** (retrieval)
- **¿Cita solo fuentes reales de su respuesta?** (citas deterministas)
- **¿Se abstiene cuando debe?** (sin inventar montos ni datos personales)
- **¿Rutea a web cuando el corpus no alcanza?** (ADR-005)

**Lo que NO hace**: no certifica legalmente las respuestas. Las métricas RAGAS
usan un LLM como juez y son estimaciones; `cita_ok` valida existencia de la
cita, no su pertinencia.

## 1.1 Eval (offline) vs observabilidad (online)

Son dos capas distintas de la misma garantía G1 y **no se mezclan**:

| | Eval (este documento) | Observabilidad Langfuse (#48) |
|---|---|---|
| **Cuándo** | Offline, por lotes, sobre el golden set | En vivo, dentro de `query()` / `query_stream()` |
| **Sobre qué** | 100 preguntas curadas | Cada consulta real del usuario |
| **Qué produce** | Métricas agregadas (`recall@k`, `cita_ok_rate`, RAGAS…) | Un trace por consulta (spans, latencia, ruta, errores) |
| **Dónde corre** | Fuera de Docker, sin red, en el pipeline de CI | En el hot path del API (fail-open) |
| **Para qué** | ¿El sistema es bueno *en promedio*? | ¿Qué pasó *en esta* consulta? ¿Está degradándose? |
| **Detalle** | este documento | `docs/OBSERVABILITY.md` |

Comparten el vocabulario de **ruta** (`policy` · `web` · `abstain` ·
`web_failed`): el eval la lee de `trace["route"]` y el tracer la escribe en
`metadata.route` del span raíz, así una fila del golden set y un trace de
producción se leen igual.

## 2. Mapa de componentes

| Componente | Ruta | Rol |
|---|---|---|
| Golden set | `data/evaluation/ragas_golden.jsonl` | 100 preguntas de referencia (versionado en git) |
| Lógica pura | `app/rag/eval.py` | `load_golden`, `expected_hit`, `cita_ok`, `cap_policy`, `BEHAVIORS` — sin red ni RAGAS |
| Runner | `scripts/evaluate_ragas.py` | Ejecuta el golden set contra el pipeline real y calcula todas las métricas |
| Instrumentación | `app/rag/query.py` (`query(trace=…, progress=…)`) | Captura ruta y contextos por pregunta sin cambiar el JSON público |
| Resultados | `data/evaluation/results/<run_id>/` | `run.json` + `results.jsonl` + `summary.json` (gitignored) |
| Reporte | `docs/eval/LATEST.md` | Resumen Markdown de la última corrida con `--report-doc` |
| Umbral (ADR-004) | `docs/umbral_score.md` | Origen empírico de `UMBRAL_SCORE=0.60` (hard gate dentro del eval) |
| Análisis de umbral | `scripts/analisis_umbral.py` | Distribución de scores de `search()` (44 queries, 3 clases) |
| Tests | `tests/test_rag_eval.py` | 18 tests puros de la lógica de evaluación |
| Dependencia | `pyproject.toml` → grupo `eval` | `ragas>=0.4.3` (se instala con `uv run --group eval`) |
| Observabilidad | `app/observability/` + `docs/OBSERVABILITY.md` | Tracing en runtime con Langfuse (opcional, noop por defecto) |

## 3. Golden set

`data/evaluation/ragas_golden.jsonl`, 100 filas:

| Comportamiento (`expected_behavior`) | n | Qué espera |
|---|---|---|
| `answer_from_policy` | 60 | Respuesta anclada al corpus; `reference_contexts` = artículos esperados (`poliza`, `documento`, `articulo`, `canonico`) |
| `answer_from_web` | 20 | Respuesta con fuente externa; `reference_sources` = URLs CMF Educa |
| `abstain_personal_information` | 12 | Abstenerse por datos personales |
| `abstain_insufficient_information` | 5 | Abstenerse: el corpus no da la respuesta |
| `abstain_missing_information` | 2 | Abstenerse: faltan condiciones particulares |
| `abstain_missing_contact` | 1 | Abstenerse: pide datos de contacto (teléfono) |

Campos por fila: obligatorios `id` (estable, para comparar corridas),
`question`, `reference_answer`, `expected_behavior`; opcionales según
comportamiento `reference_contexts` (póliza) o `reference_sources` (web).
`load_golden()` valida todo esto y falla rápido ante filas malformadas.

Reglas de curación (detalle en `RAGAS.md`): respuestas de referencia acotadas
a una póliza concreta, sin mezclar artículos de otra póliza, y citando el
límite cuando el artículo remite a condiciones particulares. Es una base para
revisión humana; 100 filas no garantizan representatividad estadística.

## 4. Métricas deterministas (sin RAGAS)

Calculadas siempre, para todos los comportamientos, sin LLM juez:

- **`expected_context_retrieved`** (`expected_hit`): ¿algún hit recuperado
  (`trace.retrieval_hits`) coincide con un `reference_contexts` esperado?
  `None` si la fila no define contextos esperados (p. ej. web).
- **`cita_ok` / `cita_ok_rate`**: cada cita inline de la respuesta
  (`[fuente: POL… · Art. N]` o `[fuente web: <url>]`) debe existir en las
  fuentes devueltas. `ok` exige ≥1 cita y 100 % válidas; `rate` =
  válidas/citadas (`None` sin citas → no aporta al promedio).
- **`expected_abstention_complied`**: para filas `abstain_*`, ¿la ruta fue
  `abstain` y la respuesta exactamente `NO_EN_FUENTES`?
- **`web_routing_rate`**: para filas `answer_from_web`, ¿la respuesta incluye
  alguna fuente `origen == "web"`?

Además se registra `actual_route` (`policy`, `web`, `abstain`, `web_failed`)
tomada del `trace` de `query()`.

## 5. Métricas RAGAS (con juez LLM)

Se aplican **solo a filas `answer_from_policy` con contextos posteriores al
hard gate** (sin contexto no hay nada que juzgar):

- **`faithfulness`**: ¿la respuesta está soportada por los contextos
  recuperados? (no exige respuesta de referencia)
- **`context_recall`**: ¿los contextos recuperados cubren la
  `reference_answer`?
- **`context_precision`**: ¿los contextos relevantes están bien ordenados?
  (variante *With Reference*)

El juez es configurable: `--judge ollama` (default, `qwen3:4b-instruct`, el
mismo modelo que genera → puede correlacionar errores) o `--judge google`
(Gemini vía endpoint compatible con OpenAI, sin sumar `litellm`). Temperatura
0; fallos por métrica/fila se registran como `error` sin abortar la corrida.

## 6. Cómo ejecutar

Requisitos: Qdrant + Ollama arriba (`docker compose up -d qdrant ollama`),
colección indexada, y para `--judge google` una `GOOGLE_API_KEY` en `.env`.

```bash
# Corrida base (todos los comportamientos, sin web)
uv run --group eval python scripts/evaluate_ragas.py --no-web

# Piloto de una pregunta (smoke test)
uv run --group eval python scripts/evaluate_ragas.py \
  --limit 1 --behavior answer_from_policy --no-web --metrics faithfulness

# Muestra aleatoria reproducible de 2 preguntas de póliza
uv run --group eval python scripts/evaluate_ragas.py \
  --n=2 --behavior answer_from_policy --no-web --metrics faithfulness --seed 42

# Reporte Markdown versionado
uv run --group eval python scripts/evaluate_ragas.py --no-web \
  --max-policy 10 --seed 42 --judge google --report-doc docs/eval/LATEST.md
```

Flags principales: `--n` / `--limit` (muestra), `--seed` (reproduce la
muestra), `--behavior` / `--exclude-behavior` (filtros), `--no-web` (desactiva
`web_search`; recomendado en la corrida base — los casos web van aparte),
`--max-policy` (tope de casos póliza vía `cap_policy`), `--metrics`, `--judge`,
`--report-doc`. `--n` y `--limit` son excluyentes.

## 7. Reproducibilidad

Cada corrida escribe `data/evaluation/results/<run_id>/run.json` con todo lo
necesario para repetirla o compararla:

- `git_commit` del código evaluado y `corpus_sha256` de
  `data/processed/articulos.jsonl`
- modelos: `generator_*` (Ollama), `judge_*`, `embedding_model`
- estado del retrieval: `score_threshold` (hard gate ADR-004), `top_k`,
  colección Qdrant con `points_count` y `status`
- muestra: `selected_question_ids`, `sample_seed`, `max_policy`,
  `behavior_filter`, `excluded_behaviors`, `no_web`, `metrics`

Si cambia el modelo de embeddings o se re-indexa el corpus, re-medir el umbral
(ver `docs/umbral_score.md` §5) antes de comparar corridas.

## 8. Resultados

Por corrida (`<run_id>` = timestamp UTC):

- **`results.jsonl`** — una fila por pregunta: respuesta, `actual_route`,
  contextos (`policy_retrieved_contexts`, `web_retrieved_contexts`,
  `answer_contexts`), hits de retrieval con score, detalle de citas y, para
  póliza, los scores RAGAS.
- **`summary.json`** — agregados:
  - `by_behavior`: por comportamiento — `count`, distribución de `routes`,
    `expected_context_recall_at_k` (media de `expected_hit`),
    `cita_ok_rate`, `cita_ok_compliance` (media de `cita_ok`),
    `abstention_compliance`, `web_routing_rate`;
  - `ragas_metrics`: `mean`, `scored`, `errors` por métrica.

`--report-doc docs/eval/LATEST.md` vuelca lo esencial como Markdown
versionado (los crudos siguen gitignored).

## 9. Estado actual y roadmap

- Runner + lógica pura + 18 tests en `feature/ragas` (#19); `cita_ok` y juez
  configurable cierran el DoD de #19.
- 5 corridas piloto en `data/evaluation/results/` (la última: 30 casos con
  juez Gemini). Falta una **corrida completa** (100 preguntas) y su reporte.
- Pendiente post-corrida: revisión humana del golden set (preguntas ambiguas
  detectadas en el piloto), decidir si subir `--max-policy` para la corrida
  oficial, y vincular el resultado a #20 (demo day).
- El umbral se re-evalúa con el golden set completo (#19 cierra la deuda de
  `docs/umbral_score.md` §3).

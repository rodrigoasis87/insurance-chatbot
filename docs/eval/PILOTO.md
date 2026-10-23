# Piloto RAGAS (n=7) — números de referencia

> Fuente **autoritativa** de los números de calidad que se presentan en
> `docs/presentation/slides_es.md`. Los resultados crudos viven en
> `data/evaluation/results/` (ignorado por git); este documento es la versión
> versionada y re-calculable offline.

## Qué es esta corrida

Piloto de la evaluación RAG (#19) sobre el golden set curado, con el
comportamiento `answer_from_policy` únicamente. El generador de respuestas es
el modelo local del MVP y el juez es un modelo cloud. **No es la corrida
completa** (n=100): es una muestra de 7 casos para validar el pipeline de
evaluación de punta a punta.

## Metadata de la corrida

| Campo | Valor |
|---|---|
| Run id | `20261019T185741581768Z` |
| Fecha | 2026-10-19 |
| Commit | `556b39a` |
| Generador | `ollama` / `qwen3:4b-instruct` |
| Juez | `google` / `gemini-3.5-flash-lite` (max_tokens 1024) |
| Embeddings | `qwen3-embedding:0.6b` |
| Índice | Qdrant `polizas`, 758 puntos, estado `green` |
| Corpus | `sha256:b87a4fe332d776f8042b3a2e7c606746e50b828e36f6e9c8675350e997c12648` |
| Umbral (hard gate) | `0.6` |
| `top_k` | 5 |
| Métricas RAGAS | faithfulness, context_recall, context_precision |
| Muestra | seed 42, `max_policy=10`, sin web, excluidos `answer_from_web` |

## Resultados por caso

| Caso | Recall@k (artículo exacto) | Faithfulness | Context recall | Context precision | Citas | Citas válidas |
|---|---|---|---|---|---|---|
| ragas-051 | no | 0.625 | 1.000 | 0.806 | 4 | 4 |
| ragas-008 | no | 0.750 | 0.667 | 0.639 | 3 | 3 |
| ragas-002 | sí | 1.000 | 1.000 | 1.000 | 4 | 4 |
| ragas-058 | no | 1.000 | 1.000 | 0.367 | 3 | 3 |
| ragas-018 | no | 1.000 | 1.000 | 1.000 | 3 | 3 |
| ragas-016 | sí | 1.000 | 1.000 | 1.000 | 4 | 4 |
| ragas-015 | sí | 1.000 | 1.000 | 0.950 | 5 | 5 |

## Agregados (n=7)

| Métrica | Media | Mínimo | Máximo |
|---|---|---|---|
| Faithfulness | **0.911** | 0.625 | 1.000 |
| Context recall | **0.952** | 0.667 | 1.000 |
| Context precision | **0.823** | 0.367 | 1.000 |
| Recall@k (artículo de referencia en el top-5) | **3/7 (43%)** | — | — |
| Trazabilidad (`cita_ok`) | **7/7 filas** | — | — |
| Citas verificables contra `sources` | **26/26 (100%)** | — | — |

Dos matices que conviene no esconder:

- **Recall@k = 3/7 no contradice el context_recall = 0.952.** El juez evalúa si
  el *contexto entregado* cubre la respuesta de referencia (0.95); el recall@k
  estricto exige que aparezca el *artículo exacto* citado en el golden set
  (43%). En los 4 casos fallidos el retriever entregó un chunk de **otro
  artículo con la misma cobertura** (p. ej. ragas-058: cobertura 1.0 con
  precisión 0.37). El sistema encuentra la **información**; no siempre el
  **mismo artículo**. Es el gap exacto que ataca el issue #42 (hybrid search).
- **Precision baja en 1 caso (0.367).** ragas-058 trae 5 fuentes de las cuales
  solo 3 son pertinentes: el hard gate por score (0.6) deja pasar contexto
  marginal. Es el trade-off conocido de `top_k=5` con umbral fijo.

## Trazabilidad: el fix del validador de citas

La corrida original registró `cita_ok = 1/7`. Era un **falso negativo del
validador**, no un problema del modelo: el regex de `app/rag/eval.py` solo
reconocía `[fuente: POL… · Art. N]` sin página, mientras el modelo emite
`[fuente: POL… · Art. N · pág. X]` y a veces `[1] POL… · Art. N · pág. X: …`.
Las citas no se detectaban, no se contaban y la fila quedaba como "sin cita
válida".

| | Registrado en la corrida | Recalculado (código actual) |
|---|---|---|
| Filas con `cita_ok` | 1/7 | **7/7** |
| Citas detectadas | 1 | **26** |
| Citas válidas | 1 | **26** |

El formato de cita y la **página son opcionales** por contrato
(`docs/CONTRACTS.md` §3): la identidad de la cita es `(poliza, articulo)`.

## Límites de esta corrida (lo que NO mide)

- **n=7.** No es la corrida completa del golden set (100 preguntas) y no
  permite intervalos de confianza.
- **Solo `answer_from_policy`.** No hay casos de abstención ni de respuesta
  web en esta muestra → **no hay medición de abstención** (el reclamo de
  "no alucina fuera de cobertura" todavía **no está respaldado por datos**).
- **Sin web** (`--no-web`).
- **Una sola corrida** → sin variabilidad entre ejecuciones.
- **Juez cloud** (`gemini-3.5-flash-lite`): los scores de RAGAS dependen del
  juez. La calibración local ↔ cloud (n=20) quedó pendiente.
- **Corpus público** (Depósito CMF): no hay datos de clientes reales.

En consecuencia, en la presentación **no se publican** las métricas que no
están medidas: `faithfulness 0.94`, `Hit@1 65%` y cualquier tasa de
abstención.

## Cómo reproducir

Re-score offline (sin red, sin juez, sin costo) de la corrida guardada:

```bash
uv run python scripts/rescore_citas.py data/evaluation/results/20261019T185741581768Z
```

Salida esperada: `cita_ok (recalculado): 7/7`, `citas: 26 | válidas: 26`, y las
medias RAGAS de la tabla de agregados.

Corrida original (sí consume API del juez; no hace falta para re-scoring):

```bash
uv run --group eval python scripts/evaluate_ragas.py \
  --limit 7 --max-policy 10 --judge google --no-web --seed 42 \
  --report-doc docs/eval/LATEST.md
```

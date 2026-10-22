# UMBRAL_SCORE: distribución empírica de scores de `search()`

> **Fecha**: 2026-10-07 · **Modelo de embeddings**: `qwen3-embedding:0.6b`
> (1024 dims, cosine) · **Colección**: `polizas` (758 puntos, 14 sub-documentos)
> · **`search()` con colapso por `(poliza, articulo)`** activo (CONTRACTS §2).
>
> **Actualización 2026-10-22 (#42)**: modo híbrido (`RETRIEVAL_MODE=hybrid`,
> denso + BM25 con RRF). Re-medición del denso, distribución fusionada,
> calibración de `UMBRAL_SCORE_HYBRID` y A/B con el golden set en §7–8.

Este documento fija el hard gate `UMBRAL_SCORE` con evidencia, en vez de un
número inventado. Se re-mide si cambia el modelo de embeddings o el corpus
(ver *Limitaciones*).

## 1. Metodología

`scripts/analisis_umbral.py` corre `search(q, top_k=5)` sobre las 3 clases de
preguntas y vuelca el detalle a `data/processed/umbral_raw.json`:

| clase | n | qué mide |
|---|---|---|
| `dominio`   | 26 | preguntas contestables con las pólizas, con el cánonico que debería ganar (ground truth) |
| `adyacente` | 12 | del rubro salud/seguros pero **no** contestables con el corpus ("¿el color del auto?", "¿cuánto tarda la ambulancia?") |
| `ajena`     | 6  | sin relación con seguros ("¿quién ganó el mundial 2022?") |

## 2. Resultados

**Score del top-1 por clase:**

| clase | min | p10 | p50 | p90 | max |
|---|---|---|---|---|---|
| dominio   | 0.555 | 0.600 | 0.691 | 0.749 | 0.763 |
| adyacente | 0.458 | 0.500 | 0.528 | 0.606 | 0.634 |
| ajena     | 0.255 | 0.255 | 0.295 | 0.360 | 0.406 |

**Histograma del top-1 por clase** (bin = 0.1):

```
score ->         0.2  0.3  0.4   0.5   0.6   0.7
dominio:                          ▓▓▓  ██████████^█^█^██   (3, 11, 12)
adyacente:                ▓▓  ▓▓▓▓▓▓▓  ▓▓▓  (2, 7, 3)
ajena:        ▓▓▓▓  ▓  ▓  (4, 1, 1)
```

**Retrieval sobre 26 de dominio:**
- Hit@1 (ground-truth cánonico en top-1): **17/26**
- Hit@5: **24/26**
- Top-1 < `0.60`: 3 (0.555, 0.596, 0.600) — de esos, **2 son misses** de todos
  modos (`declaraciones`→`denuncia de siniestro`, `definiciones`→`clausulas
  adicionales`); solo se perdería `pais de residencia` (0.555, correcto pero
  presente en el resto del contexto).

## 3. Propuesta

### `UMBRAL_SCORE = 0.60`

- **Bloquea el 100 % de las "ajenas"** (max 0.406 ≪ 0.60).
- **Bloquea 9/12 "adyacentes"**; las 3 que pasan (0.606, 0.617, 0.634) son
  semánticamente limítrofes ("¿puedo pagar con tarjeta?", "¿cuánto tarda la
  ambulancia?", "¿qué pasa si me cambio de trabajo?") — exactamente el caso que
  la 2ª llamada del agente (#17) debe mandar a `web_search` (#8).
- **Conserva 23/26 top-1 relevantes** (88 %); los 3 descartados no eran
  recuperación útil (2 misses + 1 con contexto disponible abajo).

**Alternativa más conservadora: `0.64`** — bloquea el 100 % de las "adyacentes",
pero descarta la banda relevante de 0.60–0.64 y erosiona recuperación sin
ganancia proporcional. Se vuelve a evaluar en #19 (Golden Set).

> Regla del contrato (CONTRACTS §2): `score < UMBRAL_SCORE` es hard gate en
> código; un chunk bajo umbral **jamás llega al prompt**. Se define en
> `app/rag/config.py` (ADR-001) y se lee con `get_settings().umbral_score`.

## 4. Lo que este umbral NO resuelve (para #19)

- **Boilerplate entre pólizas**: en dominio, en promedio **2.81 de los 5 slots**
  del top-k están ocupados por un cánonico que ya aparece en el mismo top-5
  (cláusulas estándar idénticas entre pólizas). Es legítimo (la cita difiere),
  pero empobrece la diversidad del contexto → el Golden Set (#19) debería medir
  y decidir si colapsar por `(categoría semántica)` es rentable.
- **Misses de cánonico** (`carencia`, `beneficiarios`, `agravacion del riesgo`,
  `exclusiones`…): errores de ranking del embedding, no del umbral; se atienden
  con mejor query o re-ranking, no subiendo el corte.

## 5. Limitaciones

- `n` chico (44 queries) y etiquetas manuales de ground-truth.
- Umbral específico de `qwen3-embedding:0.6b`; **re-medir si se cambia el modelo
  de embeddings o se re-indexa** con otro chunking.
- El solapamiento `adyacente`/`dominio` (0.555–0.634) es irreducible con cosine:
  fundamenta el juicio del agente en la 2ª llamada más que un corte más alto.

## 6. Reproducir

```bash
docker compose up -d qdrant ollama          # stack arriba
uv run python -m app.rag.indexer            # si hace falta re-indexar (758 pts)
uv run python scripts/analisis_umbral.py    # sobreescribe umbral_raw.json
uv run python scripts/analisis_umbral.py --mode hybrid             # umbral_raw_hybrid.json
uv run python scripts/analisis_umbral.py --mode hybrid --sin-piso  # fusión pura (§7.2)
uv run python scripts/ab_retrieval.py       # A/B determinístico sobre el golden set (§8.1)
```

## 7. Modo híbrido: distribución fusionada y `UMBRAL_SCORE_HYBRID` (#42)

> **Fecha**: 2026-10-22 · mismas 44 queries de §1 · colección `polizas` en
> vivo (777 puntos: los 758 de `chunks.jsonl` + 19 puntos viejos, ver §7.5) ·
> BM25 (`rank-bm25` 0.2.2, `BM25Okapi`) sobre los 758 chunks de
> `chunks.jsonl` · RRF con k=60 y 20 candidatos por lista (`top_k × 4`).

### 7.1 Qué es el score fusionado

`rrf(d) = Σ_listas 1 / (60 + rank(d))`, normalizado por el máximo posible
`2 / 61`: queda en `(0, 1]`. `1.0` = primero en el ranking denso **y** en el
BM25; `0.5` = primero en uno solo; un chunk en el puesto 20 de una sola lista
vale `0.38`. Solo depende de **posiciones**: dice qué tan arriba quedó un chunk
*para esta pregunta*, no qué tan relevante es en términos absolutos.

### 7.2 Fusión pura (sin piso): el score RRF no sirve como hard gate

`analisis_umbral.py --mode hybrid --sin-piso` (top-1 por clase):

| clase | min | p10 | p50 | p90 | max |
|---|---|---|---|---|---|
| dominio   | 0.500 | 0.500 | 0.955 | 0.992 | 1.000 |
| adyacente | 0.500 | 0.500 | 0.953 | 0.992 | 1.000 |
| ajena     | 0.500 | 0.500 | 0.500 | 0.500 | 0.901 |

Toda pregunta tiene un primero en alguna lista (≥ 0.5) y las adyacentes
comparten vocabulario con el corpus ("póliza", "cubre", "seguro"), así que
denso y BM25 coinciden igual que en el dominio. Barrido:

| umbral | dominio pasa | hit@1 que pasa | adyacente bloq. | ajena bloq. |
|---|---|---|---|---|
| ≤ 0.50 | 26/26 | 13 | 0/12 | 0/6 |
| 0.60–0.80 | 22/26 | 11 | 3/12 | 5/6 |
| 0.90 | 20/26 | 11 | 4/12 | 5/6 |

Ningún corte separa las clases: el mejor (0.60) deja pasar 9/12 adyacentes y
1 ajena y ya pierde 4 preguntas del dominio. Con el denso a 0.60 se bloquean
8/12 adyacentes y 6/6 ajenas (§7.4).

### 7.3 Decisión: piso semántico antes de fusionar + gate sobre la fusión

En `hybrid`, `search()` solo fusiona chunks **semánticamente elegibles**:
coseno ≥ `UMBRAL_SCORE` (0.60, el gate denso de §3). Los chunks que solo trae
BM25 y no están entre ellos se descartan; BM25 reordena el pool elegible y
aporta su señal léxica al ranking. Después `query()` aplica
`UMBRAL_SCORE_HYBRID` sobre el score fusionado. Distribución resultante
(`--mode hybrid`; sin hits = 0):

| clase | min | p10 | p50 | p90 | max |
|---|---|---|---|---|---|
| dominio   | 0.000 | 0.500 | 0.977 | 1.000 | 1.000 |
| adyacente | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 |
| ajena     | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

Barrido de `UMBRAL_SCORE_HYBRID` (top-1, 44 queries):

| umbral | dominio pasa | hit@1 que pasa | adyacente bloq. | ajena bloq. |
|---|---|---|---|---|
| 0.00–0.50 | 24/26 | 15 | 8/12 | 6/6 |
| 0.60–0.90 | 19/26 | 12 | 8/12 | 6/6 |

Barrido por hit sobre el golden set (`ab_retrieval.py`, 60 filas de póliza y
20 de abstención; recall post-gate = artículo de referencia entre los hits que
pasan el gate):

| `UMBRAL_SCORE_HYBRID` | recall post-gate | hits/pregunta | abstención |
|---|---|---|---|
| 0.00 | 0.717 | 4.50 | 0.55 |
| **0.40** | **0.717** | **4.50** | **0.55** |
| 0.45 | 0.717 | 4.45 | 0.55 |
| 0.50 | 0.617 | 3.30 | 0.55 |

**`UMBRAL_SCORE_HYBRID = 0.40`**: el valor más alto sin pérdida medida de
recall. Corta los hits que aparecen en una sola lista y en el fondo (puesto ≥ 17
⇒ score < 0.40), sin tocar a ninguno que sea referencia del golden set. Desde
0.50 se pierde el 10 % del recall (cae todo hit que esté en una sola lista y no
sea su primero) sin bloquear ninguna adyacente o ajena extra: la abstención la
decide el piso semántico.

### 7.4 Re-medición del denso (misma fecha y colección)

| clase | min | p10 | p50 | p90 | max |
|---|---|---|---|---|---|
| dominio   | 0.554 | 0.601 | 0.707 | 0.756 | 0.789 |
| adyacente | 0.457 | 0.502 | 0.528 | 0.606 | 0.637 |
| ajena     | 0.260 | 0.260 | 0.295 | 0.363 | 0.403 |

Hit@1 17/26 · Hit@5 25/26. A 0.60: 24/26 dominio pasan, 8/12 adyacentes y 6/6
ajenas bloqueadas. Consistente con §2–3: **`UMBRAL_SCORE = 0.60` se mantiene**.

### 7.5 Limitaciones

- La colección `polizas` en vivo tiene **19 puntos que no están en
  `chunks.jsonl`** (777 vs. 758; metadata sin `documento` ni `familia`, de una
  indexación anterior). Afectan solo al ranking denso; BM25 se arma desde
  `chunks.jsonl`. Se repitió el A/B determinístico sobre una colección limpia
  (§8.1) y la conclusión no cambia. Para limpiarla:
  `uv run python -m app.rag.indexer --recreate`.
- El corpus tiene mucho boilerplate idéntico entre pólizas (ADR-004): los
  empates de coseno se ordenan distinto según cuántos candidatos se piden, y el
  golden set exige la póliza exacta. Diferencias de ±2 preguntas (±0.03) están
  dentro de ese ruido.
- Igual que §5: `n` chico; re-medir si cambia el modelo de embeddings, el
  chunking o la tokenización de BM25 (`app/rag/bm25.py`).

## 8. A/B híbrido vs. denso con el golden set (#19)

Golden set `data/evaluation/ragas_golden.jsonl` (#19): las 60 filas
`answer_from_policy` + 20 `abstain_*` (las 20 `answer_from_web` quedan fuera:
no tienen contexto de póliza). Misma colección, mismo generador y mismo commit
(`eae6e7d`) en ambos modos; solo cambia `RETRIEVAL_MODE` (y con él el gate:
0.60 coseno vs. 0.40 RRF).

### 8.1 Retrieval, sin LLM (`scripts/ab_retrieval.py`)

Métricas sobre el top-5 de `search()`; "recall post-gate" es el
`expected_context_retrieved` del runner RAGAS; "abstención" = filas
`abstain_*` sin ningún hit sobre el gate.

| Métrica | dense | hybrid | Δ | Δ en colección limpia¹ |
|---|---|---|---|---|
| recall@1 | 0.417 | 0.367 | −0.050 | −0.017 |
| recall@3 | 0.600 | 0.617 | +0.017 | +0.033 |
| recall@5 | 0.733 | 0.717 | −0.017 | +0.017 |
| MRR | 0.520 | 0.504 | −0.016 | +0.014 |
| recall post-gate | 0.733 | 0.717 | −0.017 | +0.033 |
| hits/pregunta (póliza) | 4.48 | 4.50 | +0.02 | 0.00 |
| abstención | 0.550 | 0.550 | 0.000 | 0.000 |

¹ Colección temporal indexada desde `chunks.jsonl` (758 puntos, sin los 19
puntos viejos de §7.5) y borrada después de medir: dense 0.750 / hybrid 0.767
de recall@5.

### 8.2 RAGAS: Context Recall / Context Precision

`RETRIEVAL_MODE=<modo> uv run --group eval python scripts/evaluate_ragas.py
--no-web --exclude-behavior answer_from_web --metrics context_recall
context_precision` · generador y juez `qwen3:4b-instruct` (Ollama local) ·
80 filas, 60 evaluadas por RAGAS en cada modo, 0 errores.

| Métrica | dense | hybrid | Δ (hybrid − dense) | por pregunta (mejor / peor / igual) |
|---|---|---|---|---|
| Context Recall | 0.911 | 0.912 | **+0.001** | 3 / 4 / 53 |
| Context Precision | 0.866 | 0.844 | **−0.022** | 9 / 14 / 37 |
| `expected_context_recall_at_k` | 0.733 | 0.717 | −0.017 | — |
| Abstención (`abstain_*`, 20) | 11/20 | 11/20 | 0 | mismas rutas en ambos modos |

Corridas: `data/evaluation/results/20261022T204802581478Z` (dense) y
`20261022T210243294679Z` (hybrid), gitignored.

### 8.3 Conclusión

- **Sin ganancia medible** en este corpus y este golden set: Context Recall
  igual, Context Precision −0.02 (dentro del ruido de un juez LLM de 4B con 60
  preguntas) y recall@k ±0.02–0.05 según la colección. El híbrido cambia los
  hits que llegan al prompt en 54 de 80 preguntas, pero en promedio no los mejora.
- Por qué: las preguntas del golden set están **parafraseadas** (lenguaje del
  asegurado, no del contrato), terreno del embedding; y el boilerplate idéntico
  entre pólizas hace que BM25 empate entre clones y no desempate a favor de la
  póliza correcta.
- **Decisión: `RETRIEVAL_MODE=dense` sigue como default.** El híbrido queda
  disponible como opción (A/B, consultas con términos literales o códigos) con
  su gate calibrado (§7.3) y la misma abstención que el denso.
- Re-evaluar si el golden set suma preguntas con términos literales del
  contrato o códigos de póliza, o si se cambia la tokenización de BM25.

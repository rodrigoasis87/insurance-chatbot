# A/B de retrieval determinista: denso vs. híbrido con metadata

> **Tipo de métricas**: todas las métricas de ranking y abstención de este
> documento son **(retrieval determinista)**. La latencia es
> **(operacional)**. No hay métricas RAGAS, de juez LLM, de generación ni
> end-to-end.
>
> **Fecha**: 2026-10-23 · **Commit**: `81c4f35` · **Run**:
> `ab_literal_20261023T143923Z` · **Colección**: Qdrant `polizas`, 758 puntos,
> estado `green` · **Embeddings**: `qwen3-embedding:0.6b` (sin LLM de chat).
>
> **Estado**: medición cerrada. La conclusión es **no cambiar producción**;
> ver §6.

## 1. Pregunta y criterio de decisión

¿La búsqueda híbrida (denso + BM25/RRF) mejora sobre la búsqueda densa en
consultas que exigen términos literales del contrato: códigos de póliza,
números de artículo, términos legales raros y frases textuales?

El golden set existente está **parafraseado** (lenguaje del asegurado) y no
contiene ni un código `POL…` ni un número de artículo. Por eso se construyó un
set literal específico y se midió con tres variantes:

| Variante | Índice léxico | Piso denso antes de fusionar | Gate posterior |
|---|---|---|---|
| `dense` | — | — | `UMBRAL_SCORE = 0.60` (coseno) |
| `hybrid_current` | BM25 sobre `page_content` | `0.60` | `UMBRAL_SCORE_HYBRID = 0.40` (RRF) |
| `hybrid_meta` | BM25 sobre `page_content` + `poliza`, `documento`, `articulo`, `artN`, `titulo_canonico` | `0.60` | `0.40` (RRF) |
| `hybrid_current_sin_piso` | BM25 actual | ninguno | `0.40` (RRF) |
| `hybrid_meta_sin_piso` | BM25 con metadata | ninguno | `0.40` (RRF) |

`hybrid_meta` es un **prototipo de evaluación**: no se tocó el índice de
producción ni el esquema de Qdrant. Los dos `sin_piso` son diagnósticos para
separar el efecto del índice del efecto del piso semántico.

Criterio acordado:

1. **Primario**: `hybrid_meta` vs. `dense` en el set literal,
   `recall@5 post-gate` ≥ **+10 pp**, con IC 95 % bootstrap pareado que excluya
   0.
2. **Guardrail golden**: la paráfrasis (`answer_from_policy`) no cae más de
   **2 pp**.
3. **Guardrail abstención**: la abstención en negativos no empeora.
4. **Guardrail latencia**: p95 ≤ **2x** la de `dense`.

## 2. Set literal (60 filas)

Archivo versionado: `data/evaluation/retrieval_literal.jsonl`. Generador
determinista y testeado: `scripts/build_literal_set.py`.

| Tipo | n | Cómo se eligió | Ejemplo |
|---|---:|---|---|
| `rare_term` | 20 | término con `df=1` en los 758 chunks; curado a mano y repartido entre 8 pólizas | `¿Qué dice la póliza sobre «ventriculostomia»?` → `POL320180100` art. 5 |
| `unique_phrase` | 15 | ventana de 8 tokens única en el corpus de artículos y presente en un solo chunk; round-robin, máx. 2 por póliza | `¿Qué establece el contrato sobre «Solamente se indemnizará una de las enfermedades graves…»?` → `POL320160108` art. 3 |
| `cross_policy` | 15 | mismo canónico en ≥2 pólizas; una frase única por caso, un caso por canónico | `¿Qué establece el contrato sobre «Adicionalmente la póliza terminará cuando el asegurado cumpla la edad máxima de permanencia»?` → `POL320130223` art. 5 |
| `code_article` | 10 | código de póliza + artículo ≥10, longitud ≥120 caracteres; una consulta por póliza | `¿Qué establece la póliza POL120190177 en el artículo 10?` → `POL120190177` art. 10 |

Cada fila tiene exactamente un `reference_contexts` con
`(poliza, documento, articulo)`. El set es **adversarialmente literal**: no es
una muestra aleatoria de preguntas de usuarios. Su recall absoluto no debe
compararse con el del golden set.

Las 60 filas cubren las 10 pólizas y 22 canónicos; la distribución por póliza
va de 3 a 8 filas. El detalle completo está en el JSONL y se reproduce con:

```bash
uv run python scripts/build_literal_set.py
```

## 3. Resultados

### 3.1 Set literal, métricas de ranking

`recall@k`, MRR y nDCG@5 son **antes del gate**; `recall@5 post-gate` es el
criterio primario (artículo de referencia entre los 5 hits que pasan el gate
del modo).

| Variante | recall@1 | recall@3 | recall@5 | MRR | nDCG@5 | recall@5 post-gate |
|---|---:|---:|---:|---:|---:|---:|
| `dense` | 0.300 | 0.383 | 0.400 | 0.340 | 0.355 | **0.183** |
| `hybrid_current` | 0.183 | 0.183 | 0.183 | 0.183 | 0.183 | **0.183** |
| `hybrid_meta` | 0.183 | 0.183 | 0.183 | 0.183 | 0.183 | **0.183** |
| `hybrid_current_sin_piso` | 0.417 | 0.683 | 0.783 | 0.562 | 0.618 | **0.783** |
| `hybrid_meta_sin_piso` | 0.417 | 0.733 | 0.900 | 0.594 | 0.670 | **0.900** |

### 3.2 Set literal, por tipo de consulta (`recall@5 post-gate`)

| Tipo | n | `dense` | `hybrid_current` | `hybrid_meta` | `current_sin_piso` | `meta_sin_piso` |
|---|---:|---:|---:|---:|---:|---:|
| `code_article` | 10 | 0.000 | 0.000 | 0.000 | 0.000 | **0.800** |
| `cross_policy` | 15 | 0.533 | 0.533 | 0.533 | 0.933 | **0.933** |
| `rare_term` | 20 | 0.000 | 0.000 | 0.000 | **1.000** | **1.000** |
| `unique_phrase` | 15 | 0.200 | 0.200 | 0.200 | **0.867** | 0.800 |

Lectura directa: el piso denso de `0.60` bloquea **todos** los rescates
léxicos. Sin piso, el índice con metadata recupera 8/10 consultas de código y
mantiene el resto; el índice actual no recupera ninguna de código.

### 3.3 Diagnóstico: candidatos recuperados antes de fusionar

`D` = recall del artículo de referencia en los candidatos densos (20 para
híbridos, 10 para `dense`); `L` = en los candidatos BM25 (20); `U` = unión.
Los `sin_piso` comparten exactamente los mismos candidatos crudos que su
variante con piso: lo único que cambia es el filtro.

| Tipo | `dense` D/L/U | `hybrid_current` D/L/U | `hybrid_meta` D/L/U |
|---|---:|---:|---:|
| `code_article` | 0.000 / 0.000 / 0.000 | 0.000 / 0.000 / 0.000 | 0.000 / **1.000** / **1.000** |
| `cross_policy` | 0.733 / 0.000 / 0.733 | 0.867 / **1.000** / **1.000** | 0.867 / **1.000** / **1.000** |
| `rare_term` | 0.450 / 0.000 / 0.450 | 0.450 / **1.000** / **1.000** | 0.450 / **1.000** / **1.000** |
| `unique_phrase` | 0.467 / 0.000 / 0.467 | 0.667 / **1.000** / **1.000** | 0.667 / **1.000** / **1.000** |

El índice BM25 con metadata sí encuentra el 100 % de los artículos de
referencia en los cuatro tipos, incluidos los 10 códigos/artículos. El problema
no es el índice: es que el piso semántico descarta esos candidatos léxicos
antes de fusionar.

### 3.4 Control golden (paráfrasis, 60 filas `answer_from_policy`)

| Variante | recall@1 | recall@3 | recall@5 | MRR | nDCG@5 | recall@5 post-gate |
|---|---:|---:|---:|---:|---:|---:|
| `dense` | 0.367 | 0.567 | 0.733 | 0.482 | 0.544 | **0.717** |
| `hybrid_current` | 0.383 | 0.617 | 0.717 | 0.517 | 0.567 | **0.717** |
| `hybrid_meta` | 0.417 | 0.650 | 0.733 | 0.541 | 0.589 | **0.733** |
| `hybrid_current_sin_piso` | 0.350 | 0.600 | 0.683 | 0.483 | 0.532 | **0.683** |
| `hybrid_meta_sin_piso` | 0.400 | 0.583 | 0.717 | 0.515 | 0.564 | **0.717** |

El guardrail de paráfrasis se cumple para `hybrid_meta` (+1.7 pp) y para
`hybrid_meta_sin_piso` (0.0 pp). `hybrid_current_sin_piso` cae 3.3 pp en el
punto estimado, por encima del límite de 2 pp, aunque el IC incluye 0.

### 3.5 Abstención en negativos

Negativos = **20** filas `abstain_*` del golden set + **18** consultas OOD de
`scripts/analisis_umbral.py` (12 adyacentes + 6 ajenas). Las 26 consultas
`dominio` de ese script no entran: tienen respuesta en el corpus. La métrica es
la fracción de filas **sin ningún hit post-gate** (más alto = mejor).

| Set | n | `dense` | `hybrid_current` | `hybrid_meta` | `current_sin_piso` | `meta_sin_piso` |
|---|---:|---:|---:|---:|---:|---:|
| golden `abstain_*` | 20 | 0.600 | 0.600 | 0.600 | 0.000 | 0.000 |
| OOD adyacente + ajena | 18 | 0.833 | 0.833 | 0.833 | 0.000 | 0.000 |
| **Total** | **38** | **0.711** | **0.711** | **0.711** | **0.000** | **0.000** |

Sin piso, **todas** las consultas negativas devuelven al menos un hit: la
abstención se derrumba de 0.711 a 0.000. Este es el guardrail que invalida la
variante que sí gana recall.

### 3.6 Comparaciones pareadas

IC 95 % bootstrap pareado (2000 remuestras, seed 42, sobre filas) y McNemar
exacto sobre el acierto binario de `recall@5 post-gate`. Δ en **puntos
porcentuales (pp)**.

**Set literal (n=60):**

| Comparación | Δ recall (pp) | IC 95 % (pp) | Rescates | Regresiones | McNemar p |
|---|---:|---:|---:|---:|---:|
| `dense → hybrid_current` | 0.0 | [0.0, 0.0] | 0 | 0 | 1.0000 |
| `dense → hybrid_meta` | **0.0** | **[0.0, 0.0]** | 0 | 0 | 1.0000 |
| `dense → hybrid_current_sin_piso` | +60.0 | [+48.3, +71.7] | 36 | 0 | 2.9e-11 |
| `dense → hybrid_meta_sin_piso` | **+71.7** | **[+60.0, +83.3]** | 43 | 0 | 2.3e-13 |
| `hybrid_current → hybrid_meta` | 0.0 | [0.0, 0.0] | 0 | 0 | 1.0000 |
| `hybrid_current_sin_piso → hybrid_meta_sin_piso` | **+11.7** | **[+3.3, +21.7]** | 8 | 1 | 0.0391 |

**Control golden de paráfrasis (n=60):**

| Comparación | Δ recall (pp) | IC 95 % (pp) | Rescates | Regresiones | McNemar p |
|---|---:|---:|---:|---:|---:|
| `dense → hybrid_current` | 0.0 | [−5.0, +5.0] | 1 | 1 | 1.0000 |
| `dense → hybrid_meta` | **+1.7** | **[−3.3, +8.3]** | 2 | 1 | 1.0000 |
| `dense → hybrid_current_sin_piso` | −3.3 | [−13.3, +6.7] | 4 | 6 | 0.7539 |
| `dense → hybrid_meta_sin_piso` | 0.0 | [−10.0, +11.7] | 5 | 5 | 1.0000 |
| `hybrid_current_sin_piso → hybrid_meta_sin_piso` | +3.3 | [−6.7, +13.3] | 5 | 3 | 0.7266 |

**Abstención en negativos (n=38):**

| Comparación | A | B | Δ (pp) | IC 95 % (pp) | McNemar p |
|---|---:|---:|---:|---:|---:|
| `dense → hybrid_current` | 0.711 | 0.711 | 0.0 | [0.0, 0.0] | 1.0000 |
| `dense → hybrid_meta` | 0.711 | 0.711 | 0.0 | [0.0, 0.0] | 1.0000 |
| `dense → hybrid_current_sin_piso` | 0.711 | 0.000 | **−71.1** | [−84.2, −57.9] | 1.5e-08 |
| `dense → hybrid_meta_sin_piso` | 0.711 | 0.000 | **−71.1** | [−84.2, −57.9] | 1.5e-08 |

### 3.7 Latencia (operacional, set literal, n=60)

| Variante | media ms | p50 ms | p95 ms | máx ms |
|---|---:|---:|---:|---:|
| `dense` | 372.6 | 373.0 | 504.2 | 605.3 |
| `hybrid_current` | 398.3 | 393.4 | 558.5 | 925.3 |
| `hybrid_meta` | 406.8 | 404.4 | **510.0** | 688.2 |
| `hybrid_current_sin_piso` | 366.5 | 359.8 | 475.2 | 567.2 |
| `hybrid_meta_sin_piso` | 337.0 | 332.2 | 473.8 | 661.8 |

p95 de `hybrid_meta` / p95 de `dense` = **1.01x**; el guardrail de 2x se
cumple. En el control golden el p95 de `hybrid_meta` fue 617 ms vs. 399 ms de
`dense` (1.55x), también por debajo de 2x. La latencia es de una sola corrida
local y varía con la carga de Ollama/Qdrant; no hay control de GPU.

## 4. Lectura

1. **La variante de producción con metadata no mejora el set literal.** El
   criterio primario falla: `hybrid_meta` vs. `dense` da **0.0 pp**, IC
   [0.0, 0.0], McNemar p=1.0. Peor aún, el híbrido con piso baja el recall
   pre-gate de 0.400 a 0.183 porque el piso elimina candidatos que el denso
   habría devuelto en el top-5.
2. **El índice con metadata sí tiene señal.** Recupera el 100 % de los
   artículos de referencia como candidato léxico en los cuatro tipos, incluidos
   los 10 códigos/artículos que el BM25 actual no puede recuperar. Sin piso,
   `hybrid_meta_sin_piso` llega a **0.900** de recall post-gate: **+71.7 pp**
   sobre denso, IC [+60.0, +83.3], 43 rescates y 0 regresiones.
3. **El piso semántico es lo que bloquea la ganancia, y también lo que sostiene
   la abstención.** Al quitar el piso, la abstención en los 38 negativos cae de
   **0.711 a 0.000** (−71.1 pp, IC [−84.2, −57.9]). No es un efecto del índice:
   pasa igual con el BM25 actual. El gate RRF de 0.40 no puede separar ambos
   casos porque un hit léxico primero en una sola lista vale 0.5 tanto para una
   consulta del dominio como para una ajena; subir el gate por encima de 0.5
   elimina justamente los rescates léxicos que producen la ganancia
   (`docs/umbral_score.md` §7.2).
4. **La ganancia específica de metadata, aislada del piso, es +11.7 pp**
   (`current_sin_piso → meta_sin_piso`: IC [+3.3, +21.7], 8 rescates, 1
   regresión, p=0.039). Se concentra en `code_article` (0.000 → 0.800) y no
   daña la paráfrasis (golden: 0.0 pp vs. denso). Es evidencia para un lookup
   metadata **dirigido**, no para activar el híbrido sin piso.
5. **El control de paráfrasis no se degrada** con `hybrid_meta` (+1.7 pp, IC
   [−3.3, +8.3]) y la latencia queda dentro del guardrail. El problema es
   exclusivamente el trade-off recall literal vs. abstención.

## 5. Decisión

**No cambiar producción en esta iteración.**

- `RETRIEVAL_MODE=dense` sigue como default.
- No se agrega metadata al índice BM25 de producción todavía.
- El criterio primario (≥ +10 pp con el piso de producción) **no se cumple**.
- La única variante que lo cumple (`hybrid_meta_sin_piso`) **falla el guardrail
  de abstención** y no es desplegable.

El resultado no es “metadata no sirve”: es “metadata está bloqueada por el
diseño actual de piso + gate”. Para capturarla hace falta una señal de
confianza léxica o un ruteo por tipo de consulta, no simplemente quitar el
piso.

## 6. Próximos pasos recomendados

1. **Router de consultas explícitas** (prioridad alta). Detectar
   `POL\d+` y `artículo \d+` y, solo para esas consultas, usar el lookup
   metadata o relajar el piso denso. Es el caso donde la ganancia es más clara
   (8/10) y el riesgo de falsos positivos es más fácil de acotar. Agregar
   negativos con códigos/artículos inventados (`POL999999`, `artículo 99`) al
   set de abstención antes de medir.
2. **Gate de confianza léxica** (prioridad media). Mantener el piso para
   lenguaje natural y permitir hits solo-léxicos con una señal absoluta
   (score BM25 crudo, cobertura de IDF o proporción de términos raros), no con
   el RRF que es relativo al ranking. Calibrar contra los 38 negativos y
   reportar falsos positivos.
3. **Ampliar el set literal y los negativos** antes de una decisión de
   producto: más consultas de código/artículo, códigos inválidos, artículos
   inexistentes y términos raros de otras pólizas.
4. **No bajar el piso a ciegas.** El piso 0.60 es el que conserva la abstención
   medida; cualquier cambio debe re-medirse con este mismo A/B y con
   `docs/umbral_score.md` §7.

## 7. Reproducibilidad y límites

### 7.1 Comandos

```bash
docker compose up -d qdrant ollama

uv run python scripts/build_literal_set.py
uv run python scripts/ab_retrieval_literal.py

uv run pytest tests/test_retrieval_eval.py tests/test_ab_literal.py
```

El A/B escribe el detalle en
`data/evaluation/results/ab_literal_<timestamp>.json` (gitignored). El set
literal (`data/evaluation/retrieval_literal.jsonl`) y sus scripts sí se
versionan. `scripts/build_literal_set.py` es determinista y
`tests/test_ab_literal.py` verifica que el archivo versionado se reproduce
exactamente.

### 7.2 Archivos de esta medición

| Archivo | Rol |
|---|---|
| `data/evaluation/retrieval_literal.jsonl` | set literal de 60 filas, versionado |
| `scripts/build_literal_set.py` | generador determinista del set |
| `scripts/ab_retrieval_literal.py` | runner del A/B y variante `MetadataBM25Index` |
| `app/rag/retrieval_eval.py` | recall, MRR, nDCG, bootstrap pareado y McNemar puros |
| `tests/test_retrieval_eval.py` | tests de las métricas |
| `tests/test_ab_literal.py` | tests del índice con metadata, fusión y set literal |

### 7.3 Límites

- **n chico y un solo corpus**: 60 literales, 60 golden policy y 38 negativos;
  10 pólizas, 227 artículos, 758 chunks. Los IC son anchos y no hay múltiples
  corpus ni múltiples corridas.
- **Set literal adversarial**: mide el peor caso de términos literales, no la
  distribución real de preguntas. No comparar su recall absoluto con el golden.
- **Solo retrieval**: no mide generación, faithfulness, citas ni satisfacción.
  No se usó RAGAS ni juez LLM, por diseño y por costo.
- **Una corrida de latencia**: sin control de carga, GPU ni repeticiones;
  sirve como orden de magnitud, no como SLA.
- **`hybrid_meta` es eval-only**: no cambia el índice de producción ni Qdrant.
- **Detalle del denso**: para compartir candidatos entre variantes, `dense`
  usa los primeros 10 de la misma lista de 20 candidatos que usan los híbridos;
  el orden de Qdrant es el mismo que pedir top-10. Si hubiera empates exactos
  en el corte, alguna fila podría cambiar.
- **OOD**: son 18 consultas (12 adyacentes + 6 ajenas) de
  `scripts/analisis_umbral.py`; no las 44 totales, porque 26 son de dominio.

# UMBRAL_SCORE: distribución empírica de scores de `search()`

> **Fecha**: 2026-10-07 · **Modelo de embeddings**: `qwen3-embedding:0.6b`
> (1024 dims, cosine) · **Colección**: `polizas` (758 puntos, 14 sub-documentos)
> · **`search()` con colapso por `(poliza, articulo)`** activo (CONTRACTS §2).

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
```
# Arquitectura · MVP y Post-MVP

Documenta **cómo esperamos que quede la arquitectura al cierre del MVP** y **qué
agregaría el post-MVP** (tiempo extra) sin tocar lo ya construido. Es la vista de
sistema completa dibujada con los **dos diagramas más importantes**: el flujo del
MVP y el flujo con las dos extensiones de futuro.

- Contrato de datos y Runtime: `docs/CONTRACTS.md`
- Decisión de alcance y entregables: `docs/narrative.md` (§4 y §5)
- Decisiones de stack: `docs/STACK.md` (ADR-001…ADR-013)
- Issues de referencia entre `#4` y `#22`.

---

## 1. Componentes del MVP (estado esperado al cierre)

| Bloque | Célula | Componente | Issue |
|---|---|---|---|
| Datos | D1 · Captura y limpieza | PDFs (S3) → parser → `articulos.jsonl` (227 art. + metadata) | #4 |
| Datos | D2 · Chunking | chunks 1000/150 que nunca cruzan artículo → `chunks.jsonl` | #7 |
| Motor RAG | R1 · Indexación y retrieval | embeddings `nomic-embed-text` + Qdrant `polizas` (768d) + `search()` | #9 |
| Motor RAG | R2 · Generación con citas / agente | `query()` ≤2 llamadas LLM (`qwen3:4b`) + `web_search` | #17, #8 |
| Exposición | E1 · API y UI | FastAPI delgado + Chainlit con fuentes visibles | #16, #18 |
| Garantías | G1 · QA, eval, ops | pytest con mocks · golden set · compose/README/demo | #20, #19, #21, #22 |

Todos los servicios corren en Docker Compose local (Qdrant 6333, Ollama 11434,
API, UI). Detalle del runtime en `docs/CONTRACTS.md` §4.

---

## 2. Diagrama 1 · Arquitectura del MVP (esperada al cierre)

```
                               DEPENDENCIAS EXTERNAS
                        (ollama   qdrant)        (internet: solo web del agente)
                            │       │                        │
┌───────────────────────────▼───────▼────────────────────────▼─────────────┐
│                        DATOS · D1 + D2            (#4, #7)              │
│                                                                          │
│  S3 ──► data/raw_pdfs ──► Parser ──► articulos.jsonl (227 registros)    │
│          (9 PDFs,         extract_articles ·     con metadata:           │
│           gitignored)     segment_text ·         poliza · ramo · año ·   │
│                           canonical_title)       canonico · pagina ·     │
│                           + limpieza (5 reglas)  chars                    │
│                                             │                            │
│                                             ▼                            │
│                        Chunking (#7): chunk 1000 · overlap 150           │
│                        (un chunk NUNCA cruza de artículo)                │
│                                             │                            │
│                                             ▼                            │
│                                        chunks.jsonl                       │
└─────────────────────────────────────────────┬────────────────────────────┘
                                              │ embeddings nomic-embed-text
                                              │ (Ollama local, 768 dims)
┌─────────────────────────────────────────────▼────────────────────────────┐
│                    MOTOR RAG · R1 + R2            (#9, #17, #8)          │
│                                                                          │
│   Qdrant · colección `polizas` (coseno · 768d)                           │
│     index build idempotente (point_id determinístico)      [R1]          │
│              │                                                        │
│              ▼                                                        │
│   search(question, top_k=5) ──► chunks + score + metadata               │
│              │                                                        │
│              ▼                                                        │
│   UMBRAL_SCORE: filtro hard gate en código      (bajo umbral: jamás      │
│              │                                 entran al prompt)         │
│              ▼                                                        │
│   1.ª llamada LLM · qwen3:4b (local)                                    │
│     respuesta grounded con citas [fuente: PÓLIZA · Art. N]    [R2]      │
│              │                                                        │
│              ├──¿el contexto responde?──────► answer +                  │
│              │                                  sources[] {origen:      │
│              │                                  poliza}                 │
│              │                                                     │
│              └─ no y ¿es del dominio/             │                     │
│                 rubro? (guardrail) ────────► 2.ª llamada con            │
│                     │                          web_search (#8, DDG)      │
│                     │ no ──► "no está en las        │                  │
│                     │        fuentes" + alcance      ▼                  │
│                     │                              answer +             │
│                     │                              sources[] {origen:    │
│                     │                              web, url}             │
│                     │              (máx 1 web · ≤2 llamadas LLM)        │
└─────────────────────┼────────────────────────────────────────────────────┘
                      ▼ answer + sources[]
┌──────────────────────────────────────────────────────────────────────────┐
│                     EXPOSICIÓN · E1                        (#16, #18)    │
│                                                                          │
│   FastAPI:  /chat · /health · /policies                                  │
│      (HTTP delgado: delega en query(), sin lógica RAG)                   │
│        │                                                                │
│        ▼                                                                │
│   Chainlit: chat con fuentes visibles; las de origen web se              │
│     diferencian visualmente de las citas de póliza                       │
└──────────────────────────────────────────────────────────────────────────┘
                          ▲
        ┌─────────────────┴─────────────────┐
        │ GARANTÍAS · G1 (transversal)      │  #19 eval golden: recall@k,
        │ #20 pytest con mocks ·            │  cita_ok, marcación de web
        │ #21/#22 compose + README + video  │
        └───────────────────────────────────┘
```

---

## 3. Diagrama 2 · Arquitectura Post-MVP (con Intención + Recombinación)

Las dos extensiones de futuro (**`NUEVO`**) se insertan **sin tocar** las células
del MVP:

- **Clasificador de intención liviano**: un pequeño modelo (p. ej. encoder
  tiny/distilado y/o clasificador sobre embeddings locales) que decide **antes**
  de recuperar o buscar en la web si la pregunta es `poliza`, `rubro`,
  `recombinar` o `fuera_de_dominio`. Reemplaza la heurística de dominio que hoy
  vive en el prompt de la 1.ª llamada.
- **Recombinación de pólizas**: genera **PDFs recombinados** (póliza nueva
  armada a partir de las cláusulas canónicas), como entregable de *tiempo extra*.

```
                               DEPENDENCIAS EXTERNAS
                        (ollama   qdrant)        (internet: solo web del agente)
                            │       │                        │
┌───────────────────────────▼───────▼────────────────────────▼─────────────┐
│          INTAKE · con clasificación de intención          [NUEVO]        │
│                                                                          │
│   pregunta ──► Clasificador de intención (modelo muy liviano, local)     │
│        │  ├─ intención `poliza`    ──► retrieve (Qdrant)                 │
│        │  ├─ intención `rubro`     ──► web_search (agente)               │
│        │  ├─ intención `recombinar` ─► Recombinación de pólizas           │
│        │  └─ `fuera_de_dominio`     ─► negativa + alcance (guardrail)     │
└────────┼─────────────────────────────────────────────────────────────────┘
         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      DATOS · D1 + D2  (igual que MVP)                     │
│  S3 ──► parser/limpieza ──► articulos.jsonl ──► chunking ──► chunks.jsonl │
└────────┬───────────────────────────────────────────┬──────────────────────┘
         │                                               │ (artículos)
         ▼                                               ▼
┌──────────────────────────────────────────────┐  ┌─────────────────────────┐
│             MOTOR RAG · R1 + R2              │  │ RECOMBINACIÓN · D3 + E2  │
│  Qdrant ──► UMBRAL_SCORE ──► 1.ª LLM grounded│  │  [NUEVO]                 │
│     └─ insuficiente ──► web_search            │  │ selector de cláusulas   │
│           (origen: web)                      │  │   (36 canónicas) por     │
│  answer + sources {origen: poliza|web}        │  │   cobertura/opciones    │
│  ≤2 llamadas LLM · máx 1 web                  │  │ ensambla estructura     │
└────────┬──────────────────────────────────────┘  │   (matriz esqueleto)    │
         │                                          │ generador PDF (póliza  │
         ▼                                          │   personalizada)       │
┌──────────────────────────────────────────────┐  │   /policy-recombine     │
│                EXPOSICIÓN · E1 + E2          │  │   preview + descarga    │
│  FastAPI (delgado) · Chainlit (fuentes)      │ ─►│                        │
│  + endpoint y vista de PDF recombinado  [NUEVO]│ └─────────────────────────┘
└────────┬──────────────────────────────────────┘
         ▼ answer + sources[]  (+ opcional: PDF recombinado)
┌──────────────────────────────────────────────────────────────────────────┐
│ GARANTÍAS · G1 (igual que MVP) + eval del clasificador y del PDF          │
│   [NUEVO] precisión de intención · validez de cláusulas/PUBLISH del PDF   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Diferencia · MVP terminado vs Post-MVP

| Aspecto | MVP (Diagrama 1) | Post-MVP (Diagrama 2) |
|---|---|---|
| Cómo decide la ruta | Regla fija: retrieve → `UMBRAL_SCORE` → heurística de dominio en el prompt | **Clasificador de intención liviano** antes de recuperar/buscar |
| Tipos de intención | Implícito (póliza / rubro vía web / fuera) | Explícito: `poliza` · `rubro` · `recombinar` · `fuera_de_dominio` |
| Salidas | Solo respuestas con citas (`origen: poliza` o `web`) | + **PDF recombinado** (póliza personalizada) |
| Componentes nuevos | — | Clasificador de intención · Recombinación D3/E2 |
| Datos extra | — | Reuso de `articulos.jsonl` (36 cláusulas canónicas) para ensamblar PDFs |
| API/UI | `/chat`, `/health`, `/policies` | + `/policy-recombine` y vista de previsualización/descarga |
| Eval | `recall@k`, `cita_ok`, marcación web | + precisión del clasificador + validez de la póliza recombinada |
| Riesgo principal | Alucinación / cita incorrecta | PDFs inválidos o cláusulas contradichas |

**Regla de diseño:** el post-MVP **agrega capas, no modifica** las del MVP. El
MVP queda con `UMBRAL_SCORE` + guardrail de dominio como mecanismo robusto y
determinístico; si hay tiempo extra, el clasificador y la recombinación se
superponen sin reescribir `query()` ni la API.

---

## 5. Referencias

- `docs/CONTRACTS.md` — contratos de datos, runtime y agente (`query()` ≤2 llamadas).
- `docs/narrative.md` §4/§5 — células del MVP y roadmap M1/M2/M3.
- `docs/STACK.md` ADR-001/ADR-005 — agente + web en el MVP.
- Issues: #4, #7 (Datos) · #9, #8, #17 (Motor) · #16, #18 (Exposición) ·
  #19, #20, #21, #22 (Garantías).
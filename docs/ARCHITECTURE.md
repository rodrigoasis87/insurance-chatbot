# Arquitectura · MVP y Post-MVP

Documenta **cómo esperamos que quede la arquitectura al cierre del MVP** y **qué
agregaría el post-MVP** (tiempo extra) sin tocar lo ya construido. Es la vista de
sistema completa dibujada con los **dos diagramas más importantes**: el flujo del
MVP y el flujo con las dos extensiones de futuro.

- Contrato de datos y Runtime: `docs/CONTRACTS.md`
- Decisión de alcance y entregables: `docs/narrative.md` (§2, §6 y §7)
- Enunciado oficial y su traducción a alcance: `docs/enunciado.md`
- Decisiones de stack y arquitectura: `docs/STACK.md` (ADR-001) y
  `docs/adr/` (ADR-002…ADR-005).
- Issues de referencia entre `#4` y `#22` más las de cada célula (Generación R3: #36).

---

## 1. Componentes del MVP (estado esperado al cierre)

| Bloque | Célula | Componente | Issue | Estado |
|---|---|---|---|---|
| Datos | D1 · Captura y limpieza | PDFs (S3) → parser → `articulos.jsonl` (227 art. + metadata) | #4 | ✅ hecho |
| Datos | D2 · Chunking | chunks 1000/150 que nunca cruzan artículo → `chunks.jsonl` | #7 | ✅ hecho |
| Motor RAG | R1 · Indexación y retrieval | embeddings `qwen3-embedding:0.6b` + Qdrant `polizas` (1024d) + `search()` con colapso por `(poliza, articulo)` | #9 | ✅ hecho |
| Motor RAG | R2 · Generación con citas / agente | `query()` ≤2 llamadas LLM (`qwen3:4b-instruct`) + `web_search` | #17, #8 | ⚠ pendiente |
| Generación | R3 · Recombinación DEM (**demo v0**) | `app/generation/` → `/policy-recombine` → **PDF borrador DEM** (bloques canónicos + perfil sin PII; sin emisión) | #36 | ⚠ pendiente |
| Exposición | E1 · API y UI | FastAPI delgado + Chainlit con fuentes visibles | #16, #18 | ⚠ pendiente |
| Garantías | G1 · QA, eval, ops | pytest con mocks · golden set · compose/README/demo | #20, #19, #21, #22 | ⚠ parcial |

Hoy corren en Docker Compose local **Qdrant (6333) y Ollama (11434)**; la API y
la UI se agregan en #21. Detalle del runtime en `docs/CONTRACTS.md` §4.

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
│           gitignored)     segment_text ·         poliza · documento ·    │
│                           canonical_title)       ramo · año · familia ·  │
│                           + limpieza (5 reglas)  articulo · canonico ·   │
│                                                   pagina · chars          │
│                                             │                            │
│                                             ▼                            │
│                        Chunking (#7): chunk 1000 · overlap 150           │
│                        (un chunk NUNCA cruza de artículo)                │
│                                             │                            │
│                                             ▼                            │
│                                        chunks.jsonl                       │
└─────────────────────────────────────────────┬────────────────────────────┘
                                              │ embeddings qwen3-embedding:0.6b
                                              │ (Ollama local, 1024 dims)
┌─────────────────────────────────────────────▼────────────────────────────┐
│                    MOTOR RAG · R1 + R2            (#9, #17, #8)          │
│                                                                          │
│   Qdrant · colección `polizas` (coseno · 1024d)                          │
│     index build idempotente (point_id determinístico)      [R1]          │
│              │                                                           │
│              ▼                                                           │
│   search(question, top_k=5) ──► chunks + score + metadata                │
│               (colapso interno: 1 hit por (poliza, articulo),            │
│                el de mayor score)                                        │
│              │                                                           │
│              ▼                                                           │
│   UMBRAL_SCORE: filtro hard gate en código      (bajo umbral: jamás      │
│              │                                 entran al prompt)         │
│              ▼                                                           │
│   1.ª llamada LLM · qwen3:4b-instruct (local)                            │
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
│                        GENERACIÓN · R3 (demo v0)        (#36)            │
│                                                                          │
│   app/generation/dem.py · recombinar(bloques canónicos + perfil)         │
│     ──► borrador DEM (código de la corredora, NO POL)                    │
│     ──► PDF marcado "BORRADOR · no emitida"                              │
│   POST /policy-recombine (demo CLI hasta #16; sin emisión, sin PII)      │
│   ⚠ la aseguradora puede adoptar el DEM → si decide, lo deposita como POL │
└───────────────────────────────┬──────────────────────────────────────────┘
                      ▼ answer + sources[] (+ PDF DEM descargable)
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

## 3. Diagrama 2 · Arquitectura Post-MVP (con Intención + Recombinación completa)

Las extensiones de futuro (**`NUEVO`**) se insertan **sin tocar** las células
del MVP. La **Recombinación DEM ya existe como demo v0** en el MVP (R3 · #36:
ensambla bloques canónicos + perfil → borrador sin emisión); el post-MVP la
**completa** (preview robusto, declaración formal, emisión) y agrega el
clasificador de intención:

- **Clasificador de intención liviano**: un pequeño modelo (p. ej. encoder
  tiny/distilado y/o clasificador sobre embeddings locales) que decide **antes**
  de recuperar o buscar en la web si la pregunta es `poliza`, `rubro`,
  `recombinar` o `fuera_de_dominio`. Reemplaza la heurística de dominio que hoy
  vive en el prompt de la 1.ª llamada.
- **Recombinación completa (post-MVP, sobre R3)**: genera **PDFs recombinados**
  de grado productivo (póliza nueva armada de las cláusulas canónicas, revisada
  por suscriptor) y soporta el flujo **DEM → POL** (la aseguradora la adopta y
  la deposita en la CMF).

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
│        │  ├─ intención `recombinar` ─► Recombinación (R3 → completa)       │
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
│             MOTOR RAG · R1 + R2              │  │ RECOMBINACIÓN COMPLETA  │
│  Qdrant ──► UMBRAL_SCORE ──► 1.ª LLM grounded│  │  (post-MVP, eleva R3)   │
│     └─ insuficiente ──► web_search            │  │ selector de cláusulas   │
│           (origen: web)                      │  │   (36 canónicas) por     │
│  answer + sources {origen: poliza|web}       │  │   cobertura/opciones    │
│  ≤2 llamadas LLM · máx 1 web                  │  │ ensambla estructura     │
└────────┬──────────────────────────────────────┘  │   (matriz esqueleto)    │
         │                                          │ generador PDF de grado │
         ▼                                          │   productivo + DEM→POL │
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
| Salidas | Respuestas con citas (`origen: poliza` o `web`) + **borrador DEM (R3 · demo v0)** | + **PDF recombinado de grado productivo** (flujo DEM → POL) |
| Componentes nuevos | — (Demo v0 de generación: R3 · #36) | Clasificador de intención · Recombinación completa (eleva R3) |
| Datos extra | Reuso de `articulos.jsonl` (36 cláusulas canónicas) para el borrador DEM | + validación legal/preview de grado productivo |
| API/UI | `/chat`, `/health`, `/policies` + `/policy-recombine` (demo v0) | + `/policy-recombine` productivo con preview/descarga y emisión |
| Eval | `recall@k`, `cita_ok`, marcación web + validez del borrador DEM | + precisión del clasificador + validez de la póliza recombinada |
| Riesgo principal | Alucinación / cita incorrecta / DEM no representativo | PDFs inválidos o cláusulas contradichas |

**Regla de diseño:** el post-MVP **agrega capas, no modifica** las del MVP. El
MVP queda con `UMBRAL_SCORE` + guardrail de dominio como mecanismo robusto y
determinístico, y una **demo v0 de recombinación (DEM)** como prueba del
"generate new policies" del enunciado; si hay tiempo extra, el clasificador y la
recombinación completa se superponen sin reescribir `query()` ni la API.

---

## 5. Notas de proveniencia y semántica de códigos

### 5.1 Proveniencia del formato `POL{ramo}0{YY}{seq}` y del mapeo de ramo

- El patrón `POL{ramo}0{YYYY}{seq}` (posiciones `3-4` = ramo, `5` = `0` fijo,
  `6-8` = año, `8-12` = secuencia, p. ej. `POL320130223`) es el formato de los
  **códigos de depósito** de la muestra y se validó contra un código real del
  Depósito de Pólizas (`POL 320230367`).
- El mapeo `ramo 32 → salud`, `resto → accidentes` es una **heurística propia**:
  fue **inferida de los títulos del dataset** (implementada en
  `app/data/eda.py:45-51`), **no una tabla oficial del regulador**.
- Límites de esta interpretación: aplica solo a **códigos de depósito de
  condiciones generales** (correlativos por ramo/año, máximo 9.999); **no
  aplica a pólizas emitidas** (millones de contratos) y **no codifica
  familia/producto** ni aseguradora.
- Consecuencia: no debe presentarse como fuente normativa; sirve para ordenar y
  auditar el pipeline del prototipo.

### 5.2 Semántica `POL` vs `DEM`

| Código | Qué significa | Quién lo emite | Estado |
|---|---|---|---|
| `POL…` | Póliza de condiciones generales **depositada** ante el regulador (Depósito de Pólizas, CMF) | La **aseguradora** | Vigente/regulada |
| `DEM…` | **Borrador/estándar propio de la corredora** (recombinación de casos del mercado) | La **corredora** (con el agente) | Borrador, no emitida |

El artefacto `DEM` **no es una póliza**: es una propuesta de estándar que la
corredora puede ofrecer a una aseguradora; si la aseguradora la adopta, la
deposita como `POL` y recién ahí adquiere estatus regulatorio. El PDF del DEM
lleva la marca `BORRADOR · no emitida` y citas de los moldes base que lo
sustentan.

---

## 6. Referencias

- `docs/CONTRACTS.md` — contratos de datos, runtime y agente (`query()` ≤2 llamadas).
- `docs/umbral_score.md` — `UMBRAL_SCORE` empírico (0.60): metodología y distribuciones (ADR-004).
- `docs/narrative.md` §2/§6/§7 — mapa de actores, células del MVP y roadmap.
- `docs/enunciado.md` — requisitos de la consigna ("Insurance Policy Generation Chatbot").
- ADRs: `docs/STACK.md` (ADR-001, stack) y `docs/adr/` — ADR-002 (identidad del
  documento) · ADR-003 (chunking) · ADR-004 (colapso + `UMBRAL_SCORE`) · ADR-005
  (agente + web en el MVP).
- Issues: #4, #7 (Datos) · #9, #8, #17 (Motor) · #36 (Generación) ·
  #16, #18 (Exposición) · #19, #20, #21, #22 (Garantías).
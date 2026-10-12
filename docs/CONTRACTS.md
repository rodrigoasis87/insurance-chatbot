# Contratos de datos y API

Especificaciones vinculantes entre etapas del pipeline. Este documento es la
**única fuente de verdad** de los formatos que cruzan los milestones; los
bodies de las issues lo referencian por sección. Cualquier cambio se hace por
PR a este archivo y deriva en ajuste de las issues dependientes.

Flujo: `M1 --(#4 articulos.jsonl, #7 chunks.jsonl)--> M2 --(#9 Qdrant, #17 query)--> M3 --(#16 API, #18 UI)-->`

---

## 1. Contrato de datos M1 → M2

### 1.1 `data/processed/articulos.jsonl` — salida de #4

Una línea JSON por artículo. Exactamente **227 registros** en el corpus actual.

```json
{
  "poliza": "POL320130223",
  "documento": 1,
  "ramo": "salud",
  "año": "2013",
  "familia": "colectivo_complementario",
  "articulo": 2,
  "titulo": "COBERTURA",
  "canonico": "cobertura",
  "pagina": 1,
  "chars": 17403,
  "texto": "…cuerpo del artículo limpio, SIN la cabecera…"
}
```

Reglas:

- **La clave única es `(poliza, documento, articulo)`.** Es la que consume el
  `point_id` de `app/rag/indexer.py`, así que **tiene** que ser única.
- `poliza` es el **código de depósito real** del sub-documento, **no** el nombre
  del PDF. `documento` es el ordinal del sub-documento dentro del PDF (1..n).
  Los PDFs del Depósito traen **varias pólizas pegadas** y la numeración de
  artículos **reinicia en 1** en cada una, así que `(poliza, articulo)` a secas
  **NO es clave** (daba 37 colisiones sobre 227). Ver "Sub-documentos" abajo.
- `ramo = "salud" si código[3:5]=="32" else "accidentes"`. `año = "20"+código[6:8]`.
  Se decodifican **una única vez acá**; aguas abajo (#7 en adelante) se
  **propagan**, nunca se re-decodifican.
- `familia` se deriva del **título de portada del sub-documento** (no del nombre
  del archivo, no del cuerpo: el cuerpo nombra "accidente" en artículos de
  cualquier póliza). 8 familias en el corpus, 0 fallback `otra`. Tabla completa
  en `docs/ONTOLOGIA.md` §4.2.
- **Nota de proveniencia (códigos):** el patrón `POL{ramo}0{YY}{seq}` y el mapeo
  de ramo son una **heurística propia inferida de los títulos del dataset**
  (`app/data/parser.py:poliza_ramo`), validada contra un código real del Depósito de
  Pólizas (`POL 320230367`) pero **no es una tabla oficial del regulador**; aplica
  solo a códigos de depósito (no a pólizas emitidas). Ver `docs/ARCHITECTURE.md` §5.1.
- Tipos: `articulo`, `pagina` y `documento` son `int` (página 1-based del PDF); el
  resto `str`.
- `chars` = `len(texto)` sobre el **texto limpio** (no tiene por qué coincidir
  con la columna `chars` de la matriz EDA, que se calculó pre-limpieza).
- `texto` no conserva la cabecera `ARTÍCULO N: …` (pasa a `titulo`/`canonico`),
  aunque el PDF la traiga en la misma línea que el cuerpo.

#### Sub-documentos: por qué existe `documento`

Un PDF del Depósito puede traer más de un documento de depósito pegado, y cada
uno reinicia su numeración de artículos:

| PDF | Códigos de depósito reales dentro | Sub-docs |
|---|---|---|
| `POL320190074.pdf` (72p) | `POL320190074` (pág 1–15) + `POL320130223` (pág 16–72) | 2 |
| `POL320200071.pdf` (25p) | `POL320200071` (pág 1–16) + `POL320160108` (pág 17–25) | 2 |
| los otros 7 | uno solo, igual al nombre del archivo | 1 |

Son **9 archivos pero 10 códigos de depósito reales**: `POL320160108`
("SEGURO INDIVIDUAL DE ENFERMEDADES GRAVES") no existe como archivo propio.

Un sub-documento arranca cuando ocurre cualquiera de estas dos señales:

1. Una **marca de depósito** (`Incorporada al Depósito de Pólizas bajo el código
   POL…`) con código distinto → el artículo pasa al sub-documento real que abre.
2. Un **reinicio de numeración** (el número de artículo no crece respecto del
   anterior) → las cláusulas adicionales del Depósito también reinician en 1 sin
   traer código propio (p. ej. `POL320190074.pdf` pág 11, "EXONERACIÓN DE PAGO
   DE PRIMAS POR FALLECIMIENTO…"). El sub-documento implícito **hereda** el
   código del anterior y sigue vigente hasta que se cruce otra marca.

`documento` se renumera 1..n en orden de aparición dentro de cada PDF.

#### Limpieza aplicada (`clean_article_text`)

Los 5 casos de `app/data/parser.py` están implementados porque se **observaron**
en el corpus, no por checklist. Cada uno tiene asserts en `scripts/test_parser.py`:

1. `\r\n`/`\r` → `\n`.
2. No imprimibles → **espacio**, nunca borrado (borrarlos pegaría palabras de
   páginas distintas; el salto de página de PyMuPDF es `\x0c`). Solo aparecen en
   `POL320200214` art. 20 (domicilio), cuyo PDF además trae una tabla de basura
   binaria: el texto legible sobrevive (436 chars), la basura no se puede
   recuperar y queda como ruido del PDF de origen.
3. Cabecera `ARTÍCULO N: …` fuera del cuerpo.
4. Colapsado de espacios múltiples, tabs y líneas en blanco (se preserva una
   línea en blanco entre párrafos: hay artículos con 812/968 líneas vacías).
5. **Guiones colgantes de fin de línea** → se quita el guion y se conserva el
   salto. Solo aplica a guiones sueltos al final de la línea con blanco antes
   (20 casos, todos en `POL320200071`), y **ninguno parte una palabra**, así que
   no hay hyphenación real que unir. Compuestos reales (`temporo-mandibulares`,
   `dermo-cosméticos`, `pre-autorización`, `COVID-19`, `auto-provocadas`) van en
   medio de la línea y quedan intactos.
6. **Dedup de stopwords** (`de de` → `de`). Solo stopwords y solo la misma
   palabra repetida, para no tocar repeticiones legítimas ("diez diez"). El borde
   "deducible" no se parte.

Lo que **no** se hace, a propósito: no se repara el texto basura del PDF, no se
unes palabras partidas y no se corrigen tildes (el pipeline de embeddings es el
que las normaliza, y el `texto` se conserva fiel al documento).
- `texto` = cuerpo del artículo luego de los 5 casos de limpieza, **sin** la
  línea de cabecera (esa va a `titulo`/`canonico`).
- Validación (en #4): 227 líneas; `(poliza, articulo, canonico)` consistente con
  `docs/eda/polizas_estructura.csv`.
- Persistido en `data/processed/` (gitignored), dentro de `PROCESSED_DIR`.

### 1.2 `data/processed/chunks.jsonl` — salida de #7

Una línea JSON por chunk, en formato `Document` de LangChain:

```json
{
  "page_content": "…fragmento del artículo…",
  "metadata": {
    "poliza": "POL320130223",
    "documento": 1,
    "ramo": "salud",
    "año": "2013",
    "familia": "colectivo_complementario",
    "articulo": 2,
    "titulo_canonico": "cobertura",
    "pagina": 1,
    "chunk_index": 0
  }
}
```

Reglas:

- El splitter **se aplica por artículo** (fuente: `articulos.jsonl`): un chunk
  **nunca cruza de artículo**.
- `chunk_index` = índice 0-based **dentro de cada `(poliza, documento, articulo)`**.
- Metadata **propagada** desde `articulos.jsonl` mapeando `canonico` →
  `titulo_canonico`. `ramo`/`año`/`familia`/`documento` no se re-derivan.
- `documento` **viaja al chunk**: es parte de la clave única del chunk (ver 1.1).
- Defaults MVP (justificados en el PR de #7; revisables en el benchmark
  post-MVP): `RecursiveCharacterTextSplitter`, separadores
  `["\n\n", "\n", ".", " ", ""]`, **`chunk_size=1000`**, **`chunk_overlap=150`**.
- `chars` no viaja en el chunk (recomponible desde fuente si hace falta).

---

## 2. Contrato de retorno de #9 (retrieval en Qdrant)

```python
# app/rag/vectordb.py
def search(query: str, top_k: int = 5) -> list[dict]:
    ...
    # cada dict: {"page_content": str,
    #             "metadata": {"poliza": str, "documento": int, "ramo": str,
    #                          "año": str, "familia": str, "articulo": int,
    #                          "titulo_canonico": str, "pagina": int,
    #                          "chunk_index": int},
    #             "score": float}
```

- Colección `polizas` · vectores **1024 dims** (`qwen3-embedding:0.6b`) ·
  distancia **Cosine**.
- Payload por punto: la metadata del contrato 1.2 + `page_content` (para
  armar contexto/trazabilidad sin re-consultas).
- `point_id` determinístico `uuid5(POLIZA|documento|articulo|chunk_index)` → el
  index build es **idempotente** (re-correr no duplica) y **sin colisiones**:
  `(poliza, articulo)` a secas colisionaba 37 veces sobre 227 artículos porque
  los PDFs traen varias pólizas pegadas con la numeración reiniciada (ver 1.1),
  y Qdrant haría upsert sobre IDs repetidos perdiendo artículos en silencio.
- Los metadatos **viajan con el chunk** siempre (lo verifica #20).
- **Colapso por artículo**: `search()` pide el doble de candidatos y conserva
  **un solo hit por `(poliza, articulo)`** (el de mayor score). Motivo: la
  copia embebida de `POL320130223` (mismo artículo en `documento` 1 y 3 dentro
  de `POL320190074.pdf`, ver 1.1) y los artículos largos partidos en varios
  chunks harían que el mismo artículo ocupe dos lugares del top_k y otro
  artículo quede afuera. Artículos de pólizas distintas **nunca** se colapsan,
  aunque compartan número: la cita (póliza + página) es distinta. Aplica
  `app/rag/vectordb.py::colapsar_por_articulo`.

---

## 3. Contrato de #17 → M3 (query del agente con citas)

`query()` es un **agente acotado a ≤2 llamadas LLM por consulta**.

```python
# app/rag/rag.py
def query(question: str, top_k: int = 5) -> dict:
    ...
    # {"answer": str,
    #  "sources": [{"origen": "poliza", "poliza": str, "articulo": int, "pagina": int}
    #             | {"origen": "web", "url": str, "titulo": str}, ...]}
```

Flujo:

1. `embed(question)` → `search(top_k=5)` (sección 2) → chunks + `score`.
2. **Filtro hard gate** `UMBRAL_SCORE` (en CÓDIGO, no en el LLM): los chunks con
   `score < UMBRAL_SCORE` **no entran al contexto**. Parámetro en `app/rag`,
   calibrado con el golden set de #19 (default inicial documentado en el PR de #17).
3. **1.ª llamada LLM**: responde *grounded* con las citas internas del contexto.
   La instrucción exige no citar ni inventar nada que no esté en el contexto.
   Si el contexto alcanza → fin (1 llamada).
4. Si la 1.ª llama juzga que el contexto **no responde** y la pregunta es del
   **dominio** (pólizas o información relacionada del rubro) → **2.ª llamada**:
   usa `web_search` (#8, `app/rag/web_search.py`) con `max_results=5`, y responde
   citando la fuente con `origen: "web"` + `url`, **siempre marcada y nunca
   igualada a cita de póliza**.
5. Si no hay contexto y no corresponde web (o la pregunta es **fuera de
   dominio**): ninguna llamada responde contenido — mensaje de "no está en las
   fuentes" que reitera el alcance del asistente.

Reglas:

- Citas inline: interna `[fuente: POL320130223 · Art. 2]` coherente con
  `sources`; externa `[fuente web: <dominio>]` con su URL en `sources`.
- El LLM **solo cita** lo presente en el contexto invocado (chunks de la sección
  2 o resultados de `web_search`). Nunca inventa.
- `sources` ordenadas: internas primero (score desc.), luego web. Sin duplicados.
- `UMBRAL_SCORE` es hard gate: un chunk bajo umbral **jamás llega al prompt**
  (decisión de alcance). Con 0 chunks sobrevivientes → sin contexto.
- El agente ejecuta a lo sumo **1 llamada a `web_search`** por consulta
  (≤2 generaciones LLM en total).
- `#19` valida con el golden set: `recall@k`, `cita_ok` (internas) y marcación
  correcta de fuentes web.

---

## 4. Contrato API → UI (#16 → #18)

```json
POST /chat     {"question": "¿…?"}
  → {"answer": "…",
     "sources": [{"origen": "poliza", "poliza": "POL320130223", "articulo": 2, "pagina": 1},
                 {"origen": "web", "url": "https://...", "titulo": "..."}]}

GET  /health   → {"qdrant": "ok", "ollama": "ok"}

GET  /policies → [{"poliza": "POL320130223", "ramo": "salud", "año": "2013"}]
```

Reglas:

- `#16` es **HTTP delgado**: no tiene lógica RAG propia; delega en `query()`
  de `#17`.
- `#18` consume **`#16`** (no `#17` directo); muestra `poliza`/`articulo`/`pagina`
  como fuentes, diferenciando visualmente las de `origen: "web"`.
- `GET /policies` puede derivar la lista de `data/raw_pdfs/` o de los índices;
  la fuente concreta la define `#16`.

---

## 4.1 Contrato de Generación · Recombinación DEM (R3 · #36, demo v0)

Demo v0: ensambla **bloques de cláusulas canónicas** de un molde base del
catálogo + **perfil sin PII** (opciones curadas) → **borrador DEM** (PDF + JSON).
Corre hoy como **CLI** (`uv run python -m app.generation.dem`); el endpoint se
cablea en `#16` con este contrato.

```json
POST /policy-recombine
  {"molde": "POL320200071",
   "perfil": {"edad": "30-40", "preexistencias": "no", "deportes_riesgo": "no",
              "fonasa_isapre": "isapre", "embarazo": "no", "cronicas": "no",
              "colectivo": "no", "residencia": "chile"}}
  → 200
  {"codigo": "DEM260001",
   "molde_base": "POL320200071",
   "creado_en": "2026-10-02T...",
   "perfil": { ... mismos valores curados ... },
   "secciones": [
     {"nombre": "cobertura", "titulo": "COBERTURA", "pagina": 1,
      "perfil": "base", "texto": "…bloque canónico del molde…"},
     {"nombre": "exclusiones", "titulo": "EXCLUSIONES", "pagina": 3,
      "perfil": "preexistencias", "texto": "…"}],
   "pdf_url": "/generated/DEM260001.pdf",
   "aviso": "BORRADOR · no emitida · estándar de la corredora (código DEM); la aseguradora puede adoptarlo y depositarlo como POL."}
```

Reglas:

- El DEM es **borrador**: marcado en el PDF y en el payload (`aviso`); **nunca**
  una póliza emitida ni un código `POL`.
- El **perfil se compone solo de opciones curadas** (bandas/sí-no/listas fijas),
  **no persiste** (contexto de la llamada) y alimenta únicamente la **selección
  de bloques** del molde.
- Cada sección conserva su **cita de origen** del molde (`nombre`, `pagina`).
- El código `DEM` es correlativo de la corredora: `DEM{YYYY}{seq:04d}`.

---

## 5. Mantenimiento

- Este archivo se versiona como cualquier fuente; los bodies de las issues
  **productoras** (#4, #7, #9, #17) enlazan la sección correspondiente.
- Un cambio de contrato (ej. renombrar campo, tipo, default) exige: PR a este
  doc + actualizar las issues que lo producen y las que lo consumen.

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
  "ramo": "salud",
  "año": "2013",
  "articulo": 2,
  "titulo": "COBERTURA",
  "canonico": "cobertura",
  "pagina": 1,
  "chars": 17403,
  "texto": "…cuerpo del artículo limpio, SIN la cabecera…"
}
```

Reglas:

- `ramo = "salud" si código[3:5]=="32" else "accidentes"`. `año = "20"+código[6:8]`.
  Se decodifican **una única vez acá**; aguas abajo (#7 en adelante) se
  **propagan**, nunca se re-decodifican.
- Tipos: `articulo` y `pagina` son `int` (página 1-based del PDF); el resto `str`.
- `chars` = `len(texto)` sobre el **texto limpio** (no tiene por qué coincidir
  con la columna `chars` de la matriz EDA, que se calculó pre-limpieza).
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
    "ramo": "salud",
    "año": "2013",
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
- `chunk_index` = índice 0-based **dentro de cada `(poliza, articulo)`**.
- Metadata **propagada** desde `articulos.jsonl` mapeando `canonico` →
  `titulo_canonico`. `ramo`/`año` no se re-decodifican.
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
    #             "metadata": {"poliza": str, "ramo": str, "año": str,
    #                          "articulo": int, "titulo_canonico": str,
    #                          "pagina": int, "chunk_index": int},
    #             "score": float}
```

- Colección `polizas` · vectores **768 dims** (`nomic-embed-text`) ·
  distancia **Cosine**.
- Payload por punto: la metadata del contrato 1.2 + `page_content` (para
  armar contexto/trazabilidad sin re-consultas).
- `point_id` determinístico `uuid5(POLIZA|articulo|chunk_index)` → el index
  build es **idempotente** (re-correr no duplica).
- Los metadatos **viajan con el chunk** siempre (lo verifica #20).

---

## 3. Contrato de #17 → M3 (query con citas)

```python
# app/rag/rag.py
def query(question: str, top_k: int = 5) -> dict:
    ...
    # {"answer": str,
    #  "sources": [{"poliza": str, "articulo": int, "pagina": int}, ...]}
```

Reglas:

- `answer` formateada con **citas inline** `[fuente: POL320130223 · Art. 2]`
  coherentes con `sources`.
- El LLM **solo puede citar** póliza/artículo presentes en el contexto
  recuperado (nunca inventar). `#17` mapea chunk → artículo usando
  `articulos.jsonl` cuando necesite normalizar.
- `sources` ordenadas por score descendente del retrieval, sin duplicados.

---

## 4. Contrato API → UI (#16 → #18)

```json
POST /chat     {"question": "¿…?"}
  → {"answer": "…", "sources": [{"poliza": "POL320130223", "articulo": 2, "pagina": 1}]}

GET  /health   → {"qdrant": "ok", "ollama": "ok"}

GET  /policies → [{"poliza": "POL320130223", "ramo": "salud", "año": "2013"}]
```

Reglas:

- `#16` es **HTTP delgado**: no tiene lógica RAG propia; delega en `query()`
  de `#17`.
- `#18` consume **`#16`** (no `#17` directo); muestra `poliza`/`articulo`/`pagina`
  como fuentes.
- `GET /policies` puede derivar la lista de `data/raw_pdfs/` o de los índices;
  la fuente concreta la define `#16`.

---

## 5. Mantenimiento

- Este archivo se versiona como cualquier fuente; los bodies de las issues
  **productoras** (#4, #7, #9, #17) enlazan la sección correspondiente.
- Un cambio de contrato (ej. renombrar campo, tipo, default) exige: PR a este
  doc + actualizar las issues que lo producen y las que lo consumen.
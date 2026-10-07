# Narrativa del prototipo

Orden de la historia para la presentación y referencia del diseño. Tres bloques
mandatorios (Contexto / Dataset / Solución) exactamente como pide la consigna del
prototipo; dentro de Solución viven las **células**.

- Enunciado de referencia y su traducción a alcance: `docs/enunciado.md`
- Arquitectura y post-MVP: `docs/ARCHITECTURE.md`
- Contratos de datos y API: `docs/CONTRACTS.md`
- Ontología / taxonomía del dominio: `docs/ONTOLOGIA.md`

---

## 0. La regla de negocio (ancla de todo)

> Ante una pregunta del usuario **sobre pólizas de seguros de salud**, la
> aplicación debe **devolver el fragmento fiel de la póliza** que responde la
> pregunta, **con su cita** (`póliza · Art. N`), sin inventar nada. Si la respuesta
> exige información relacionada que no está en las pólizas (mercado, normativa),
> el **agente** la complementa con búsqueda web, siempre con la fuente marcada
> como externa.

**Incluye el modo "suscripción documental"**: el asistente sustenta la etapa de
suscripción/evaluación de riesgos informando **lo que el texto del contrato
exige/condiciona** para un perfil (admisión, carencia, exclusiones, garantías);
**no decide, no tarifica y no pide datos personales** — la decisión y la prima
quedan en el humano y en los sistemas del emisor.

De ahí se derivan todos los criterios: parsear/limpiar bien (fidelidad del
fragmento), recuperar bien (completitud), citar bien (trazabilidad), y acotar el
dominio de lo que contestamos (control).

---

## 1. Contexto y problema

- Las pólizas de seguros de salud chilenas son **documentos legales densos en
  PDF** con múltiples cláusulas (cobertura, exclusiones, primas, carencias,
  vigencia, siniestros, retracto…), estilos de cabecera heterogéneos y, en
  algunos casos, documentos compuestos con varias pólizas/anexos anidados.
- El problema práctico: un asesor que atiende consultas debe **leer el contrato
  correcto, en el artículo correcto, cada vez** — lento y propenso a error.
- El problema técnico: la respuesta correcta no es "generar", es **encontrar el
  fragmento fiel** dentro de la documentación y **devolverlo citando la fuente**.
- **Ciclo de vida del producto** (marco de todo el mapa de actores):

  ```
  condiciones generales (molde) → registro de producto → emisión → cartera en vigencia → terminación
  ```

  El corpus de este proyecto son **moldes (condiciones generales)**, no pólizas
  emitidas.

### El corpus = catálogo de la corredora

El catálogo que maneja la corredora responde al **mercado general**: son moldes
de condiciones generales **extraídos del Depósito de Pólizas de la CMF** (donde
las aseguradoras depositan sus condiciones antes de comercializar, DFL 251 /
NCG 349). Los **9 moldes de ejemplo del dataset son anónimos** (sin nombre de
aseguradora), sirven para responder **consultas generales** y para la
**recombinación** de la corredora. La aseguradora real se identifica por
conversación/CRM, y las referencias a **compañías específicas** se resuelven con
`web_search` citado.

Regla de alcance (por dominio):

- **Dominio (dentro de las pólizas):** respondemos con citas a partir del corpus.
- **Relacionado (dentro del dominio, fuera del corpus):** información que el
  asesor puede necesitar y que vive en la web — precios y **rangos de valores
  (incluyendo precios)** para un tipo de póliza, normativa vigente del
  regulador, compañías reales, noticias/requisitos del rubro — se complementa
  vía `web_search` del agente (#8, en el MVP), con fuente externa siempre
  marcada. **Nunca se inventa una cifra** desde el corpus (que no tiene
  precios) ni se presenta un dato web como si fuera de póliza.
- **Fuera del dominio (la pregunta no es de seguros/pólizas):** no devolvemos
  contenido; explicamos brevemente por qué no podemos responder y reiteramos el
  alcance del asistente.

### Nota de proveniencia (códigos)

El patrón `POL{ramo}0{YY}{seq}` (p. ej. `POL320130223`) y el mapeo
`ramo 32 → salud`, `resto → accidentes` son una **heurística propia inferida de
los títulos del dataset** (`app/data/eda.py:45-51`), no una tabla oficial del
regulador; aplica a **códigos de depósito**, no a pólizas emitidas. Se conserva
documentado en `docs/CONTRACTS.md` §1.1 y `docs/ARCHITECTURE.md` §3.

---

## 2. Mapa de actores

El chatbot **no es un actor**: es una **pieza móvil** que se puede parar sobre
otros actores. La decisión del proyecto: **está parado sobre la corredora** y
asiste al **humano interno** (el asesor), que tiene **dos tareas**: responder al
cliente final y recombinar pólizas. Una interfaz directa al cliente final (B2C)
es una **evolución futura** (otra piel del mismo motor).

### 2.1 Inventario de actores y roles

| Entidad | Roles | Función en el ciclo | Atendido por el bot |
|---|---|---|---|
| **Regulador** (CMF / Superint. de Salud) | Depósito de Pólizas, autorización de moldes, NCG 349 / DFL 251 | Da existencia legal a los moldes (fuente del corpus) | No (contexto/envolvente) |
| **Aseguradora (emisora)** | Suscriptor/underwriter · Área técnica · Jurídico · Servicio al asegurado | Fija condiciones/prima; deposita moldes; convierte un **DEM** en **POL** | Indirecto (la corredora la asesora con el bot) |
| **Corredora (intermediario)** | **Asesor/a interno** · Corredor certificado · Admin. de cartera/CRM | Traduce la pregunta del cliente → consulta pólizas → responde con respaldo; **recombina** | **Sí (parada principal)** |
| **Cliente final** | **Solicitante** (pre-emisión) · **Asegurado** (post-emisión) | Aplica con datos personales; usa la póliza; consulta, denuncia, renueva | No directo (vía el asesor; B2C = futuro) |
| **Chatbot (pieza móvil)** | — | Asistente alojado en la corredora; dos tareas: responder + recombinar | Es la pieza |

### 2.2 Visual del mapa (rail + tablero de ciclo)

**Rail (quién está parado dónde):**

```
[REGULADOR · Depósito de Pólizas]──► catálogo de moldes ◄── [ASEGURADORAS]
                                                  │
                                    [CORREDORA ◉ bot]  ← pieza móvil
                                   asistido: asesor/a interno
                                   (2 tareas: responder + recombinar)
                                    │              │
                          asesora clientes   asesora aseguradoras
                                  ▼
                          [CLIENTE FINAL]
```

**Tablero de ciclo (dónde y cuándo opera):**

```
                 SUSCRIPCIÓN      EMISIÓN       VIGENCIA       SINIESTRO/RENOV.
Regulador         ● deposita moldes
Aseguradora       ▪ define/¿→POL   ▪ convierte DEM→POL
Corredora         ▪ bot: perfil +  ▪ bot: recombinar    ◉ bot: responder      ▪ bot: citas
                   resp. documental  (demo DEM v0)      consultas             (denuncia, plazos)
Cliente           ◯ solicita       ◯ contrata          ◯ usa
```

### 2.3 Decisiones de posicionamiento (cerradas)

1. **El bot asiste al humano dentro de la corredora**, no responde desde la
   corredora a un cliente final (B2C queda como evolución).
2. La corredora, **como intermediario, cumple un rol central: asiste tanto a
   aseguradoras como a clientes finales**; el bot multiplica esa asesoría.
3. La recombinación produce un **estándar propio de la corredora** con **código
   propio (DEM, no POL)**: es un borrador/propuesta; la **aseguradora puede
   adoptarla** y, si decide, **depositarla como POL** en la CMF.
4. El corpus es el **catálogo de la corredora**: moldes anónimos del Depósito,
   respuesta a consultas generales del mercado.

---

## 3. Usuario final (a quien asiste la pieza)

### Persona primaria: asesor/a interno de la corredora (B2B)

| Dimensión | Qué implica |
|---|---|
| **Quién es** | Quien atiende consultas (chat/teléfono/mail) y **recombina** propuestas sobre el catálogo que la corredora administra. |
| **Qué tareas cumple (dos)** | 1) **Responder**: interpretar la pregunta del cliente, ubicar la cláusula, confirmar en el contrato y comunicar con respaldo. 2) **Recombinar**: armar borradores estándar (DEM) a partir de los moldes del mercado para proponérselos a las aseguradoras. |
| **Qué preguntas hace** | ¿Cubre X? ¿Por qué no me cubre Y (exclusión/limitación)? ¿Vigencia y renovación? Plazos de siniestro. Caso COVID. **¿Qué rangos de valores/precios hay para este tipo de póliza?** (→ web citada). ¿Qué incluiría un borrador DEM para este perfil? |
| **Qué necesita del chatbot** | 1. Respuesta clara  2. **Fragmento textual original**  3. **Cita verificable**  4. Cobertura de **todas** las cláusulas  5. Privacidad de la consulta  6. **Ensamblar un borrador DEM** desde bloques + perfil, **sin PII**. |
| **Fuera de dominio** | Pregunta que no es de pólizas: explicación breve + alcance + canal oficial. (Guardrail #17/#20.) |

El **cliente final** es usuario **indirecto** (lo atiende el asesor); el
**asegurador** es destinatario de la asesoría/recombinación de la corredora.

### Necesidades → criterios de diseño (ver §5)

Seguridad y privacidad, trazabilidad, cero alucinación y velocidad (en ese
orden). Sin PII en el sistema (ver §4).

---

## 4. Perfil del cliente: sin datos personales

El bot define **mínimamente el perfil del cliente final sin pedir datos
identificatorios ni almacenar información sensible**. Solo consulta las
**condiciones de perfil que las pólizas requieren para acotar áreas de
cobertura**, verificadas en el corpus:

| Condición de perfil | En cuántas pólizas | Qué condiciona (cláusula) | Dato sensible (Ley 19.628) |
|---|---|---|---|
| **Edad** | 9/9 | Admisión, primas por banda, fin de vigencia, carencias | No |
| **Preexistencias / salud** | 8/9 | Exclusión de preexistencias | **Sí** |
| **Deportes / actividades de riesgo** | 7/9 | Exclusiones y limitaciones | **Sí** |
| **Fonasa / Isapre** | 7/9 | Elegibilidad de algunos complementarios | Personal (no sensible) |
| **Embarazo / maternidad** | 7/9 | Carencia de maternidad / cobertura de parto | **Sí** |
| **Enfermedades crónicas** | 2/9 | Exclusiones específicas | **Sí** |
| **Vínculo laboral / colectivo** | 3/9 | Seguros colectivos y COVID; admisión por grupo | Personal |
| **Residencia** | 1/9 | Límites de cobertura por país | Personal |

### Reglas de diseño del perfil

1. **Opciones curadas, no texto libre**: bandas etarias, sí/no, listas
   fijas (Fonasa/Isapre, país) → sin interpretación ni datos abiertos.
2. **No persiste**: el perfil vive solo en el contexto de la conversación
   (in-memory); nunca en la base del sistema.
3. **Lo confirma el asesor** (ya lo conoce por la entrevista/CRM): el cliente no
   teclea nada sensible.
4. **Algunas de estas condiciones son "datos sensibles"** (salud: preexistencias,
   embarazo, enfermedades crónicas): se manejan solo como selector de cláusula,
   sin registrarlas.
5. La salida siempre es **condicional y textual**: "según este perfil, el texto
   del producto condiciona X" — **nunca un precio ni una decisión** (el precio,
   cuando se pida, va por `web_search` citado como rango de mercado).
6. En la recombinación (DEM), el perfil solo alimenta la **selección de bloques**
   (qué cláusulas entran al borrador), no datos del cliente en el documento.

---

## 5. Prioridades → criterio de diseño

Pirámide de prioridades. El orden ES criterio de diseño: cuando dos prioridades
pelean, gana la de mayor rango.

| # | Prioridad | Criterio de diseño que impone |
|---|---|---|
| 1 | **Seguridad** | Stack 100% local (Ollama + Qdrant en docker compose, sin nube); datos de póliza en volúmenes internos; CORS acotado; **sin PII** en el corpus ni en el sistema (perfil solo in-memory). |
| 2 | **Trazabilidad** | `answer` **siempre** con `sources[]` (contrato `docs/CONTRACTS.md` §3); la UI muestra póliza/artículo/página; todo paso verificable. |
| 3 | **0 alucinación** | RAG *grounded*: el LLM **solo cita** contexto recuperado; umbral de score (`UMBRAL_SCORE`) filtra en código antes del LLM; si nada responde, no inventa; las fuentes **web van siempre marcadas** (`origen: web`); guardrail de dominio; **nunca se inventa un precio/rango**; el eval (#19) mide `recall@k`, `cita_ok` y marcación de externas. |
| 4 | **Velocidad** (si queda) | Inferencia local, `top_k=5`, chunking fijo, respuesta en segundos. |

Trade-off explícito: **trazabilidad y cero alucinación > velocidad.** Si una cita
correcta es más lenta, se paga el costo; la velocidad se optimiza recién al final.

---

## 6. Células de la solución (bloques del bloque Solución)

Siete células, agrupadas en **4 macro-bloques** para la presentación:

```
Datos (D1→D2) ─► Motor RAG (R1→R2) ─► Exposición (E1)
                          │
Generación (G0) ◄─ recombinar DEM (demo v0)
                          ▲
Garantías (G1) ─── valida/asegura ───┘
```

| Macro | Célula | Entregable | Prioridad dominante | Issues |
|---|---|---|---|---|
| **Datos** | **Captura y limpieza** | PDFs → `articulos.jsonl` (segmentados, limpios, con metadata) | Trazabilidad | #4 |
| | **Chunking** | `articulos.jsonl` → `chunks.jsonl` (no cruzan artículo) | Trazabilidad + completud | #7 |
| **Motor RAG** | **Indexación y retrieval** | chunks → Qdrant (`polizas`, 1024d, coseno) + `search()` | 0 alucinación + velocidad | #9 |
| | **Generación con citas (agente)** | `query()` = agente ≤2 llamadas: retrieve → juzgar → (si falta, `web_search`) → `answer` + `sources[]` | Trazabilidad + 0 alucinación | #17, #8 |
| **Generación** | **Recombinación DEM (demo v0)** | `app/generation/` → endpoint `/policy-recombine` + **PDF borrador DEM** (bloques canónicos + perfil sin PII; sin emisión) | Regla de negocio (núcleo del enunciado) | #23 |
| **Exposición** | **API + UI** | FastAPI (`/chat`, `/health`, `/policies`, `/policy-recombine`) + Chainlit con fuentes visibles | Trazabilidad | #16, #18 |
| **Garantías** | **QA, eval y ops** | pytest (mocks), eval golden set, compose de 1 comando | Seguridad + 0 alucinación **medidos** | #19, #20, #21, #22 |

Cada célula en la presentación muestra: **qué produce · cómo se prueba · qué
prioridad protege.**

---

## 7. Mapa de slides (20)

| # | Slide | Bloque mandatorio |
|---|---|---|
| 1 | Título | — |
| 2 | Agenda | — |
| 3 | Contexto y regla de negocio | Problem |
| 4 | **Mapa de actores** (rail + tablero de ciclo) | Problem |
| 5 | **Persona: asesor/a de la corredora (dos tareas)** | Problem |
| 6 | **Perfil del cliente sin PII** | Problem |
| 7 | El problema en números | Problem |
| 8 | **Requisitos → prioridades (pirámide)** | Problem |
| 9 | **Alcance y guardrails** (incluye rangos de precios vía web) | Problem |
| 10 | Fuente y acceso | Dataset |
| 11 | Estructura descubierta (EDA) | Dataset |
| 12 | Calidad (EDA) | Dataset |
| 13 | Cómo la aprovechamos | Dataset |
| 14 | **Arquitectura en células** (incluye Generación v0) | Solution |
| 15 | Datos: D1 + D2 | Solution |
| 16 | Motor: R1 | Solution |
| 17 | Motor: R2 — **agente + web** (≤2 llamadas, `UMBRAL_SCORE`, rangos vía web) | Solution |
| 18 | **Exposición + Generación** (API + UI; `/policy-recombine` → PDF DEM) | Solution |
| 19 | Garantías y roadmap: G1 + M1/M2/M3 (incluye demo v0 de recombinación) | Solution |
| 20 | Próximos pasos | — |

Cambios respecto del deck actual (16→20): nuevas slides **4 (Mapa de actores)**,
**6 (Perfil sin PII)**; Persona pasa a mostrar las **dos tareas**; Alcance suma
los rangos de precios vía web; Exposición suma la **generación DEM v0**;
Garantías absorbe la generación en el roadmap (#23).
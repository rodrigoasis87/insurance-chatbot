# Narrativa del prototipo

Orden de la historia para la presentación y referencia del diseño. Tres bloques
mandatorios (Contexto / Dataset / Solución) exactamente como pide la consigna del
prototipo; dentro de Solución viven las **células**.

---

## 0. La regla de negocio (ancla de todo)

> Ante una pregunta del usuario **sobre pólizas de seguros de salud**, la
> aplicación debe **devolver el fragmento fiel de la póliza** que responde la
> pregunta, **con su cita** (`póliza · Art. N`), sin inventar nada. Si la respuesta
> exige información relacionada que no está en las pólizas (mercado, normativa),
> el **agente** la complementa con búsqueda web, siempre con la fuente marcada
> como externa.

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


Regla de alcance (por dominio):

- **Dominio (dentro de las pólizas):** respondemos con citas a partir del corpus.
- **Relacionado (dentro del dominio, fuera del corpus):** información que el
  asesor puede necesitar y que vive en la web — precios de pólizas de la
  competencia, normativa vigente del regulador, noticias/requisitos del rubro —
  se complementa vía `web_search` del agente (#8, en el MVP), con fuente externa
  siempre marcada.
- **Fuera del dominio (la pregunta no es de seguros/pólizas):** no devolvemos
  contenido; explicamos brevemente por qué no podemos responder y reiteramos el
  alcance del asistente.

---

## 2. Usuario final

### Persona primaria (B2B): asesor/a de atención de una corredora de seguros de salud

| Dimensión | Qué implica |
|---|---|
| **Quién es** | Quien contesta consultas de asegurados (por chat, teléfono o mail) sobre las pólizas que la corredora administra. |
| **Qué tareas cumple** | Interpretar la pregunta del cliente, ubicar la cláusula que aplica, confirmar la respuesta en el contrato y comunicarla con respaldo; ocasionalmente complementar con contexto de mercado (precios, normativa). |
| **Qué preguntas hace** | ¿Cubre X procedimiento/hospitalización? ¿Por qué no me cubre Y (exclusión/limitación)? ¿Cuánto es la prima/carencia? ¿Vigencia y renovación? ¿Cómo y en qué plazo denunciar un siniestro? Caso COVID. = los temas del *golden set* (#19). |
| **Qué necesita del chatbot** | 1. Respuesta clara y directa. 2. El **fragmento textual original** que la respalda (transparencia y completud). 3. **Cita verificable** (póliza · art. · página) para confiar sin releer el PDF. 4. Cobertura de **todas** las cláusulas, no solo cobertura. 5. Que su consulta **no salga del sistema** (privacidad). |
| **Fuera de dominio** | Pregunta que no es de pólizas de seguros: no devolver contenido; explicación breve de por qué no contestamos + reiterar el alcance + sugerir el canal oficial. La info relacionada del rubro se complementa con `web_search` del agente (#8, en el MVP). (Guardrail, en #17/#20.) |

### Necesidades → criterios de diseño (ver sección 3)

Seguridad y privacidad, trazabilidad, cero alucinación y velocidad (en ese orden).

---

## 3. Prioridades → criterio de diseño

Pirámide de prioridades. El orden ES criterio de diseño: cuando dos prioridades
pelean, gana la de mayor rango.

| # | Prioridad | Criterio de diseño que impone |
|---|---|---|
| 1 | **Seguridad** | Stack 100% local (Ollama + Qdrant en docker compose, sin nube); datos de póliza en volúmenes internos; CORS acotado; sin PII en el corpus. |
| 2 | **Trazabilidad** | `answer` **siempre** con `sources[]` (contrato `docs/CONTRACTS.md` §3); la UI muestra póliza/artículo/página; cada paso del pipeline es verificable. |
| 3 | **0 alucinación** | RAG *grounded*: el LLM **solo cita** contexto recuperado; umbral de score (`UMBRAL_SCORE`) filtra en código antes del LLM; si nada responde, no inventa ("no está en las fuentes"); las fuentes **web van siempre marcadas** (`origen: web`); guardrail de dominio (fuera de pólizas no se responde); el eval (#19) mide `recall@k`, `cita_ok` y la marcación de externas. |
| 4 | **Velocidad** (si queda) | Inferencia local, `top_k=5`, chunking fijo, respuesta en segundos. |

Trade-off explícito: **trazabilidad y cero alucinación > velocidad.** Si una cita
correcta es más lenta, se paga el costo; la velocidad se optimiza recién al final.

---

## 4. Células de la solución (bloques del bloque Solución)

Seis células, agrupadas en **4 macro-bloques** para la presentación:

```
Datos (D1→D2) ─► Motor RAG (R1→R2) ─► Exposición (E1)
                                    ▲
Garantías (G1) ─── valida/asegura ───┘
```

| Macro | Célula | Entregable | Prioridad dominante | Issues |
|---|---|---|---|---|
| **Datos** | **Captura y limpieza** | PDFs → `articulos.jsonl` (segmentados, limpios, con metadata) | Trazabilidad (metadata de origen) | #4 |
| | **Chunking** | `articulos.jsonl` → `chunks.jsonl` (chunks que no cruzan artículo) | Trazabilidad + completud | #7 |
| **Motor RAG** | **Indexación y retrieval** | chunks → Qdrant (`polizas`, 768d, coseno) + `search()` | 0 alucinación (recuperar lo correcto) + velocidad | #9 |
| | **Generación con citas (agente)** | `query()` = **agente ≤2 llamadas**: retrieve → juzgar → (si falta, `web_search`) → `answer` + `sources[]` (`origen: poliza·web`) | Trazabilidad + 0 alucinación | #17, #8 |
| **Exposición** | **API + UI** | FastAPI (`/chat`, `/health`, `/policies`) + Chainlit con fuentes visibles | Trazabilidad (el usuario ve la cita) | #16, #18 |
| **Garantías** | **QA, eval y ops** | pytest (mocks), eval golden set (`recall@k`, `cita_ok`), compose de 1 comando | Seguridad + 0 alucinación **medidos** | #19, #20, #21, #22 |

Cada célula en la presentación muestra: **qué produce · cómo se prueba · qué
prioridad protege.**

---

## 5. Mapa de slides (18)

| # | Slide | Bloque mandatorio |
|---|---|---|
| 1 | Título | — |
| 2 | Agenda | — |
| 3 | Contexto y regla de negocio | Problem |
| 4 | **Persona (asesor/corredor)** | Problem |
| 5 | El problema en números | Problem |
| 6 | **Requisitos → prioridades (pirámide)** | Problem |
| 7 | **Alcance y guardrails** (dominio / relacionado vía web / fuera de dominio) | Problem |
| 8 | Fuente y acceso | Dataset |
| 9 | Estructura descubierta (EDA) | Dataset |
| 10 | Calidad (EDA) | Dataset |
| 11 | Cómo la aprovechamos | Dataset |
| 12 | **Arquitectura en células** (4 macro / 6 células) | Solution |
| 13 | Datos: D1 + D2 | Solution |
| 14 | Motor: R1 | Solution |
| 15 | Motor: R2 — **agente + web** (≤2 llamadas, `UMBRAL_SCORE`, guardrail) | Solution |
| 16 | Exposición: E1 | Solution |
| 17 | Garantías y roadmap: G1 + M1/M2/M3 (MVP: cita interna + ejemplo web marcado) | Solution |
| 18 | Próximos pasos | — |

Cambios respecto del deck actual (16): nuevas slides **4 (Persona)**, **6
(prioridades)** y **7 (guardrails)**; la de Arquitectura pasa a presentar las
células; Garantías absorbe el roadmap.
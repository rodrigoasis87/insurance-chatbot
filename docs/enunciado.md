# Enunciado oficial · Insurance Policy Generation Chatbot

Referencia de la consigna del proyecto final (AnyoneAI). El texto íntegro vive
en el documento del curso; este archivo conserva **los requisitos vinculantes**
sobre los que se diseñó el prototipo (respaldan decisiones en
`docs/narrative.md`, `docs/ARCHITECTURE.md` y `docs/STACK.md`).

---

## 1. Qué pide el enunciado

- Un **chatbot con IA** para **profesionales/as de compañías de seguros** que
  asiste durante el **proceso de suscripción y evaluación de riesgos**
  (underwriting) y en la **creación de pólizas**.
- Capacidad central: a partir de una **base de pólizas previas**, el sistema
  debe poder **generar (recombinar) pólizas nuevas** (cláusulas nuevas,
  personalización, parámetros).
- Debe responder **preguntas sobre compañías específicas del rubro**.
- Incluye **búsqueda web** y **resumen** de información.
- Un **interfaz de usuario** (web y/o móvil) para interactuar con el asistente.
- Sugerencias del enunciado: ChatGPT/OpenAI, Pinecone, Haystack, LangChain.
  (Ver `docs/STACK.md` ADR-001: se eligió un stack **100% local y gratuito**
  que cumple los entregables obligatorios — LangChain Agents/Tools, API, UI,
  Docker — divergiendo deliberadamente de los servicios de pago.)

## 2. Traducción al alcance del prototipo

El asistente se posiciona **dentro de una corredora de seguros** (intermediario
regulado) y asiste al **humano interno** en sus dos tareas:

1. **Responder consultas** sobre el catálogo de pólizas que la corredora
   administra (con citas fieles del contrato).
2. **Recombinar** pólizas a partir de los casos detectados en el mercado,
   produciendo un **borrador estándar propio (código DEM)**, que una
   aseguradora puede adoptar y depositar luego como póliza (código POL).

Relación con la consigna:

| Requisito del enunciado | Cómo lo cubre el prototipo |
|---|---|
| Asistente para compañías de seguros | Asiste al asesor **dentro de la corredora** (intermediario central que asesora tanto a aseguradoras como a clientes finales). |
| Underwriting / evaluación de riesgos | Faceta **documental de la suscripción**: el bot informa qué exige/mitiga el contrato para un perfil, **sin decidir ni tarificar** (decisión humana). |
| Generar pólizas nuevas a partir de pólizas previas | **Recombinación DEM (demo v0)**: ensambla bloques de cláusulas canónicas de los moldes del catálogo + perfil → borrador DEM en PDF. |
| Preguntas sobre compañías específicas | Corpus anónimo declarado; compañías reales → `web_search` **citada** (`origen:"web"`). |
| Búsqueda web + resumen | Agente con `web_search` (DDG), ≤2 llamadas LLM, fuente siempre marcada. |
| UI web / móvil | Chainlit (web) + API FastAPI; interfaz directa al cliente final = evolución futura (misma piel). |

## 3. Entregables obligatorios del proyecto

- LangChain Agents and Tools (ruteo pólizas / rubro / recombinar / fuera de
  dominio).
- API (FastAPI) y UI (Chainlit).
- Docker Compose (Qdrant + Ollama, 1 comando).
- Aplicación que resuelve el problema con el stack elegido.
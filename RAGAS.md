# Evaluación RAG con RAGAS

Estado: **runner implementado; piloto de extremo a extremo completado para una pregunta y Faithfulness**.

## Qué hay y qué falta

El proyecto ya ofrece las piezas centrales del pipeline: `search()` recupera
chunks con metadata y score, `query()` genera la respuesta y entrega fuentes con
fragmentos, y `data/processed/articulos.jsonl` conserva el texto fuente. El
script `scripts/analisis_umbral.py` ya tiene 26 preguntas con etiquetas de
cánonico esperado, pero esas etiquetas sirven para medir retrieval y no son
respuestas de referencia.

Se inició un golden set curado en
`data/evaluation/ragas_golden.jsonl`: 100 preguntas con respuestas de
referencia. Incluye 60 preguntas respaldadas por artículos del corpus, 20 casos
que requieren abstención y 20 preguntas de información aseguradora externa que
requieren fuentes web. Las preguntas de póliza incluyen la póliza y artículo esperados;
los casos web incluyen URLs de fuentes oficiales. Es una base inicial para
revisión humana; el tamaño no garantiza por sí solo representatividad ni
significancia estadística.

`scripts/evaluate_ragas.py` valida y ejecuta el golden set, usa Qdrant/Ollama,
captura por separado los contextos completos de póliza y web, y guarda
respuestas, rutas, citas y métricas por pregunta en `data/evaluation/results/`.
El parámetro opcional `trace` de `query()` habilita esa captura sin cambiar el
JSON de respuesta pública. El runner registra commit, modelos, embedding,
umbral, `top_k`, hash del corpus y estado/tamaño de la colección Qdrant.

## Golden set: cómo curarlo

Cada fila en `data/evaluation/ragas_golden.jsonl` lleva:

- `id`: identificador estable para comparar ejecuciones.
- `question`: pregunta en lenguaje natural, representativa del uso esperado.
- `reference_answer`: respuesta correcta y acotada a una póliza concreta,
  incluyendo límites cuando el artículo remite a condiciones particulares.
- `reference_contexts`: artículos que respaldan la respuesta (`poliza` y
  `documento`, `articulo` y título canónico. `documento` desambigua artículos
  repetidos en subdocumentos de una póliza.
- `reference_sources`: URLs primarias de CMF Educa para
  preguntas respondibles con web; verificar vigencia antes de reutilizar.
- `expected_behavior`: comportamiento previsto para separar respuestas
  documentales, abstenciones y respuestas con búsqueda web.

Las preguntas no incluyen el código de la póliza que sirve de fuente. Los
identificadores de póliza/documento/artículo viven solo en `reference_contexts`
como etiquetas para auditoría y evaluación; el runner no debe agregarlos a la
pregunta enviada al chatbot. Algunas reglas cambian entre pólizas, así que los
casos que no se puedan identificar por el tipo de cobertura podrían necesitar
varias fuentes aceptables o una pista de producto expresada en lenguaje natural.

Las respuestas de referencia son paráfrasis, no citas normativas. Se redactan
desde `articulos.jsonl`, se vinculan al artículo fuente y se revisan para evitar
generalizar entre pólizas. Las preguntas que no puede contestar el corpus llevan
expectativa explícita de abstención; no se deben forzar a una respuesta factual
inventada. Las referencias web se verificaron en CMF Educa el 2026-10-14;
revalidar las páginas y cifras antes de reutilizar ese segmento.

Las 20 filas web son casos de comportamiento esperado, no una afirmación de que
el flujo actual ya las enrute correctamente. `query()` habilita la web mediante
una lista acotada de palabras clave y el prompt pide `NEED_WEB` principalmente
para valores/precios de mercado. El runner debe reportar el éxito de enrutamiento
por separado y estos ejemplos pueden revelar una brecha del alcance actual.

## Integración propuesta

1. RAGAS está declarado en el grupo `eval` (`ragas>=0.4.3`) y `uv.lock`
   resuelve `ragas==0.4.3` para Python 3.12. La importación directa falla con
   `langchain-community==0.4.2`, porque RAGAS importa una ruta antigua de
   Vertex AI. Probé que un bootstrap de compatibilidad que registra clases
   Vertex AI no utilizadas permite importar `ragas` y `llm_factory` sin
   degradar LangChain ni instalar el proveedor Vertex AI. El runner encapsula
   ese ajuste y desactiva la telemetría de RAGAS (`RAGAS_DO_NOT_TRACK=true`).
   RAGAS no se incorpora a las dependencias de runtime de producción.
2. **Implementado:** `uv run --group eval python scripts/evaluate_ragas.py`
   ejecuta las 100 preguntas; `--limit 1` y `--behavior answer_from_policy`
   permiten pilotos acotados. `--no-web` evita búsquedas externas.
3. **Implementado:** `query(..., trace=...)` conserva los contextos completos
   posteriores al hard gate y los que recibió la generación final. La respuesta
   pública mantiene su estructura actual.
4. El runner aplica `Faithfulness`, `ContextRecall` y
   `ContextPrecisionWithReference` de RAGAS a respuestas de póliza que sí
   recibieron contextos. La relevancia de respuesta con embeddings queda para
   después de verificar el endpoint de embeddings compatible con Ollama.
5. Evaluar por separado: las 60 preguntas de póliza para métricas RAGAS; las 20
   abstenciones con una medida específica de cumplimiento de abstención; y las
   20 web con los contextos externos capturados y verificación de URL/citas. No
   calcular fidelidad de contexto de póliza para filas sin contextos de póliza.
6. **Implementado:** resultados crudos y agregados van a una carpeta de
   ejecución ignorada por Git. Después del piloto, resumir límites y muestras
   en documentación para el QM.

El piloto `20261014T202630662612Z` ejecutó `ragas-001` con `qwen3:4b-instruct`
como generador y juez, y obtuvo `Faithfulness = 1.0` (sin error de evaluación).
La ejecución tardó varios minutos para un solo caso en el entorno local; no es
razonable lanzar los 100 casos todavía. Además, la pregunta genérica sobre
reembolso médico recuperó varias pólizas de salud válidas, pero no la única
referencia curada. Hay que desambiguar esa pregunta con el tipo de producto en
lenguaje natural o aceptar todas las fuentes equivalentes antes de medir
recall/precision. El piloto demuestra que el flujo funciona, no que el golden
set esté validado ni que el juez sea fiable.

La configuración elegida para el primer piloto es `qwen3:4b-instruct` como juez
local vía endpoint compatible con OpenAI de Ollama (`http://localhost:11434/v1`).
El modelo de chat ya configurado en el proyecto es el mismo, pero para evaluar
conviene registrar por separado modelo generador y juez, y advertir que usar el
mismo modelo puede correlacionar errores. No se ha ejecutado aún una evaluación
ni verificado la calidad del modelo como juez.

La versión resuelta actualmente es RAGAS 0.4.3. La documentación oficial muestra
soporte para modelos locales vía endpoint compatible con
OpenAI, como Ollama. También presenta APIs de métricas basadas en
`SingleTurnSample` y `single_turn_ascore`, además del flujo `evaluate`; se debe
escoger una API y fijarla junto con la versión al implementar el runner. RAGAS
puede evaluar con un LLM como juez y algunas métricas requieren embeddings. El
proyecto ya tiene proveedores de LLM por LangChain y embeddings locales vía
Ollama, pero hay que confirmar que las integraciones elegidas funcionan con el
modelo disponible. Un modelo local pequeño reduce el envío de datos a terceros,
aunque sus puntuaciones pueden ser menos confiables; cualquier modelo externo
requiere considerar credenciales, costo y envío de preguntas/contextos.

## Métricas iniciales y límites

- **Faithfulness**: si las afirmaciones de la respuesta se apoyan en los
  contextos recuperados. Requiere respuesta, contexto y juez.
- **Answer/Response Relevancy**: si la respuesta atiende la pregunta; algunas
  implementaciones requieren embeddings además del juez.
- **Context Precision**: si los contextos relevantes aparecen arriba en el
  ranking; requiere referencia y juicio de relevancia.
- **Context Recall**: cuánto de la respuesta de referencia queda respaldado
  por los contextos; requiere referencias de respuesta/contexto de calidad.

RAGAS produce estimaciones, no certifica corrección legal. Debe acompañarse de
revisión humana de errores y de métricas deterministas del proyecto (por
ejemplo, cita presente y artículo/póliza esperado recuperado). En el reporte al
QM hay que indicar tamaño y composición del set, modelos usados y fecha.

## Próximo paso

Ejecutar un piloto real con pocas preguntas de póliza, revisar manualmente las
respuestas y confirmar que el juez `qwen3:4b-instruct` devuelve puntuaciones
útiles. Si el piloto funciona, evaluar el conjunto completo y revisar las 100
referencias. El pin alternativo `langchain-community==0.4.1` evita el import
fallido, pero el proyecto requiere `>=0.4.2`; el runner usa el bootstrap local
para evitar degradar esa dependencia.

## Referencias

- [RAGAS: quick start](https://docs.ragas.io/en/stable/getstarted/quickstart/)
- [RAGAS: métricas disponibles](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/)
- [RAGAS: Context Precision](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/)
- `scripts/analisis_umbral.py` y `docs/umbral_score.md` (etiquetas de retrieval).
- `app/rag/query.py` (flujo de respuesta) y `app/rag/vectordb.py` (contextos recuperados).
- Fuentes web del golden set: CMF Educa (Seguro de Salud y SOAP), enlazadas
  por fila.

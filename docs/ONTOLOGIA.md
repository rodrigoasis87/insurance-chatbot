# Ontología y taxonomía del dominio

Documento de **vocabulario controlado** del proyecto: define los términos,
jerarquías, esquemas y relaciones que comparten el parser, el retrieval, el
perfil del cliente y la recombinación. Es la referencia canónica para nombrar
cosas de forma consistente en código, contratos, issues y presentaciones.

> **Fuentes vivas de este documento** (en caso de divergencia, manda la fuente):
> `app/data/parser.py` (claves canónicas) · `docs/CONTRACTS.md` (schemas) ·
> `docs/narrative.md` (entidades, perfil, decisiones) · `app/data/eda.py:45-51`
> (proveniencia de códigos) · `docs/EDA.md` (corpus y familias).

---

## 1. Propósito y alcance

- **Para qué sirve:** nombrar de una sola forma las entidades y cláusulas del
  dominio, de modo que parser, metadata, agentes, UI y documentos no se
  contradigan.
- **Alcance del dominio:** pólizas de **seguros de salud** (ramo principal) y
  **accidentes personales** (caso de generalización del pipeline). El corpus son
  **moldes de condiciones generales anónimos** extraídos del Depósito de
  Pólizas de la CMF (DFL 251 / NCG 349).
- **Convenciones:** los términos marcados con `(diseño)` describen capacidades
  **planteadas pero no implementadas** (p. ej. la recombinación DEM). Las claves
  canónicas van en minúsculas y sin acento (son el identificador interno).

---

## 2. Entidades del dominio (actores y roles)

| Entidad | Rol | Función en el ciclo | Atendida por el bot |
|---|---|---|---|
| **Regulador** (CMF / Superint. de Salud) | Supervisión, Depósito de Pólizas, NCG 349 / DFL 251 | Da existencia legal a los moldes (fuente del corpus) | No (contexto/envolvente) |
| **Depósito de Pólizas** (instancia del regulador) | Registro público de condiciones generales | Fuente del catálogo de la corredora | No |
| **Aseguradora (emisora)** | Suscriptor/underwriter · técnica · jurídico · servicio | Fija condiciones/prima; deposita moldes; convierte un **DEM** en **POL** | Indirecto (la corredora la asesora con el bot) |
| **Corredora** | **Asesor/a interno** · corredor certificado · cartera/CRM | Traduce la pregunta del cliente → consulta pólizas → responde con respaldo; **recombina** | **Sí (posición principal del bot)** |
| **Cliente final** | **Solicitante** (pre-emisión) · **Asegurado** (post-emisión) | Aplica; usa la póliza; consulta, denuncia, renueva | No directo (vía el asesor; B2C = futuro) |
| **Chatbot** | Pieza móvil | Se para sobre la corredora; dos tareas: **responder** y **recombinar** | Es la pieza |

Fuente: `docs/narrative.md` §2.1.

---

## 3. Tipos de documento y su semántica

| Tipo | Significado | Formato de código | Estado | Emisor |
|---|---|---|---|---|
| **`POL`** | Póliza **depositada/regulada** en la CMF (condiciones generales comercializables) | `POL{ramo}0{YY}{seq}` (p. ej. `POL320130223`) | Depositada (puede tener vigencia, terminación…) | La **aseguradora** |
| **`DEM`** `(diseño)` | **Borrador estándar propio de la corredora**; propuesta, no emitida | `DEM{YYYY}{seq:04d}` (p. ej. `DEM20260001`) | Borrador | La **corredora** (con el asistente) |

- **Relación (semántica):** la corredora ensambla un **DEM** (borrador) desde los
  moldes del catálogo; la **aseguradora puede adoptarlo** y, si lo decide,
  **depositarlo como `POL`** en el Depósito. El DEM nunca es una `POL`.
- **Estado del producto (ciclo):** `condiciones generales (molde) → registro de
  producto → emisión → cartera en vigencia → terminación`. El corpus son molde
  (condiciones generales), **no** pólizas emitidas.
- **Nota de proveniencia:** el patrón `POL{ramo}0{YY}{seq}` y el mapeo de ramo son
  una **heurística propia inferida de los títulos del dataset**
  (`app/data/eda.py:45-51`), validada contra un código real del Depósito
  (`POL 320230367`) pero **no** una tabla oficial del regulador; aplica solo a
  **códigos de depósito**, no a pólizas emitidas. Ver `docs/CONTRACTS.md` §1.1
  y `docs/ARCHITECTURE.md` §5.1.

---

## 4. Ramos y familias de producto

Ramo = rama de negocio codificada en el código del Depósito (posiciones `3-4`).

### 4.1 Vocabulario de ramos

| Ramo (código) | Clave canónica | Observación |
|---|---|---|
| `32` | **`salud`** | **Ramo principal del prototipo** |
| `12` (resto) | **`accidentes`** | Caso de generalización; tema próximo a salud (reembolso de gastos médicos por accidente) |

Regla de decodificación (una sola vez, en #4): `ramo = "salud" si código[3:5]=="32"
else "accidentes"`.

### 4.2 Familias de producto del corpus (9 moldes)

| Familia | Ramo | Pólizas | Cubre en esencia |
|---|---|---|---|
| **Colectivo complementario de salud** | salud | `POL320130223` | Complemento de prestaciones para grupos/asociados |
| **Prestaciones médicas derivadas de accidentes** | salud | `POL320150503`, `POL320180100` | Reembolso de gastos médicos por accidente |
| **Prestaciones médicas de alto costo** | salud | `POL320190074`, `POL320200214`, `POL320210210` | Enfermedades/eventos de alto costo |
| **Catastrófico individual por evento** | salud | `POL320200071` | Evento catastrófico único con deducible/copago |
| **COVID-19 asociado** | salud | `POL320210063` | Cobertura COVID (molde con sintaxis de cabecera distinta) |
| **Accidentes personales / reembolso gastos médicos** | accidentes | `POL120190177` | Rembolso de gastos médicos por accidentes personales |

- El **retrieval y el perfil son salud-céntricos**; la póliza de accidentes sirve
  para **probar generalización** del parser fuera del ramo 32.
- **Multi-ramo** (sumar más ramos al catálogo) es una **evolución futura**
  (el motor no tiene lógica hard-coded por ramo).

Fuente: `docs/EDA.md` §1 (perfil del corpus) y `AÑO`/`titulo_portada` de cada
póliza.

---

## 5. Estructura documental: el esqueleto de cláusulas canónicas

### 5.1 Jerarquía del documento

```
Póliza (molde, código POL…)
 └─ Artículo  (unidad natural: `ARTÍCULO Nº NN: TÍTULO`, página 1-based)
     └─ Cláusula canónica  (clave normalizada del título del artículo)
         └─ Chunk (fragmento del artículo; nunca cruza de artículo)
```

Las **referencias inline** (`Artículo 2°, letra A, numeral 4…`) NO son cláusulas:
no abren un nuevo artículo; se descartan en la segmentación.

### 5.2 Vocabulario: 35 claves canónicas + fallback genérico

`TITLE_KEYWORDS` (`app/data/parser.py:36-72`) define **35 claves**, cada una con
sus keywords detonantes (matcheo sin acentos, las más específicas primero). Una
cabecera MAYÚSCULA corta que no matchea ninguna keyword se acepta como clave
**genérica** (su propio título normalizado) → eso da los **36** "tipos de
cláusula" que citan los decks (35 + genérico).

| # | Clave canónica | Keywords detonantes | Función |
|---|---|---|---|
| 1 | `reglas` | `reglas aplicables` | Normas de aplicación del contrato |
| 2 | `definiciones` | `definiciones` | Definición de términos |
| 3 | `declaraciones` | `declaraciones` | Declaraciones de las partes |
| 4 | `obligaciones` | `obligaciones` | Obligaciones del asegurado/asegurador |
| 5 | `unidad del contrato` | `unidad del contrato`, `unidad de la poliza`, `moneda o unidad` | Moneda/unidad en que se expresa el contrato |
| 6 | `incorporacion` | `incorporacion` | Incorporación de cláusulas/condiciones |
| 7 | `domicilio` | `domicilio` | Domicilio de las partes |
| 8 | `comunicaciones` | `comunicacion` | Comunicaciones y notificaciones |
| 9 | `modificaciones` | `modificaciones` | Modificación del contrato |
| 10 | `retracto` | `retracto` | Derecho de retracto |
| 11 | `agravacion del riesgo` | `agravacion` | Deber de declarar mayor riesgo |
| 12 | `rehabilitacion` | `rehabilitacion` | Rehabilitación de la cobertura |
| 13 | `descripcion de coberturas` | `descripcion de las coberturas`, `descripcion de coberturas` | Descripción general de coberturas |
| 14 | `riesgos cubiertos` | `riesgos cubiertos` | Riesgos amparados |
| 15 | `cobertura` | `cobertura` | Cobertura (cláusula central) |
| 16 | `exclusiones` | `exclusiones` | Excesiones de cobertura |
| 17 | `limitaciones` | `limitaciones` | Limitaciones a la cobertura |
| 18 | `otros seguros` | `otros seguros` | Relación con otros seguros |
| 19 | `duplicacion de beneficios` | `duplicacion` | Evitar doble pago de beneficios |
| 20 | `beneficiarios` | `beneficiarios` | Beneficiarios de la póliza |
| 21 | `primas` | `no pago de la prima`, `no pago de las primas`, `prima del seguro`, `primas` | Prima, su pago y consecuencias del no pago |
| 22 | `ajuste de la prima` | `ajuste de la prima` | Reajuste de la prima |
| 23 | `impuestos` | `impuestos`, `contribuciones` | Impuestos/contribuciones del contrato |
| 24 | `denuncia de siniestro` | `siniestro` | Procedimiento y plazos de denuncia |
| 25 | `monto maximo de reembolso` | `monto maximo de reembolso` | Tope máximo reembolsable |
| 26 | `liquidacion de gastos` | `liquidacion de los gastos`, `formula de liquidacion` | Liquidación/reembolso de gastos |
| 27 | `calculo de gastos` | `calculo de los gastos reembolsables` | Base de cálculo de los gastos reembolsables |
| 28 | `deducible` | `deducible` | Deducible por evento/periodo |
| 29 | `copago` | `copago` | Porcentaje/copago a cargo del asegurado |
| 30 | `carencia` | `carencia` | Periodo de carencia |
| 31 | `vigencia` | `vigencia` | Vigencia y renovación |
| 32 | `terminacion` | `terminacion`, `termino` | Terminación del contrato |
| 33 | `clausulas adicionales` | `clausulas adicionales` | Cláusulas adicionales / anexos |
| 34 | `pais de residencia` | `pais de residencia` | Residencia y sus límites |
| 35 | `controversias` | `controversias` | Solución de controversias/arbitraje |
| — | **genérico** | (sin keyword) | Cabecera MAYÚSCULA corta reconocida por heurística de formato |

Fuente: `app/data/parser.py` (§5.2) y `docs/CONTRACTS.md` §1 (esqueleto por
póliza). Números de la matriz de esqueleto por póliza: `docs/eda/polizas_estructura.csv`.

---

## 6. Esquema de metadata (el dato que viaja por el pipeline)

Campos del contrato M1→M2 (`docs/CONTRACTS.md` §1). `ramo`/`año` se decodifican
**una única vez** en #4 y desde ahí solo se propagan.

### 6.1 `articulos.jsonl` (salida de #4)

| Campo | Tipo | Ejemplo | Origen |
|---|---|---|---|
| `poliza` | str | `POL320130223` | Código del molde |
| `ramo` | str | `salud` | Regla de decodificación (heurística) |
| `año` | str | `2013` | `"20"+código[6:8]` |
| `articulo` | int | `2` | Cabecera del artículo |
| `titulo` | str | `COBERTURA` | Título limpio de la cabecera |
| `canonico` | str | `cobertura` | Clave canónica (§5.2) |
| `pagina` | int | `1` | Página 1-based del PDF |
| `chars` | int | `17403` | `len(texto)` sobre texto limpio |
| `texto` | str | `…cuerpo del artículo sin cabecera…` | Limpieza del texto |

### 6.2 `chunks.jsonl` (salida de #7)

`Document` de LangChain: `page_content` (fragmento) + `metadata` = `poliza`,
`ramo`, `año`, `articulo`, `titulo_canonico`, `pagina`, `chunk_index` (0-based
por `(poliza, articulo)`). El splitter no cruza de artículo. El retrieval agrega
`score` (coseno, colección `polizas`, 768 dims, `nomic-embed-text`).

Fuente: `docs/CONTRACTS.md` §1 y §2.

---

## 7. Taxonomía de fuentes y orígenes

| Origen | Qué es | Cita que produce | Regla |
|---|---|---|---|
| **`poliza`** | Fragmento del corpus (moldes) | `[fuente: POL320130223 · Art. 2 · pág. 1]` | Respuesta *grounded*; el LLM solo cita lo del contexto |
| **`web`** | Información externa del rubro (precios/rangos, normativa, compañías) | `[fuente web: <dominio>]` + URL | **Siempre marcada**; nunca se presenta como cita de póliza |
| **`fuera de dominio`** | La pregunta no es de seguros/pólizas | — | No se responde contenido; se explica el alcance |

- El corpus son **moldes anónimos**: sin PII ni nombre de aseguradora. Las
  compañías reales se resuelven con `web_search` citado.
- El corpus **no tiene precios**; los **rangos de valores/precios** del rubro se
  responden vía `web_search` con fuente marcada. **Nunca se inventa una cifra.**
- Filtrado de contexto: los chunks con `score < UMBRAL_SCORE` **no entran** al
  prompt (hard gate en código).

Fuente: `docs/narrative.md` §1 y `docs/CONTRACTS.md` §3.

---

## 8. Perfil del cliente sin PII (vocabulario controlado de rating)

El bot acota el perfil del cliente **sin datos identificatorios** ni retención;
solo consume las **condiciones de perfil que las pólizas requieren**. Cada
condición tiene un **tipo de valor** y un **dominio canónico fijo** (opciones
curadas; no hay texto libre).

| Condición de perfil | Tipo de valor | Dominio canónico (fijado) | En cuántas pólizas | Sensibilidad (Ley 19.628) |
|---|---|---|---|---|
| **Edad** | banda etaria | `0–18` · `19–29` · `30–40` · `41–50` · `51–60` · `61–70` · `71+` | 9/9 | No |
| **Preexistencias / salud** | sí–no | `no` · `sí` | 8/9 | **Sensible** |
| **Deportes / actividades de riesgo** | sí–no | `no` · `sí` | 7/9 | **Sensible** |
| **Fonasa / Isapre** | lista fija | `Fonasa` · `Isapre` | 7/9 | Personal |
| **Embarazo / maternidad** | sí–no | `no` · `sí` | 7/9 | **Sensible** |
| **Enfermedades crónicas** | sí–no | `no` · `sí` | 2/9 | **Sensible** |
| **Vínculo laboral / colectivo** | lista fija | `individual` · `colectivo` | 3/9 | Personal |
| **Residencia** | lista fija | `Chile` · `Extranjero` | 1/9 | Personal |

Reglas de diseño (fijadas, no negociables para el MVP):

1. **Opciones curadas:** el selector solo consume valores del dominio canónico;
   el LLM no interpreta texto abierto.
2. **No persiste:** el perfil vive solo en el contexto de la conversación
   (in-memory); nunca en la base del sistema.
3. **Lo confirma el asesor** (ya lo conoce por la entrevista/CRM): el cliente no
   teclea datos sensibles.
4. Las condiciones **sensibles** se manejan solo como **selector de cláusula**,
   sin registrarlas.
5. La salida es **condicional y textual** ("según este perfil, el producto
   condiciona X") — nunca un precio (los rangos van por `web_search` citado) ni
   una decisión.
6. En la recombinación (`(diseño)`), el perfil solo alimenta la **selección de
   bloques** de cláusulas; no va al documento.

Fuente: `docs/narrative.md` §4.

---

## 9. Capacidades del asistente (intenciones)

| Intención | Qué hace | Fuente que usa | Estado |
|---|---|---|---|
| **Responder (documental)** | Devuelve el fragmento fiel con `póliza · Art. N` | corpus (retrieval) | Implementado (MVP, #17) |
| **Valores/precios del rubro** | Rangos de mercado citados y marcados | `web_search` | MVP (#8) |
| **Recombinar → DEM** | Ensambla borrador estándar desde bloques + perfil | molde + perfil | **`(diseño)` post-MVP, no implementado** |
| **Fuera de dominio** | Negativa + alcance + canal oficial | — | MVP (#17/#20) |

---

## 10. Relaciones principales (grafo)

```
[Regulador/Depósito CMF] ──deposita──► {moldes (POL…)} ──catálogo──► [Corredora ◉ bot]
                                                                       │ assist: asesor interno
   [Cliente final] ◄──asesoría──┤  (dos tareas: responder · recombinar)
   [Aseguradora]  ◄──propuesta──┤
        ▲                       │    (diseño) ensambla DEM{YYYY}{seq}
        └──────adopta y deposita DEM ──► convierte en POL
```

Relaciones en forma de lista:

- `Regulador → Depósito → moldes (POL)` — fuente del corpus.
- `Corredora → bot` — posición principal; el bot asiste al **asesor interno**
  (humano), que **responde** y **recombina**.
- `Cliente final y Aseguradora ↔ Corredora` — la corredora asesora a ambos
  (intermediación); el bot multiplica esa asesoría.
- `molde → artículo → cláusula canónica → chunk` — jerarquía documental (§5.1);
  cada chunk lleva su metadata (§6).
- `perfil (curado) → condiciona cláusula` — sin PII: solo selectores en memoria.
- `origen → cita` — cada respuesta se traza a `poliza` o `web` (§7).
- `DEM (borrador) → adopción → POL (depositada)` — semántica de generación (§3,
  diseño).

---

## 11. Glosario

| Término | Definición |
|---|---|
| **RUT** | Cédula de identidad chilena (identificatorio; nunca entra al sistema) |
| **Fonasa** | Fondo Nacional de Salud: cobertura pública de salud en Chile |
| **Isapre** | Institución de Salud Previsional: aseguradores privados de salud |
| **CMF** | Comisión para el Mercado Financiero (regulador; Depósito de Pólizas) |
| **Depósito de Pólizas** | Registro público donde las aseguradoras depositan condiciones generales |
| **DFL 251 / NCG 349** | Normativa que regula contratos de seguros y depósito de condiciones |
| **UF** | Unidad de Fomento (moneda indexada chilena) — aparece en cláusulas de tope/montos |
| **POL** | Póliza depositada/regulada (§3) |
| **DEM** | Borrador estándar de la corredora (§3, `(diseño)`) |
| **Molde** | Condiciones generales (tipo de producto); el corpus es puro molde |
| **Asegurado / Solicitante** | Cliente final post-emisión / pre-emisión |

---

## 12. Trazabilidad (de dónde sale cada término)

| Sección de esta ontología | Fuente |
|---|---|
| §2 entidades | `docs/narrative.md` §2.1 |
| §3 tipos de documento | `docs/narrative.md` §2.3 · `docs/ARCHITECTURE.md` §3/§5.2 · `docs/CONTRACTS.md` §4.1 |
| §4 ramos y familias | `app/data/eda.py:45-51` · `docs/EDA.md` §1 · `docs/EDA.md` (títulos) |
| §5 esqueleto y claves | `app/data/parser.py:36-72` · `docs/eda/polizas_estructura.csv` |
| §6 metadata | `docs/CONTRACTS.md` §1 y §2 |
| §7 orígenes | `docs/narrative.md` §1 · `docs/CONTRACTS.md` §3 |
| §8 perfil | `docs/narrative.md` §4 |
| §9 intenciones | `docs/narrative.md` §5/§6 · `docs/CONTRACTS.md` §4 |
| §11 glosario | definiciones estándar del rubro; usadas en `docs/narrative.md` §4 |
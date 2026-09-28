# EDA · Corpus de Pólizas (Issue #3)

Reporte generado con `uv run python -m app.data.eda`.
- PDFs de origen: `data/raw_pdfs/` (no versionados).
- Script: `app/data/eda.py` · estructura por póliza: `docs/eda/polizas_estructura.csv` + `.json` · deep-dive del Artículo 2: `docs/eda/cobertura_articulo2.md`.

## 1. Perfil del corpus

| poliza | ramo | año | paginas | chars | tablas | imagenes | articulos | productor | titulo_portada |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| POL120190177 | accidentes | 2019 | 14 | 59347 | 0 | 0 | 23 | FPDF 1.6 | PÓLIZA DE ACCIDENTES PERSONALES / REEMBOLSO GASTOS MÉDICOS |
| POL320130223 | salud | 2013 | 47 | 53229 | 0 | 0 | 19 | FPDF 1.6 | SEGURO COLECTIVO COMPLEMENTARIO DE SALUD  |
| POL320150503 | salud | 2015 | 26 | 63182 | 0 | 0 | 23 | FPDF 1.6 | PÓLIZA DE SEGURO PARA PRESTACIONES MÉDICAS DERIVADAS DE ACCIDENT |
| POL320180100 | salud | 2018 | 25 | 58486 | 0 | 0 | 23 | FPDF 1.6 | PÓLIZA DE SEGURO PARA PRESTACIONES MÉDICAS DERIVADAS DE |
| POL320190074 | salud | 2019 | 72 | 106450 | 0 | 0 | 52 | iLovePDF | SEGURO PARA PRESTACIONES MÉDICAS DE ALTO COSTO |
| POL320200071 | salud | 2020 | 25 | 85630 | 0 | 0 | 40 | iLovePDF | SEGURO INDIVIDUAL CATASTRÓFICO POR EVENTO |
| POL320200214 | salud | 2020 | 42 | 79458 | 0 | 4 | 20 | GPL Ghostscript 8.70 | SEGURO PARA PRESTACIONES MÉDICAS DE ALTO COSTO |
| POL320210063 | salud | 2021 | 6 | 16383 | 0 | 0 | 12 | GPL Ghostscript 8.70 | SEGURO INDIVIDUAL OBLIGATORIO DE SALUD ASOCIADO A COVID 19 |
| POL320210210 | salud | 2021 | 10 | 25683 | 0 | 0 | 15 | FPDF 1.6 | SEGURO PARA PRESTACIONES MÉDICAS DE ALTO COSTO |

## 2. Esqueleto estándar de artículos

Las pólizas comparten el mismo esqueleto de artículos (reglas → cobertura →
definiciones → … → cláusulas adicionales). Matriz de posiciones:

| pos | POL120190177 | POL320130223 | POL320150503 | POL320180100 | POL320190074 | POL320200071 | POL320200214 | POL320210063 | POL320210210 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | reglas | reglas | reglas | reglas | reglas | reglas | reglas | reglas | reglas |
| 2 | cobertura | cobertura | cobertura | cobertura | cobertura | cobertura | cobertura | cobertura | cobertura |
| 3 | limitaciones | definiciones | limitaciones | limitaciones | definiciones | descripcion de coberturas | definiciones | primas | definiciones |
| 4 | definiciones | monto maximo de reembolso | definiciones | definiciones | exclusiones | limitaciones | exclusiones | exclusiones | exclusiones |
| 5 | exclusiones | duplicacion de beneficios | exclusiones | exclusiones | carencia | definiciones | deducible | denuncia de siniestro | carencia |
| 6 | obligaciones | exclusiones | obligaciones | obligaciones | obligaciones | exclusiones | copago | otros seguros | obligaciones |
| 7 | declaraciones | riesgos cubiertos | declaraciones | declaraciones | declaraciones | obligaciones | obligaciones | terminacion | declaraciones |
| 8 | primas | obligaciones | primas | primas | primas | declaraciones | declaraciones | vigencia | primas |
| 9 | denuncia de siniestro | declaraciones | denuncia de siniestro | denuncia de siniestro | beneficiarios | vigencia | agravacion del riesgo | deducible | beneficiarios |
| 10 | calculo de gastos | beneficiarios | calculo de gastos | calculo de gastos | denuncia de siniestro | primas | primas | rehabilitacion | denuncia de siniestro |
| 11 | liquidacion de gastos | primas | liquidacion de gastos | liquidacion de gastos | vigencia | denuncia de siniestro | otros seguros | controversias | vigencia |
| 12 | deducible | denuncia de siniestro | deducible | deducible | comunicaciones | calculo de gastos | denuncia de siniestro | comunicaciones | comunicaciones |
| 13 | vigencia | vigencia | vigencia | vigencia | controversias | terminacion | vigencia | — | controversias |
| 14 | cobertura | incorporacion | cobertura | cobertura | clausulas adicionales | impuestos | terminacion | — | clausulas adicionales |
| 15 | terminacion | unidad del contrato | terminacion | terminacion | domicilio | unidad del contrato | modificaciones | — | domicilio |
| 16 | ajuste de la prima | comunicaciones | ajuste de la prima | ajuste de la prima | cobertura | comunicaciones | pais de residencia | — | — |
| 17 | unidad del contrato | controversias | unidad del contrato | unidad del contrato | exclusiones | controversias | comunicaciones | — | — |
| 18 | rehabilitacion | domicilio | rehabilitacion | rehabilitacion | carencia | retracto | controversias | — | — |
| 19 | impuestos | clausulas adicionales | impuestos | impuestos | beneficiarios | domicilio | clausulas adicionales | — | — |
| 20 | comunicaciones | — | comunicaciones | comunicaciones | denuncia de siniestro | clausulas adicionales | domicilio | — | — |
| 21 | controversias | — | controversias | controversias | Cláusulas Aplicables | reglas | — | — | — |
| 22 | clausulas adicionales | — | clausulas adicionales | clausulas adicionales | reglas | cobertura | — | — | — |
| 23 | domicilio | — | domicilio | domicilio | cobertura | limitaciones | — | — | — |
| 24 | — | — | — | — | definiciones | exclusiones | — | — | — |
| 25 | — | — | — | — | monto maximo de reembolso | obligaciones | — | — | — |
| 26 | — | — | — | — | duplicacion de beneficios | declaraciones | — | — | — |
| 27 | — | — | — | — | exclusiones | vigencia | — | — | — |
| 28 | — | — | — | — | riesgos cubiertos | primas | — | — | — |
| 29 | — | — | — | — | obligaciones | denuncia de siniestro | — | — | — |
| 30 | — | — | — | — | declaraciones | denuncia de siniestro | — | — | — |
| 31 | — | — | — | — | beneficiarios | denuncia de siniestro | — | — | — |
| 32 | — | — | — | — | primas | terminacion | — | — | — |
| 33 | — | — | — | — | denuncia de siniestro | rehabilitacion | — | — | — |
| 34 | — | — | — | — | vigencia | impuestos | — | — | — |
| 35 | — | — | — | — | incorporacion | unidad del contrato | — | — | — |
| 36 | — | — | — | — | unidad del contrato | comunicaciones | — | — | — |
| 37 | — | — | — | — | comunicaciones | controversias | — | — | — |
| 38 | — | — | — | — | controversias | retracto | — | — | — |
| 39 | — | — | — | — | domicilio | domicilio | — | — | — |
| 40 | — | — | — | — | clausulas adicionales | definiciones | — | — | — |
| 41 | — | — | — | — | cobertura | — | — | — | — |
| 42 | — | — | — | — | exclusiones | — | — | — | — |
| 43 | — | — | — | — | carencia | — | — | — | — |
| 44 | — | — | — | — | beneficiarios | — | — | — | — |
| 45 | — | — | — | — | denuncia de siniestro | — | — | — | — |
| 46 | — | — | — | — | Cláusulas Aplicables | — | — | — | — |
| 47 | — | — | — | — | cobertura | — | — | — | — |
| 48 | — | — | — | — | definiciones | — | — | — | — |
| 49 | — | — | — | — | exclusiones | — | — | — | — |
| 50 | — | — | — | — | denuncia de siniestro | — | — | — | — |
| 51 | — | — | — | — | terminacion | — | — | — | — |
| 52 | — | — | — | — | Cláusulas Aplicables | — | — | — | — |

## 3. Deep-dive · Artículo 2: Cobertura (pólizas de salud)

| poliza | chars | condiciones_particulares | carencia | uf | porcentajes | listas_letra | listas_numeral | incipit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| POL320130223 | 17403 | True | True | False | 50% | 12 | 4 | ARTÍCULO Nº 2: COBERTURA La compañía de seguros bajo las condiciones y términos que más adelante se establecen, conviene |
| POL320150503 | 10785 | True | False | False | - | 3 | 18 | ARTÍCULO 2º: COBERTURA Y MATERIA ASEGURADA La Compañía Aseguradora reembolsará al asegurado o pagará directamente al pre |
| POL320180100 | 6671 | True | False | False | - | 0 | 5 | ARTÍCULO 2º: COBERTURA Y MATERIA ASEGURADA La Compañía Aseguradora reembolsará al asegurado o pagará directamente al pre |
| POL320190074 | 4160 | True | True | False | - | 1 | 0 | ARTÍCULO 2º: COBERTURA La compañía aseguradora reembolsará los gastos médicos razonables, acostumbrados y efectivamente  |
| POL320200071 | 3743 | True | True | False | - | 0 | 0 | ARTICULO 2°. COBERTURA.- La compañía aseguradora reembolsará o pagará directamente al beneficiario o al prestador de sal |
| POL320200214 | 1138 | False | False | False | - | 0 | 0 | ARTÍCULO 2º: COBERTURA El Asegurador reembolsará los gastos médicos razonables, acostumbrados y efectivamente incurridos |
| POL320210063 | 2030 | False | False | False | 100% | 0 | 2 | Artículo 4. Cobertura. Este seguro cubre los siguientes riesgos: 1.- Riesgos de salud: a) Tratándose de los trabajadores |
| POL320210210 | 4174 | True | True | False | - | 1 | 0 | ARTÍCULO 2º: COBERTURA La compañía aseguradora reembolsará los gastos médicos razonables, acostumbrados y efectivamente  |

## 4. Tamaño de los artículos (insumo #7)

Longitud por artículo (chars): min **107** · mediana **1199** · max **25715** (n=227)

## 5. Hallazgos

- Cabeceras `ARTÍCULO` consistentes entre pólizas, con variantes de formato
  (`°`/`º`, `Nº`, `:` vs `.`, tilde opcional) → normalizables por regex.
- `pymupdf.find_tables()` detecta **0 tablas**: planes/saldos están en prosa
  corrida; `POL320200214` aporta 4 imágenes (logos/sellos).
- El Artículo 2 de salud es prosa legal densa: referencias constantes a
  "Condiciones Particulares", porcentajes de reembolso, carencia y UF.
- Casos borde: `POL320190074` (dos series de artículos 1..N anidadas dentro
  de Cláusulas Adicionales) y `POL320210063` (póliza COVID con sintaxis de
  cabecera distinta, ~2 artículos detectados).

## 6. Recomendaciones para el pipeline

- **#4 (parser):** segmentar por cabecera `ARTÍCULO` normalizada (sin
  acentos, soportando `Nº`/`°`/`:`); tratar serie anidada y COVID aparte.
- **#7 (chunking):** el "artículo" es la unidad natural; el tamaño base de
  chunk se puede calibrar contra la mediana por artículo (ver sección 4).
- **#9 (metadata):** cada chunk debería llevar `poliza`, `ramo`, `año`,
  `articulo`, `titulo_canonico` y `pagina` → permite filtrar por tipo de
  cláusula (cobertura, exclusiones, definiciones…).

## 7. Metodología

Segmentación por regex `ARTÍCULO Nº NN: TÍTULO` tolerante a variantes; cada
artículo = texto entre su cabecera y la siguiente. Títulos mapeados a claves
canónicas por keywords. Deep-dive del Artículo 2 en pólizas ramo 32 (salud).
Solo se versionan este reporte y las tablas de estructura (los PDFs no).

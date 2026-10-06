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
definiciones → … → cláusulas adicionales). Matriz de posiciones, **una columna
por código de depósito** (el corpus son 9 PDFs pero 10 códigos reales, y
`POL320130223` aparece tanto en su archivo como dentro de `POL320190074.pdf`; cada
columna muestra el primer sub-documento del código). Detalle por sub-documento:
`docs/eda/polizas_estructura.csv`.

| pos | POL120190177 | POL320130223 | POL320150503 | POL320160108 | POL320180100 | POL320190074 | POL320200071 | POL320200214 | POL320210063 | POL320210210 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | reglas | reglas | reglas | reglas | reglas | reglas | reglas | reglas | reglas | reglas |

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

Longitud por artículo (chars): min **90** · mediana **1106** · max **25420** (n=227)

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

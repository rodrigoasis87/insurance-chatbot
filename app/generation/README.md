# Módulo de Generación · Recombinación DEM (demo v0 · #36)

Este módulo implementa el motor de recombinación de pólizas estándar (código DEM) para la corredora de seguros, conforme a `docs/CONTRACTS.md` §4.1 y `docs/ONTOLOGIA.md` §8.

Permite ensamblar cláusulas canónicas de un molde base del catálogo regulatorio junto con las condiciones de un perfil de cliente sin datos personales identificables (PII), generando una propuesta técnica en formato JSON y un documento formal PDF rotulado como borrador no emitido.

---

## Estructura del Módulo

- `dem.py`: Lógica central del componente (validación de perfil, filtrado de artículos, recombinación condicional, armado de payload y renderizado PDF con PyMuPDF).
- `__init__.py`: Exportación de la API pública del módulo con resolución dinámica.
- `__main__.py`: Punto de entrada para ejecución modular por consola.

---

## Uso desde Python (Integración para Issue #16 / FastAPI)

Para cablear el endpoint `POST /policy-recombine`, se importa directamente la función `generar_dem`:

```python
from app.generation import generar_dem

# Perfil curado sin PII (vocabulario controlado de ONTOLOGIA.md §8)
perfil = {
    "edad": "30-40",
    "preexistencias": "sí",
    "deportes_riesgo": "no",
    "fonasa_isapre": "isapre",
    "embarazo": "no",
    "cronicas": "no",
    "colectivo": "no",
    "residencia": "chile",
}

# Ejecución de la recombinación
payload, pdf_path = generar_dem(
    molde="POL320200071",
    perfil=perfil,
    seq=1,  # Opcional: define correlativo DEM20260001
)

# payload: dict conforme a docs/CONTRACTS.md §4.1
# pdf_path: Path al archivo generado en data/generated/DEM20260001.pdf
```

---

## Uso desde Línea de Comandos (CLI)

El módulo se puede ejecutar directamente con el gestor `uv`:

```bash
uv run python -m app.generation.dem \
  --molde POL320200071 \
  --perfil '{"edad":"30-40","preexistencias":"sí","deportes_riesgo":"no","fonasa_isapre":"isapre","embarazo":"sí","cronicas":"no","colectivo":"no","residencia":"chile"}' \
  --seq 1 \
  --json
```

### Argumentos disponibles:

- `--molde` (str, requerido): Código de la póliza molde base (ej. `POL320200071`).
- `--perfil` (str, requerido): JSON string o ruta a archivo `.json` con el perfil curado.
- `--seq` (int, opcional): Número correlativo para el código DEM (ej. `1` produce `DEM20260001`).
- `--output-dir` (Path, opcional): Directorio de salida alternativo para el archivo PDF.
- `--articulos` (Path, opcional): Ruta a un archivo `.jsonl` alternativo de artículos.
- `--json` (flag): Imprime el payload estructurado completo en stdout.

---

## Contrato de Salida (docs/CONTRACTS.md §4.1)

El payload generado contiene los siguientes campos obligatorios:

```json
{
  "codigo": "DEM20260001",
  "molde_base": "POL320200071",
  "creado_en": "2026-10-11T10:00:00.000000",
  "perfil": { ... },
  "secciones": [
    {
      "nombre": "cobertura",
      "titulo": "COBERTURA",
      "pagina": 2,
      "perfil": "base",
      "texto": "..."
    },
    {
      "nombre": "exclusiones",
      "titulo": "EXCLUSIONES",
      "pagina": 5,
      "perfil": "preexistencias",
      "texto": "..."
    }
  ],
  "pdf_url": "/generated/DEM20260001.pdf",
  "aviso": "BORRADOR · no emitida · estándar de la corredora (código DEM); la aseguradora puede adoptarlo y depositarlo como POL."
}
```

---

## Reglas de Negocio y Diseño

1. **Vocabulario controlado sin PII:** El validador rechaza cualquier texto libre o datos identificatorios (RUT, nombres, direcciones). Solo procesa factores de rating predefinidos bajo la Ley 19.628.
2. **No persistencia de perfil:** El perfil no se registra en base de datos; vive únicamente en memoria durante la ejecución.
3. **No emisión contractual:** El código DEM es una propuesta técnica de la corredora, no una póliza emitida ni un código POL de la CMF.
4. **Trazabilidad estricta:** Cada cláusula del PDF y del JSON conserva su número de página del molde original.
5. **Directorio de salida:** Los archivos PDF se generan en `data/generated/`, ruta excluida en el `.gitignore`.

---

## Pruebas Unitarias

Para ejecutar la suite de pruebas del módulo:

```bash
uv run pytest tests/test_generation_dem.py -v
```

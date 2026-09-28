# Guía de Contribución y Normas del Equipo

Este documento define la **Definition of Done (DoD)**, la estrategia de ramas de Git y las convenciones de código para el desarrollo del proyecto **Insurance Policy Generation Chatbot**.

---

## 1. Definition of Done (DoD)

Un Issue o tarea se considera oficialmente **Done** (Terminada) únicamente cuando cumple con los siguientes criterios:

* **Código y Funcionalidad:**
  * El código cumple con los requerimientos específicos definidos en la descripción del Issue.
  * Fue ejecutado y probado localmente de forma exitosa (sin errores de ejecución ni sintaxis).
  * No se subieron credenciales, llaves API ni secretos al repositorio (se manejan vía `.env`).
  * Los archivos generados, temporales o descargados (PDFs, índices vectoriales locales) están ignorados en el `.gitignore`.
* **Pruebas y Calidad:**
  * Pasan las pruebas unitarias e integración con `pytest` (si aplica para la tarea).
  * El entorno es 100% reproducible usando el gestor `uv`.
* **Proceso de Git:**
  * El trabajo se realizó en una rama dedicada `feature/*`.
  * Se abrió un **Pull Request (PR)** hacia la rama principal (`main`).
  * El PR fue revisado y aprobado por el **Tech Lead** o al menos un integrante del equipo.
  * Se resolvieron todos los conflictos de integración antes de hacer el merge.
* **Documentación:**
  * Las funciones y módulos principales incluyen *docstrings* y *type hints*.
  * Se actualizó el `README.md` si la tarea agregó nuevas variables de entorno, endpoints o dependencias.

---

## 2. Estrategia de Ramificación (Git Flow)

Para mantener la rama principal siempre en estado ejecutable, utilizaremos el flujo de **Feature Branches**:

```text
main (Rama protegida / Producción)
 ├── feature/s3-downloader
 ├── feature/pdf-parsing-and-chunking
 ├── feature/qdrant-vector-store
 └── feature/fastapi-backend
```

## 3. Flujo de Trabajo Diario (Comandos Git y UV)

Para mantener la calidad del repositorio y evitar conflictos entre las distintas células, todo el equipo debe seguir este flujo de trabajo diario.

---

### A. Inicio de la jornada (Sincronización)
Antes de comenzar a trabajar o programar una nueva funcionalidad, actualizá tu rama `main` local y sincronizá las dependencias del proyecto:

```bash
# 1. Cambiar a main y traer los últimos cambios
git checkout main
git pull origin main

# 2. Sincronizar el entorno virtual de Python con uv
uv sync
```

### B. Iniciar una nueva tarea (Crear la rama)
Las ramas se crean a partir de las Issues asignadas en GitHub Projects.

Creá la rama en la interfaz de GitHub desde el panel derecho de la Issue (Create a branch).

Traé la rama a tu máquina local:

```bash
# Actualizar las referencias de ramas remotas
git fetch origin

# Moverte a la nueva rama
git checkout <nombre-de-la-rama>
```

Nota: Si creás la rama manualmente en local, asegurate de seguir la convención de nombres (ej. feature/dataset-eda, feature/chunking-benchmark).

### C. Desarrollo local y gestión de librerías
Agregar nuevas dependencias
Si tu tarea requiere una nueva librería de Python, no uses pip install directamente. Usá uv para que se registre automáticamente en el pyproject.toml y uv.lock:

```bash
uv add <nombre-de-la-libreria>
# Ejemplo: uv add duckduckgo-search
```

Guardar cambios (Commits frecuentes)
Realizá commits pequeños y descriptivos siguiendo la convención acordada:

feat(...): Nueva funcionalidad.

fix(...): Corrección de un error.

docs(...): Cambios en documentación.

chore(...): Tareas de mantenimiento o configuración.

```bash
# Ver estado de archivos
git status

# Agregar archivos al área de preparación
git add .

# Guardar commit
git commit -m "feat(tools): implement web search with duckduckgo"
```

### D. Mantener la rama actualizada con main
Si pasaron varios días o tus compañeros mergearon código a main, integrá esos cambios en tu rama para resolver conflictos de forma temprana:

```bash
# Traer e integrar cambios de main a tu rama actual
git fetch origin
git merge origin/main

# Re-sincronizar dependencias si hubo cambios en pyproject.toml
uv sync
```

### E. Finalizar tarea y abrir Pull Request (PR)
1. Subir tu rama a GitHub: 
```bash
git push -u origin <nombre-de-la-rama>
```

2. Abrir el PR en GitHub:

Ve al repositorio en GitHub y hacé clic en Compare & pull request.


### F. Post-Merge (Limpieza en local)
Una vez que tu PR fue aprobado y mergeado a main en GitHub:

```bash
# Volver a main y actualizar con tu trabajo ya integrado
git checkout main
git pull origin main

# Borrar la rama local que ya fue mergeada
git branch -d <nombre-de-la-rama>
```
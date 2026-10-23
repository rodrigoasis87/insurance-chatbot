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
  * El trabajo se realizó en una rama dedicada `feature/*` creada desde `develop`.
  * Se abrió un **Pull Request (PR)** hacia la rama de integración (`develop`).
  * El PR fue revisado y aprobado por el **Tech Lead** o al menos un integrante del equipo.
  * Se resolvieron todos los conflictos de integración antes de hacer el merge.
  * `main` solo se actualiza vía PR de integración `develop` → `main` (releases / demo-day).
* **Documentación:**
  * Las funciones y módulos principales incluyen *docstrings* y *type hints*.
  * Se actualizó el `README.md` si la tarea agregó nuevas variables de entorno, endpoints o dependencias.

---

## 2. Estrategia de Ramificación (Git Flow)

Para mantener la rama principal siempre en estado ejecutable, utilizamos un
flujo de **Git Flow simplificado** con `develop` como rama de integración:

```text
main (protegida · releases / demo-day, solo se actualiza vía PR desde develop)
 └── develop (integración · siempre ejecutable; las ramas feature nacen de aquí)
      ├── feature/issue-19-golden-set      # eval golden set              (app/rag)
      ├── feature/issue-20-suite-pytest    # suite pytest consolidada     (tests/)
      ├── feature/issue-22-demo-video      # demo + README de cierre      (docs/)
      └── ... nuevas ramas se crean desde cada Issue en GitHub Projects
```

> Nota: hasta octubre 2026 las ramas `feature/*` nacían de `main`. La rama
> `demo-integrada` fue renombrada a `develop` (misma historia, sin duplicados)
> y concentra todo el trabajo de demo (agente, API, UI, compose, generación DEM).

## 3. Flujo de Trabajo Diario (Comandos Git y UV)

Para mantener la calidad del repositorio y evitar conflictos entre las distintas células, todo el equipo debe seguir este flujo de trabajo diario.

---

### A. Inicio de la jornada (Sincronización)
Antes de comenzar a trabajar o programar una nueva funcionalidad, actualizá tu rama `develop` local y sincronizá las dependencias del proyecto:

```bash
# 1. Cambiar a develop y traer los últimos cambios
git checkout develop
git pull origin develop

# 2. Sincronizar el entorno virtual de Python con uv
uv sync
```

### B. Iniciar una nueva tarea (Crear la rama)
Las ramas se crean a partir de las Issues asignadas en GitHub Projects, **siempre desde `develop`** (cambiá la rama base en el panel de la Issue antes de usar "Create a branch", o creala manualmente):

```bash
# Actualizar las referencias de ramas remotas
git fetch origin

# Crear la rama de la issue desde develop
git checkout -b feature/issue-<N>-<nombre-corto> origin/develop
```

Nota: si creás la rama desde la interfaz de GitHub, asegurate de que la rama base sea `develop` y de seguir la convención de nombres (ej. `feature/issue-19-golden-set`).

### C. Desarrollo local y gestión de librerías

#### Agregar una nueva dependencia
Si tu tarea requiere una nueva librería de Python, no uses pip install directamente. Usá uv para que se registre automáticamente en el pyproject.toml y uv.lock:

```bash
uv add <nombre-de-la-libreria>
# Ejemplo: uv add duckduckgo-search
```

#### Guardar cambios (commits frecuentes)
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

### D. Mantener la rama actualizada con develop
Si pasaron varios días o tus compañeros integraron código a `develop`, traé esos cambios a tu rama para resolver conflictos de forma temprana:

```bash
# Traer e integrar cambios de develop a tu rama actual
git fetch origin
git merge origin/develop

# Re-sincronizar dependencias si hubo cambios en pyproject.toml
uv sync
```

### E. Finalizar tarea y abrir Pull Request (PR)

Antes de abrir el PR, asegurate de que tu rama esté al día con `develop`: `git merge origin/develop`. Si GitHub marca la rama como *"out-of-date"*, el merge del PR puede bloquearse (o quedar pendiente en *'Checking for the ability to merge...'*).

1. Subir tu rama a GitHub: 
```bash
git push -u origin <nombre-de-la-rama>
```

2. Abrir el PR en GitHub **con base en `develop`**:

Ve al repositorio en GitHub y hacé clic en Compare & pull request (verificá que el rama base sea `develop`, no `main`).


### F. Post-Merge (Limpieza en local)
Una vez que tu PR fue aprobado y mergeado a develop en GitHub:

```bash
# Volver a develop y actualizar con tu trabajo ya integrado
git checkout develop
git pull origin develop

# Borrar la rama local que ya fue mergeada
git branch -d <nombre-de-la-rama>
```

### G. Integración a main (solo Tech Lead)

`main` solo se actualiza vía un PR de `develop` → `main`, en hitos de release o antes del demo-day. Ese PR es el único punto donde se validan juntos todos los avances del equipo.

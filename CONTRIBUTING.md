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
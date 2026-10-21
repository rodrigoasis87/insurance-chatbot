"""Configuracion comun de la suite pytest (tests sin Docker, todo mockeado).

La suite NO debe exportar trazas a Langfuse: con ``LANGFUSE_ENABLED=true`` en
el ``.env`` local, cada test que toca el agente intenta enviar spans a un
hostname de Docker (``langfuse-web``) que no resuelve desde el host y ensucia
la salida con reintentos. Se desactiva antes de que la app lea su settings
(``load_dotenv`` no pisa variables ya presentes en el entorno).
"""

from __future__ import annotations

import os

os.environ.setdefault("LANGFUSE_ENABLED", "false")

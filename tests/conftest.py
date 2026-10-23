"""Fixtures compartidas de la suite.

Los tests asumen los defaults documentados del retrieval (``RETRIEVAL_MODE``
denso, #42). Como ``app.rag.config`` carga el ``.env`` local al importarse, un
``RETRIEVAL_MODE=hybrid`` de desarrollo cambiaria el modo y el hard gate de
toda la suite; aca se quitan esas variables para cada test. Los tests del modo
hibrido las fijan explicitamente con ``monkeypatch``.

La suite NO debe exportar trazas a Langfuse: con ``LANGFUSE_ENABLED=true`` en
el ``.env`` local, cada test que toca el agente intenta enviar spans a un
hostname de Docker (``langfuse-web``) que no resuelve desde el host y ensucia
la salida con reintentos. Se desactiva antes de que la app lea su settings
(``load_dotenv`` no pisa variables ya presentes en el entorno).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("LANGFUSE_ENABLED", "false")


@pytest.fixture(autouse=True)
def _retrieval_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("UMBRAL_SCORE_HYBRID", raising=False)
    yield

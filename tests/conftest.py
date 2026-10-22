"""Fixtures compartidas de la suite.

Los tests asumen los defaults documentados del retrieval (``RETRIEVAL_MODE``
denso, #42). Como ``app.rag.config`` carga el ``.env`` local al importarse, un
``RETRIEVAL_MODE=hybrid`` de desarrollo cambiaria el modo y el hard gate de
toda la suite; aca se quitan esas variables para cada test. Los tests del modo
hibrido las fijan explicitamente con ``monkeypatch``.
"""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _retrieval_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    monkeypatch.delenv("UMBRAL_SCORE_HYBRID", raising=False)
    yield

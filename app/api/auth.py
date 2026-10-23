"""Autenticación mínima del API por API key en header (Issue #44, CONTRACTS §4).

Los endpoints protegidos exigen el header ``X-API-Key`` igual a ``API_KEY`` del
``.env``. Si ``API_KEY`` está vacío el API corre en **modo dev sin auth** y lo
avisa en los logs. ``/health`` queda público (lo usan el smoke test y compose).

La key se lee en cada request con ``get_settings()`` (sin cache), igual que el
resto de la configuración, para que los tests puedan cambiarla con ``monkeypatch``.
"""

from __future__ import annotations

import logging
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.rag.config import get_settings

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"

# auto_error=False: la ausencia del header la resuelve ``require_api_key`` (401
# propio, o pase libre en modo dev). Registrarlo con ``Security`` agrega el
# esquema al OpenAPI, así Swagger (/docs) muestra el botón "Authorize".
api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key del despliegue (variable API_KEY del .env).",
)

MODO_DEV_AVISO = (
    "API_KEY vacío: el API corre en modo dev SIN autenticación. "
    "Definí API_KEY en el .env para proteger /chat, /chat/stream y /policy-recombine."
)


def auth_habilitada() -> bool:
    """``True`` si hay una ``API_KEY`` configurada (endpoints protegidos)."""
    return bool(get_settings().api_key)


def avisar_si_modo_dev() -> bool:
    """Loguea un warning si el API arranca sin ``API_KEY``.

    Returns:
        ``True`` si se emitió la advertencia (modo dev sin auth).
    """
    if auth_habilitada():
        return False
    logger.warning(MODO_DEV_AVISO)
    return True


def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    """Dependency de FastAPI: valida ``X-API-Key`` contra ``API_KEY``.

    Args:
        api_key: valor del header ``X-API-Key`` (``None`` si no viene).

    Raises:
        HTTPException: 401 si hay ``API_KEY`` configurada y el header falta o no
            coincide. La comparación es de tiempo constante.
    """
    esperada = get_settings().api_key
    if not esperada:
        return
    if not api_key or not secrets.compare_digest(
        api_key.encode("utf-8"), esperada.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"API key inválida o ausente (header {API_KEY_HEADER})",
            headers={"WWW-Authenticate": "APIKey"},
        )

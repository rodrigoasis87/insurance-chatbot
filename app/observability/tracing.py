"""Tracing de observabilidad en el hot path (Langfuse, opcional) (#48).

La observabilidad es **complementaria** a G1 (docs/EVAL.md): G1 evalua el
pipeline contra el golden set de forma batch y offline; Langfuse traza las
consultas **reales** de runtime (latencia, ruta, contexto usado, tokens).

Por defecto este modulo es un **noop**: no hace nada, no abre conexiones y no
agrega latencia. Solo se activa si ``LANGFUSE_ENABLED=true`` y hay
``LANGFUSE_PUBLIC_KEY`` + ``LANGFUSE_SECRET_KEY``.

Regla dura: **ningun error de observabilidad puede romper la consulta**. El
SDK de Langfuse atrapa sus propios errores, y este modulo envuelve ademas cada
span en un try/except que degrada a noop sin propagar la excepcion.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.rag.config import get_settings

logger = logging.getLogger(__name__)

# Nombres de los spans del pipeline (se ven como nodos en el trace de Langfuse).
SPAN_QUERY = "rag.query"
SPAN_RETRIEVE = "rag.retrieve"
SPAN_HARD_GATE = "rag.hard_gate"
SPAN_LLM = "rag.llm_generate"
SPAN_LLM_WEB = "rag.llm_generate_web"
SPAN_WEB = "rag.web_search"

# Tipos de observacion de Langfuse (segun la API v5).
TYPE_SPAN = "span"
TYPE_GENERATION = "generation"
TYPE_RETRIEVER = "retriever"
TYPE_TOOL = "tool"


class Span:
    """Envoltura delgada sobre una observacion de Langfuse (o sobre nada).

    ``update()`` nunca propaga excepciones: un fallo al reportar un span no
    puede tumbar la consulta que se esta trazando.
    """

    __slots__ = ("_obs",)

    def __init__(self, obs: Any | None = None) -> None:
        self._obs = obs

    @property
    def active(self) -> bool:
        """``True`` si el span esta conectado a un backend real."""
        return self._obs is not None

    def update(self, **kwargs: Any) -> None:
        """Actualiza la observacion (``output``, ``metadata``, ``level``...)."""
        if self._obs is None:
            return
        try:
            self._obs.update(**kwargs)
        except Exception:  # pragma: no cover - defensivo
            logger.debug("No se pudo actualizar el span de Langfuse", exc_info=True)


class Tracer:
    """Tracer noop: el modo por defecto (Langfuse no configurado)."""

    enabled: bool = False

    @contextmanager
    def span(
        self,
        name: str,
        *,
        as_type: str = TYPE_SPAN,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> Iterator[Span]:
        """Abre un span que no hace nada."""
        yield Span()

    def flush(self) -> None:
        """Vacia la cola de eventos (noop: no hay nada que vaciar)."""
        return None


class LangfuseTracer(Tracer):
    """Tracer que delega en el SDK de Langfuse."""

    enabled = True

    def __init__(self, client: Any) -> None:
        self._client = client

    @contextmanager
    def _propaga(self, session_id: str | None) -> Iterator[None]:
        """Propaga el ``session_id`` a los spans hijos (agrupa la conversacion).

        Si el SDK no puede propagar los atributos, la consulta sigue igual: solo
        se pierde el agrupamiento por sesion.
        """
        if not session_id:
            yield
            return
        ctx = self._entra_propagate(session_id)
        if ctx is None:
            yield
            return
        try:
            yield
        except BaseException as exc:
            try:
                ctx.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:  # pragma: no cover - defensivo
                pass
            raise
        else:
            try:
                ctx.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensivo
                logger.debug(
                    "No se pudo cerrar la propagacion de atributos", exc_info=True
                )

    def _entra_propagate(self, session_id: str) -> Any | None:
        """Entra al contexto de propagacion; ``None`` si el SDK no lo permite."""
        ctx = None
        try:
            from langfuse import propagate_attributes

            ctx = propagate_attributes(session_id=session_id)
            ctx.__enter__()
            return ctx
        except Exception:
            logger.debug(
                "No se pudo propagar el session_id a Langfuse", exc_info=True
            )
            if ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:  # pragma: no cover - defensivo
                    pass
            return None

    @contextmanager
    def span(
        self,
        name: str,
        *,
        as_type: str = TYPE_SPAN,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> Iterator[Span]:
        """Abre una observacion de Langfuse; degrada a noop si el SDK falla."""
        manager = None
        obs = None
        try:
            manager = self._client.start_as_current_observation(
                name=name, as_type=as_type, **kwargs
            )
            obs = manager.__enter__()
        except Exception:
            logger.warning(
                "Langfuse no pudo abrir el span '%s'; la consulta sigue sin traza",
                name,
                exc_info=True,
            )
            yield Span()
            return

        try:
            with self._propaga(session_id):
                yield Span(obs)
        except BaseException as exc:
            # El cuerpo del span fallo: se lo informamos al SDK para que marque
            # el status como ERROR, y propagamos la excepcion original.
            try:
                manager.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:  # pragma: no cover - defensivo
                pass
            raise
        else:
            try:
                manager.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensivo
                logger.debug("No se pudo cerrar el span de Langfuse", exc_info=True)

    def flush(self) -> None:
        """Fuerza el envio de los traces pendientes (el SDK los manda en bg)."""
        try:
            self._client.flush()
        except Exception:  # pragma: no cover - defensivo
            logger.debug("No se pudo hacer flush de Langfuse", exc_info=True)


def observability_enabled() -> bool:
    """``True`` si Langfuse esta habilitado **y** tiene credenciales.

    Es la unica condicion para activar el tracing: sin keys el modulo queda
    en noop y no se importa el SDK.
    """
    settings = get_settings()
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


# Cliente de Langfuse cacheado: el SDK comparte los recursos por public_key,
# pero evita recrear el wrapper en cada consulta.
_client_cache: tuple[tuple[str, str, str, str], Any] | None = None


def _build_client(
    public_key: str, secret_key: str, base_url: str, environment: str
) -> Any:
    """Devuelve el cliente de Langfuse para la configuracion dada (cacheado)."""
    global _client_cache
    config = (public_key, secret_key, base_url, environment)
    if _client_cache is not None and _client_cache[0] == config:
        return _client_cache[1]
    from langfuse import Langfuse

    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        environment=environment,
    )
    _client_cache = (config, client)
    return client


def reset_client_cache() -> None:
    """Olvida el cliente cacheado (tests)."""
    global _client_cache
    _client_cache = None


def get_tracer() -> Tracer:
    """Devuelve el tracer activo: Langfuse si esta configurado, noop si no.

    No cachea la decision: la configuracion se relee en cada llamada (igual que
    ``get_settings()``) para que los tests puedan cambiar el ``.env`` con
    ``monkeypatch`` sin efectos colaterales. El cliente de Langfuse si se
    cachea (el SDK comparte los recursos por ``public_key``).
    """
    if not observability_enabled():
        return Tracer()

    settings = get_settings()
    try:
        client = _build_client(
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
            settings.langfuse_base_url,
            settings.langfuse_environment,
        )
    except Exception:
        logger.warning(
            "No se pudo inicializar el cliente de Langfuse; se sigue sin traza",
            exc_info=True,
        )
        return Tracer()
    return LangfuseTracer(client)

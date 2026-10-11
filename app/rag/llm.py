"""Abstraccion del LLM de chat: Ollama (local, default) y cloud opt-in (ADR-006).

El proveedor se elige con ``LLM_PROVIDER`` en el ``.env`` (default: Ollama,
ADR-001) o se fuerza por parametro en cada llamada (demo ambas modalidades).
El resto de la app depende de ``BaseChatModel`` (``invoke``, ``stream``,
``bind_tools``) y nunca importa una clase de proveedor directamente:

    resp = query(question, llm=get_llm(provider="google"))
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from app.rag.config import SUPPORTED_LLM_PROVIDERS, get_settings


def get_llm(provider: str | None = None, *, temperature: float = 0.0) -> BaseChatModel:
    """Instancia el modelo de chat segun ``LLM_PROVIDER``.

    * ``ollama`` -> ``ChatOllama`` con ``OLLAMA_CHAT_MODEL`` (``qwen3:4b-instruct``).
    * ``openai`` -> ``ChatOpenAI`` con ``OPENAI_CHAT_MODEL`` (``gpt-4o-mini``).
    * ``anthropic`` -> ``ChatAnthropic`` con ``ANTHROPIC_CHAT_MODEL``
      (``claude-haiku-4-5-20251001``).
    * ``google`` -> ``ChatGoogleGenerativeAI`` con ``GOOGLE_CHAT_MODEL``
      (``gemini-3.5-flash-lite``).

    Args:
        provider: fuerza un proveedor e ignora el ``.env`` (Demo: el selector
            de la UI pasa "ollama" o "google" por peticion).
        temperature: temperatura de muestreo. 0 = respuestas deterministas.

    Raises:
        ValueError: si el proveedor no esta soportado o falta su API key.
    """
    settings = get_settings()
    selected = (provider or settings.llm_provider).strip().lower()

    if selected == "ollama":
        return ChatOllama(
            model=settings.ollama_chat_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
            # Apaga el razonamiento en modelos hibridos (p. ej. qwen3 original).
            # No alcanza con modelos solo-thinking como "qwen3:4b": por eso el
            # default es "qwen3:4b-instruct".
            reasoning=False,
        )

    if selected == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER=openai requiere OPENAI_API_KEY en el archivo .env"
            )
        # Import diferido: el camino local no necesita cargar el SDK de OpenAI.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.openai_chat_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
        )

    if selected == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError(
                "LLM_PROVIDER=anthropic requiere ANTHROPIC_API_KEY en el archivo .env"
            )
        # Import diferido: solo se carga el SDK de Anthropic si se usa.
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_chat_model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
            # Tope de la respuesta: alcanza para una respuesta RAG con citas y
            # evita gastar creditos en respuestas largas (el default es 64000).
            max_tokens=1024,
        )

    if selected == "google":
        if not settings.google_api_key:
            raise ValueError(
                "LLM_PROVIDER=google requiere GOOGLE_API_KEY en el archivo .env"
            )
        # Import diferido: solo se carga el SDK de Google si se usa.
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.google_chat_model,
            api_key=settings.google_api_key,
            temperature=temperature,
            # Tope de la respuesta: alcanza para una respuesta RAG con citas.
            max_tokens=1024,
            retries=2,
        )

    raise ValueError(
        f"LLM_PROVIDER no soportado: {selected!r}. "
        f"Opciones validas: {', '.join(SUPPORTED_LLM_PROVIDERS)}"
    )

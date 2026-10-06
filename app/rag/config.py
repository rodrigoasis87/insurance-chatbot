"""Configuracion central del motor RAG, leida desde el archivo ``.env``.

Es el unico lugar que conoce los nombres de las variables de entorno y sus
valores por defecto (ADR-001 y docs/CONTRACTS.md). El resto de los modulos
llama a ``get_settings()``.

Los valores se leen en cada llamada (sin cache) para que los tests puedan
cambiar variables con ``monkeypatch`` sin efectos colaterales.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.paths import PROJECT_ROOT

# No pisa variables ya definidas en el entorno (util en Docker y en CI).
load_dotenv(PROJECT_ROOT / ".env")

SUPPORTED_LLM_PROVIDERS = ("ollama", "openai", "anthropic")

# Valores por defecto: ADR-001 + docs/CONTRACTS.md seccion 2.
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# "qwen3:4b" en Ollama es la variante thinking-2507: siempre razona antes de
# responder y no se puede apagar. La variante instruct (mismo tamano) no.
DEFAULT_OLLAMA_CHAT_MODEL = "qwen3:4b-instruct"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4o-mini"
# El mas rapido y barato de Claude; para mas calidad: "claude-sonnet-5-5".
DEFAULT_ANTHROPIC_CHAT_MODEL = "claude-haiku-4-5-20251001"
# Multilingue (nomic-embed-text es solo ingles y fallo el test en espanol).
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "polizas"


def _env(name: str, default: str) -> str:
    """Devuelve la variable de entorno sin espacios, o ``default`` si esta vacia."""
    value = os.getenv(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    """Valores de configuracion inmutables del proyecto."""

    llm_provider: str
    ollama_base_url: str
    ollama_chat_model: str
    openai_api_key: str
    openai_chat_model: str
    anthropic_api_key: str
    anthropic_chat_model: str
    embedding_model: str
    qdrant_url: str
    qdrant_collection: str


def get_settings() -> Settings:
    """Construye ``Settings`` a partir de las variables de entorno actuales."""
    return Settings(
        llm_provider=_env("LLM_PROVIDER", DEFAULT_LLM_PROVIDER).lower(),
        ollama_base_url=_env("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        ollama_chat_model=_env("OLLAMA_CHAT_MODEL", DEFAULT_OLLAMA_CHAT_MODEL),
        openai_api_key=_env("OPENAI_API_KEY", ""),
        openai_chat_model=_env("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_CHAT_MODEL),
        anthropic_api_key=_env("ANTHROPIC_API_KEY", ""),
        anthropic_chat_model=_env("ANTHROPIC_CHAT_MODEL", DEFAULT_ANTHROPIC_CHAT_MODEL),
        embedding_model=_env("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        qdrant_url=_env("QDRANT_URL", DEFAULT_QDRANT_URL),
        qdrant_collection=_env("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION),
    )

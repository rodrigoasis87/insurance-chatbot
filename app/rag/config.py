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

SUPPORTED_LLM_PROVIDERS = ("ollama", "openai", "anthropic", "google")

# Valores por defecto: ADR-001 + docs/CONTRACTS.md seccion 2.
DEFAULT_LLM_PROVIDER = "ollama"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# "qwen3:4b" en Ollama es la variante thinking-2507: siempre razona antes de
# responder y no se puede apagar. La variante instruct (mismo tamano) no.
DEFAULT_OLLAMA_CHAT_MODEL = "qwen3:4b-instruct"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4o-mini"
# El mas rapido y barato de Claude; para mas calidad: "claude-sonnet-5-5".
DEFAULT_ANTHROPIC_CHAT_MODEL = "claude-haiku-4-5-20251001"
# Google (opt-in post-MVP, ADR-006): el default del repo sigue siendo Ollama
# (ADR-001). Gemini 3 Flash Lite: ultra-low latency y el mas barato de la linea.
DEFAULT_GOOGLE_CHAT_MODEL = "gemini-3.5-flash-lite"
# Multilingue (nomic-embed-text es solo ingles y fallo el test en espanol).
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_QDRANT_COLLECTION = "polizas"
# Hard gate de retrieval (CONTRACTS §2): chunks con score menor a este valor
# jamás llegan al prompt. Empírico sobre la coleccion real; ver
# docs/umbral_score.md (se re-mide si cambia el modelo de embeddings).
DEFAULT_UMBRAL_SCORE = 0.60

# Observabilidad en runtime (Langfuse, #48). Es OPCIONAL: sin estas variables
# el modulo app.observability queda en modo noop (no toca la red).
# LANGFUSE_BASE_URL apunta al Langfuse self-host de docker-compose.observability.yml.
DEFAULT_LANGFUSE_BASE_URL = "http://localhost:3000"
DEFAULT_LANGFUSE_ENVIRONMENT = "local"

# Autenticacion minima del API (#44): API_KEY vacio = modo dev sin auth.
# No hay default: la key la define cada despliegue en su .env.
DEFAULT_API_KEY = ""


def _env(name: str, default: str) -> str:
    """Devuelve la variable de entorno sin espacios, o ``default`` si esta vacia."""
    value = os.getenv(name, "").strip()
    return value or default


def _env_bool(name: str, default: bool = False) -> bool:
    """Interpreta una variable de entorno como booleano ("1/true/yes/on")."""
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


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
    google_api_key: str
    google_chat_model: str
    embedding_model: str
    qdrant_url: str
    qdrant_collection: str
    umbral_score: float
    langfuse_enabled: bool
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str
    langfuse_environment: str
    api_key: str


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
        google_api_key=_env("GOOGLE_API_KEY", ""),
        google_chat_model=_env("GOOGLE_CHAT_MODEL", DEFAULT_GOOGLE_CHAT_MODEL),
        embedding_model=_env("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        qdrant_url=_env("QDRANT_URL", DEFAULT_QDRANT_URL),
        qdrant_collection=_env("QDRANT_COLLECTION", DEFAULT_QDRANT_COLLECTION),
        umbral_score=float(_env("UMBRAL_SCORE", str(DEFAULT_UMBRAL_SCORE))),
        langfuse_enabled=_env_bool("LANGFUSE_ENABLED"),
        langfuse_public_key=_env("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=_env("LANGFUSE_SECRET_KEY", ""),
        langfuse_base_url=_env("LANGFUSE_BASE_URL", DEFAULT_LANGFUSE_BASE_URL),
        langfuse_environment=_env("LANGFUSE_ENVIRONMENT", DEFAULT_LANGFUSE_ENVIRONMENT),
        api_key=_env("API_KEY", DEFAULT_API_KEY),
    )

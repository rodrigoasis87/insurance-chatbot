"""Tests unitarios de get_llm (sin red: solo instancian los clientes)."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.rag.llm import get_llm

ENV_VARS = (
    "LLM_PROVIDER",
    "OLLAMA_BASE_URL",
    "OLLAMA_CHAT_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_CHAT_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_CHAT_MODEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aisla los tests de lo que tenga el .env de cada desarrollador."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_default_is_ollama_qwen3_without_thinking() -> None:
    llm = get_llm()
    assert isinstance(llm, ChatOllama)
    assert llm.model == "qwen3:4b-instruct"
    assert llm.reasoning is False


def test_switch_to_openai_changing_only_llm_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # ya presente en el .env
    monkeypatch.setenv("LLM_PROVIDER", "openai")  # la unica variable que cambia
    llm = get_llm()
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4o-mini"


def test_provider_value_ignores_case_and_spaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "  Ollama ")
    assert isinstance(get_llm(), ChatOllama)


def test_model_name_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen3.5:4b")
    assert get_llm().model == "qwen3.5:4b"


def test_openai_without_api_key_fails_early(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_llm()


def test_unknown_provider_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(ValueError, match="no soportado"):
        get_llm()


def test_switch_to_anthropic_changing_only_llm_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # ya presente en el .env
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    llm = get_llm()
    assert isinstance(llm, ChatAnthropic)
    assert llm.model == "claude-haiku-4-5-20251001"
    assert llm.max_tokens == 1024


def test_anthropic_without_api_key_fails_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        get_llm()

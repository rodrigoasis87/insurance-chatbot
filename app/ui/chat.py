"""Interfaz de chat para la demo (Issue #18, CONTRACTS §4).

Correr local:      uv run chainlit run app/ui/chat.py
Desde Docker:      API_URL=http://api:8000 (compone dentro de docker compose)

Consume el API HTTP (#16): POST /chat/stream (SSE) por defecto; la lógica RAG
vive en ``app/rag/query.py`` y la expone el API (CONTRACTS §4). El selector
lateral elige el LLM por petición (demo ambas modalidades, ADR-006): el valor
viaja en el body (``provider``) sin reiniciar nada.
"""

import json
import os

import chainlit as cl
import httpx
from chainlit.input_widget import Select

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

AMBIENTE = """Asistente documental sobre el Depósito de Pólizas de la CMF.
Respondo SOLO con citas de pólizas del corpus o fuentes web de mercado.
Preguntas útiles: cobertura, exclusiones, plazos de denuncia, obligaciones.
El selector **Modelo** (panel derecho) cambia el LLM en vivo: `ollama` (local)
o `google` (Gemini por API key, demo)."""

DEFAULT_PROVIDER = "ollama"


def _render_fuentes(sources: list[dict]) -> str:
    if not sources:
        return ""
    partes = ["\n**Fuentes:**"]
    for s in sources:
        if s["origen"] == "poliza":
            titulo = f" · {s['titulo']}" if s.get("titulo") else ""
            partes.append(
                f"- [póliza] `{s['poliza']}` · Art. {s['articulo']} · "
                f"pág. {s.get('pagina', '-')}{titulo}"
            )
        else:
            partes.append(f"- [web] {s.get('titulo')} — {s['url']}")
    return "\n".join(partes)


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("provider", DEFAULT_PROVIDER)
    await cl.ChatSettings(
        inputs=[
            Select(
                id="provider",
                label="Modelo (demo)",
                values=["ollama", "openai", "anthropic", "google"],
                initial_value=DEFAULT_PROVIDER,
                description="ollama: local (ADR-001) · google: Gemini por API key "
                "(ADR-006, la consulta sale del sistema)",
            )
        ]
    ).send()
    await cl.Message(content=AMBIENTE, author="QuePlan").send()


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    cl.user_session.set("provider", settings.get("provider", DEFAULT_PROVIDER))


@cl.on_message
async def on_message(message: cl.Message) -> None:
    pregunta = message.content.strip()
    if not pregunta:
        await cl.Message(content="Escribí una pregunta sobre las pólizas.").send()
        return

    provider = cl.user_session.get("provider", DEFAULT_PROVIDER)
    msg = cl.Message(content="")
    texto: list[str] = []
    fuentes: list[dict] = []

    try:
        # Consumo SSE del endpoint /chat/stream (ADR-006): tokens en vivo y
        # fuentes al final. Si el API no soporta el stream, cae a /chat.
        async with httpx.AsyncClient(timeout=180) as http:
            async with http.stream(
                "POST",
                f"{API_URL}/chat/stream",
                json={"question": pregunta, "provider": provider},
            ) as resp:
                if resp.status_code == 400:
                    cuerpo = await resp.aread()
                    detalle = json.loads(cuerpo or b"{}").get(
                        "detail", "provider inválido"
                    )
                    await cl.Message(content=f"Error: {detalle}").send()
                    return
                resp.raise_for_status()
                async for linea in resp.aiter_lines():
                    if not linea.startswith("data: "):
                        continue
                    ev = json.loads(linea[6:])
                    if ev["type"] == "token":
                        texto.append(ev["text"])
                        await msg.stream_token(ev["text"])
                    elif ev["type"] == "sources":
                        fuentes = ev["sources"]
                    elif ev["type"] == "error":
                        texto.append(f"\n\nError: {ev.get('message')}")
                        break
                    elif ev["type"] == "done":
                        break
        msg.content = "".join(texto) + _render_fuentes(fuentes)
        await msg.update()
    except Exception as exc:  # la UI nunca debe caer por un error interno
        await cl.Message(
            content=f"Ocurrió un error interno: {type(exc).__name__} ({exc}). "
            "¿El API está levantado? Reintentá o ajustá la pregunta."
        ).send()
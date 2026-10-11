"""Interfaz de chat para la demo (Issue #18, CONTRACTS §4).

Correr local:      uv run chainlit run app/ui/chat.py
Desde Docker:      API_URL=http://api:8000 (compone dentro de docker compose)

Consume el API HTTP (#16) por POST /chat; la logica RAG vive en
``app/rag/query.py`` y el API la expone (CONTRACTS §4: "#18 consume #16,
no #17 directo").
"""

import os

import chainlit as cl
import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

AMBIENTE = """Asistente documental sobre el Depósito de Pólizas de la CMF.
Respondo SOLO con citas de pólizas del corpus o fuentes web de mercado.
Preguntas útiles: cobertura, exclusiones, plazos de denuncia, obligaciones."""


def _render(respuesta: dict) -> str:
    partes = [respuesta["answer"]]
    if respuesta["sources"]:
        partes.append("\n**Fuentes:**")
        for s in respuesta["sources"]:
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
    await cl.Message(content=AMBIENTE, author="QuePlan").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    if not message.content.strip():
        await cl.Message(content="Escribí una pregunta sobre las pólizas.").send()
        return
    try:
        async with httpx.AsyncClient(timeout=180) as http:
            resp = await http.post(
                f"{API_URL}/chat", json={"question": message.content.strip()}
            )
            resp.raise_for_status()
            respuesta = resp.json()
        await cl.Message(content=_render(respuesta)).send()
    except Exception as exc:  # la UI nunca debe caer por un error interno
        await cl.Message(
            content=f"Ocurrió un error interno: {type(exc).__name__} ({exc}). "
            "¿El API está levantado? Reintentá o ajustá la pregunta."
        ).send()
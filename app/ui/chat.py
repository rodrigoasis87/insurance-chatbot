"""Interfaz de chat para la demo (Issue #18, CONTRACTS §4.1 demo v0).

Correr con:  uv run chainlit run app/ui/chat.py

Consume ``app/rag/query.query()`` (Issue #17) directamente; cuando exista el
API (#16) migrará a HTTP.
"""

import chainlit as cl

from app.rag.query import query

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
        respuesta = await cl.make_async(query)(message.content.strip())
        await cl.Message(content=_render(respuesta)).send()
    except Exception as exc:  # la UI nunca debe caer por un error interno
        await cl.Message(
            content=f"Ocurrió un error interno: {type(exc).__name__} ({exc}). "
            "Reintentá o ajustá la pregunta."
        ).send()
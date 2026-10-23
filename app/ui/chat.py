"""Interfaz de chat para la demo (Issue #18, CONTRACTS §4).

Correr local:      uv run chainlit run app/ui/chat.py
Desde Docker:      API_URL=http://api:8000 (compone dentro de docker compose)

Auth (#44): si ``API_KEY`` está definida (el ``.env`` lo carga Chainlit; en
compose llega por ``environment``) cada request al API manda ``X-API-Key``.

Login: la UI pide usuario y contraseña con la pantalla de login de Chainlit
(``password_auth_callback``). Credenciales por ``UI_USERNAME``/``UI_PASSWORD``
(default ``admin``/``admin``, demo); Chainlit exige ``CHAINLIT_AUTH_SECRET``
para firmar la sesión (``uv run chainlit create-secret``).

Consume el API HTTP (#16): POST /chat/stream (SSE) por defecto; la lógica RAG
vive en ``app/rag/query.py`` y la expone el API (CONTRACTS §4). El selector
lateral elige el LLM por petición (demo ambas modalidades, ADR-006): el valor
viaja en el body (``provider``) sin reiniciar nada.
"""

import hmac
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

API_KEY_HEADER = "X-API-Key"

ERROR_401 = (
    "Error: el API rechazó la API key (401). Revisá que `API_KEY` de la UI "
    "coincida con la del API."
)


DEFAULT_UI_USERNAME = "admin"
DEFAULT_UI_PASSWORD = "admin"


def _ui_credentials() -> tuple[str, str]:
    """Usuario y contraseña del login (``UI_USERNAME``/``UI_PASSWORD``).

    Vacío o ausente cae al default de la demo. Se lee en cada login para tomar
    cambios de entorno sin reimportar el módulo.
    """
    usuario = os.getenv("UI_USERNAME", "").strip() or DEFAULT_UI_USERNAME
    password = os.getenv("UI_PASSWORD", "") or DEFAULT_UI_PASSWORD
    return usuario, password


def _coincide(recibido: str, esperado: str) -> bool:
    """Comparación en tiempo constante (no filtra el largo del prefijo correcto)."""
    return hmac.compare_digest(recibido.encode(), esperado.encode())


@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    """Valida el login; ``None`` hace que Chainlit muestre credenciales inválidas."""
    usuario, esperado = _ui_credentials()
    # Se evalúan ambas comparaciones siempre (sin cortocircuito) para no revelar
    # por tiempo si el usuario existe.
    usuario_ok = _coincide(username.strip(), usuario)
    password_ok = _coincide(password, esperado)
    if usuario_ok and password_ok:
        return cl.User(identifier=usuario, metadata={"role": "admin"})
    return None


def _auth_headers() -> dict[str, str]:
    """Header ``X-API-Key`` con la ``API_KEY`` del entorno (vacío = modo dev).

    Se lee en cada request para tomar cambios de entorno sin reimportar el módulo.
    """
    api_key = os.getenv("API_KEY", "").strip()
    return {API_KEY_HEADER: api_key} if api_key else {}


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
    # Id de sesion del navegador: agrupa los traces de la misma conversacion en
    # Langfuse (opcional, el API lo ignora si Langfuse no esta configurado).
    session_id = cl.user_session.get("id")
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
                json={
                    "question": pregunta,
                    "provider": provider,
                    "session_id": session_id,
                },
                headers=_auth_headers(),
            ) as resp:
                if resp.status_code == 401:
                    await cl.Message(content=ERROR_401).send()
                    return
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
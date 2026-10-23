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

Generación DEM (#58): el panel derecho configura molde + perfil curado (sin
PII) y el botón "Generar borrador DEM" llama a ``POST /policy-recombine``
(CONTRACTS §4.1). El PDF se sirve vía ``API_PUBLIC_URL`` (el navegador no
alcanza ``API_URL=http://api:8000``, que es interno a docker).
"""

import hmac
import json
import os
import sys
from pathlib import Path

import chainlit as cl
import httpx
from chainlit.input_widget import Select

# Chainlit carga este módulo con ``spec_from_file_location`` y solo agrega su
# propio directorio (app/ui) a ``sys.path``, no la raíz del proyecto. Como el
# módulo importa ``app.ui.dem_form`` (y este ``app.generation``), insertamos la
# raíz para que el paquete ``app`` sea importable en Docker y en dev local.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.ui.dem_form import (
    MOLDE_DEFAULT,
    build_dem_body,
    dem_pdf_name,
    opciones_perfil,
    perfil_default,
    public_pdf_url,
    render_dem_result,
)

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

# URL del API alcanzable desde el navegador (para abrir el PDF generado).
API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")

AMBIENTE = """Asistente documental sobre el Depósito de Pólizas de la CMF.
Respondo SOLO con citas de pólizas del corpus o fuentes web de mercado.
Preguntas útiles: cobertura, exclusiones, plazos de denuncia, obligaciones.
El selector **Modelo** (panel derecho) cambia el LLM en vivo: `ollama` (local)
o `google` (Gemini por API key, demo).

Para armar un borrador **DEM**: configurá molde y perfil en el panel derecho y
presioná el botón **Generar borrador DEM**."""

DEFAULT_PROVIDER = "ollama"

DEM_ACTION = "generar_dem"

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


async def _fetch_moldes() -> list[dict]:
    """Moldes disponibles desde ``GET /policies`` (público); ``[]`` si falla."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(f"{API_URL}/policies")
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return []


def _moldes_items(moldes: list[dict]) -> dict[str, str]:
    """``{label -> código}`` para el Select de molde; fallback al molde demo."""
    items: dict[str, str] = {}
    for m in moldes:
        codigo = m.get("poliza")
        if not codigo:
            continue
        extras = " · ".join(x for x in (m.get("ramo"), m.get("año")) if x)
        label = f"{codigo} ({extras})" if extras else codigo
        items[label] = codigo
    return items or {MOLDE_DEFAULT: MOLDE_DEFAULT}


def _molde_inicial(moldes: list[dict]) -> str:
    """Molde inicial del Select: el demo si está disponible, si no el primero."""
    codigos = [m.get("poliza") for m in moldes if m.get("poliza")]
    if not codigos or MOLDE_DEFAULT in codigos:
        return MOLDE_DEFAULT
    return codigos[0]


def _dem_settings_inputs(moldes: list[dict]) -> list:
    """Inputs del panel derecho: modelo + molde + 8 campos del perfil."""
    inputs = [
        Select(
            id="provider",
            label="Modelo (demo)",
            values=["ollama", "openai", "anthropic", "google"],
            initial_value=DEFAULT_PROVIDER,
            description="ollama: local (ADR-001) · google: Gemini por API key "
            "(ADR-006, la consulta sale del sistema)",
        ),
        Select(
            id="dem_molde",
            label="Molde base (DEM)",
            items=_moldes_items(moldes),
            initial_value=_molde_inicial(moldes),
            description="Póliza molde del catálogo (GET /policies).",
        ),
    ]
    for campo, label, opciones in opciones_perfil():
        inputs.append(
            Select(
                id=f"dem_{campo}",
                label=label,
                values=opciones,
                initial_value=perfil_default()[campo],
                description="Factor de rating curado, sin PII (ONTOLOGIA §8).",
            )
        )
    return inputs


def _detalle_error(resp: httpx.Response) -> str:
    """Extrae el ``detail`` del error del API (string o lista de pydantic)."""
    try:
        cuerpo = resp.json()
    except Exception:
        return resp.text.strip() or f"status {resp.status_code}"
    detalle = cuerpo.get("detail", cuerpo)
    if isinstance(detalle, list):
        partes = [str(d.get("msg", d)) for d in detalle if isinstance(d, dict)]
        return ", ".join(partes) if partes else "validación"
    return str(detalle)


@cl.on_chat_start
async def on_chat_start() -> None:
    moldes = await _fetch_moldes()
    cl.user_session.set("provider", DEFAULT_PROVIDER)
    cl.user_session.set("dem_molde", _molde_inicial(moldes))
    cl.user_session.set("dem_perfil", perfil_default())
    await cl.ChatSettings(inputs=_dem_settings_inputs(moldes)).send()
    await cl.Message(
        content=AMBIENTE,
        author="QuePlan",
        actions=[
            cl.Action(
                name=DEM_ACTION,
                label="Generar borrador DEM",
                description="Molde + perfil (panel derecho) → borrador DEM (CONTRACTS §4.1).",
            )
        ],
    ).send()


@cl.on_settings_update
async def on_settings_update(settings: dict) -> None:
    cl.user_session.set("provider", settings.get("provider", DEFAULT_PROVIDER))
    cl.user_session.set("dem_molde", settings.get("dem_molde", MOLDE_DEFAULT))
    perfil = perfil_default()
    for campo, _, _ in opciones_perfil():
        clave = f"dem_{campo}"
        if clave in settings:
            perfil[campo] = settings[clave]
    cl.user_session.set("dem_perfil", perfil)


@cl.action_callback(DEM_ACTION)
async def on_generar_dem(action: cl.Action) -> None:
    molde = cl.user_session.get("dem_molde", MOLDE_DEFAULT)
    perfil = cl.user_session.get("dem_perfil", perfil_default())
    try:
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.post(
                f"{API_URL}/policy-recombine",
                json=build_dem_body(molde, perfil),
                headers=_auth_headers(),
            )
        if resp.status_code == 401:
            await cl.Message(content=ERROR_401).send()
            return
        if resp.status_code in (400, 404, 422):
            await cl.Message(
                content=f"Error al generar el DEM: {_detalle_error(resp)}"
            ).send()
            return
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # la UI nunca debe caer por un error interno
        await cl.Message(
            content=f"Ocurrió un error al generar el DEM: {type(exc).__name__} "
            f"({exc}). ¿El API está levantado?"
        ).send()
        return

    pdf_url = public_pdf_url(API_PUBLIC_URL, payload.get("pdf_url", ""))
    await cl.Message(
        content=render_dem_result(payload),
        elements=[
            cl.Pdf(name=dem_pdf_name(payload), url=pdf_url, display="inline")
        ],
    ).send()


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
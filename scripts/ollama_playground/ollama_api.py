"""Playground para probar modelos de Ollama a mano (latencia, razonamiento, prompts).

Uso (con el stack de docker compose levantado):
    uv run python scripts/ollama_playground/ollama_api.py

- http://localhost:8000       -> chat de prueba con cronómetro y métricas
- http://localhost:8000/docs  -> endpoints /health, /chat y /chat/stream

Variables opcionales: OLLAMA_URL (default http://localhost:11434) y OLLAMA_MODEL (default qwen3:4b).
"""

import json
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")

app = FastAPI(title="Prueba Ollama")


class ChatRequest(BaseModel):
    message: str
    model: str = DEFAULT_MODEL
    system: str | None = None
    think: bool = False
    temperature: float = 0.7


def build_payload(req: ChatRequest, stream: bool) -> dict:
    messages = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    # Qwen3 soft switch: algunas versiones del modelo ignoran el parámetro `think`
    content = req.message if req.think else f"{req.message} /no_think"
    messages.append({"role": "user", "content": content})
    return {
        "model": req.model,
        "messages": messages,
        "think": req.think,
        "stream": stream,
        "options": {"temperature": req.temperature},
    }


def split_think(content: str) -> tuple[str, str | None]:
    """Separa el bloque <think>...</think> que el modelo mete dentro del contenido."""
    if "</think>" not in content:
        return content.strip(), None
    thinking, answer = content.split("</think>", 1)
    thinking = thinking.replace("<think>", "").strip()
    return answer.strip(), thinking or None


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=10) as client:
        tags = (await client.get(f"{OLLAMA_URL}/api/tags")).json()
        ps = (await client.get(f"{OLLAMA_URL}/api/ps")).json()
    loaded = [
        {"model": m["name"], "vram_gb": round(m.get("size_vram", 0) / 1e9, 2),
         "total_gb": round(m.get("size", 0) / 1e9, 2)}
        for m in ps.get("models", [])
    ]
    return {"ollama": OLLAMA_URL, "available": [m["name"] for m in tags["models"]], "loaded": loaded}


@app.post("/chat")
async def chat(req: ChatRequest):
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=build_payload(req, stream=False))
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    data = r.json()
    eval_s = data.get("eval_duration", 0) / 1e9
    answer, thinking = split_think(data["message"]["content"])
    return {
        "answer": answer,
        "thinking": data["message"].get("thinking") or thinking,
        "model": data["model"],
        "stats": {
            "wall_s": round(time.perf_counter() - start, 2),
            "load_s": round(data.get("load_duration", 0) / 1e9, 2),
            "tokens": data.get("eval_count"),
            "tokens_per_s": round(data.get("eval_count", 0) / eval_s, 1) if eval_s else None,
        },
    }


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """NDJSON: {"thinking": ...} / {"content": ...} por fragmento y {"stats": ...} al final."""

    async def gen():
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=build_payload(req, stream=True)) as r:
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        yield json.dumps({"error": chunk["error"]}) + "\n"
                        return
                    msg = chunk.get("message", {})
                    if msg.get("thinking"):
                        yield json.dumps({"thinking": msg["thinking"]}) + "\n"
                    if msg.get("content"):
                        yield json.dumps({"content": msg["content"]}) + "\n"
                    if chunk.get("done"):
                        eval_s = chunk.get("eval_duration", 0) / 1e9
                        yield json.dumps({"stats": {
                            "wall_s": round(time.perf_counter() - start, 2),
                            "load_s": round(chunk.get("load_duration", 0) / 1e9, 2),
                            "tokens": chunk.get("eval_count"),
                            "tokens_per_s": round(chunk.get("eval_count", 0) / eval_s, 1) if eval_s else None,
                        }}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.get("/")
async def index():
    return FileResponse(Path(__file__).with_name("index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

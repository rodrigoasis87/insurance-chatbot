#!/usr/bin/env bash
# Setup de desarrollo del equipo: entorno identico via Docker (+ uv).
# Uso: bash scripts/setup.sh
set -euo pipefail

echo "== [1/4] uv sync =="
uv sync

echo "== [2/4] Levantando servicios (Qdrant + Ollama) =="
docker compose up -d

echo "== [3/4] Bajando modelos de Ollama (una sola vez por maquina) =="
docker compose exec ollama ollama pull qwen3:4b-instruct   # LLM del RAG (#9)
docker compose exec ollama ollama pull qwen3-embedding:0.6b   # embeddings del RAG (#9)

echo "== [4/4] Smoke test del stack =="
uv run python scripts/smoke_stack.py

echo
echo "Listo. Recordá: no uses Ollama nativo para este proyecto"
echo "(docker compose es la fuente de verdad)."
#!/usr/bin/env bash
# Setup de desarrollo del equipo: entorno identico via Docker (+ uv).
# Uso: bash scripts/setup.sh
#   USE_GPU=1 fuerza GPU NVIDIA, USE_GPU=0 fuerza CPU (por defecto se autodetecta).
set -euo pipefail

OLLAMA_IMAGE="ollama/ollama:0.24.0"

# GPU NVIDIA solo si el host tiene driver y Docker puede pasarla a un contenedor
detect_gpu() {
  command -v nvidia-smi >/dev/null 2>&1 || return 1
  docker run --rm --gpus all --entrypoint nvidia-smi "$OLLAMA_IMAGE" -L >/dev/null 2>&1
}

echo "== [1/4] uv sync =="
uv sync

COMPOSE=(docker compose -f docker-compose.yml)
if [[ "${USE_GPU:-auto}" == "1" ]] || { [[ "${USE_GPU:-auto}" == "auto" ]] && detect_gpu; }; then
  COMPOSE+=(-f docker-compose.gpu.yml)
  echo "GPU NVIDIA detectada: Ollama correra en GPU (docker-compose.gpu.yml)"
else
  echo "Sin GPU NVIDIA disponible para Docker: Ollama correra en CPU"
fi

echo "== [2/4] Levantando servicios (Qdrant + Ollama) =="
"${COMPOSE[@]}" up -d

echo "== [3/4] Bajando modelos de Ollama (una sola vez por maquina) =="
"${COMPOSE[@]}" exec ollama ollama pull qwen3:4b
"${COMPOSE[@]}" exec ollama ollama pull nomic-embed-text

echo "== [4/4] Smoke test del stack =="
uv run python scripts/smoke_stack.py

echo
echo "Listo. Recordá: no uses Ollama nativo para este proyecto"
echo "(docker compose es la fuente de verdad)."
echo "Verificá CPU/GPU con: docker compose exec ollama ollama ps  (columna PROCESSOR)"

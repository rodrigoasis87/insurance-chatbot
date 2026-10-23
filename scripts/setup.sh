#!/usr/bin/env bash
# Setup de desarrollo del equipo: entorno identico via Docker (+ uv).
# Uso: bash scripts/setup.sh
set -euo pipefail

echo "== [1/5] uv sync =="
uv sync

echo "== [2/5] Levantando servicios (Qdrant + Ollama) =="
docker compose up -d

echo "== [3/5] Bajando modelos de Ollama (una sola vez por maquina) =="
docker compose exec ollama ollama pull qwen3:4b-instruct   # LLM del RAG (#9)
docker compose exec ollama ollama pull qwen3-embedding:0.6b   # embeddings del RAG (#9)

# El corpus NO viaja en el repo (/data/* esta gitignored, ver .gitignore:17):
# los PDFs son de una bucket de S3 y los artefactos derivados se regeneran.
# Si data/processed/chunks.jsonl ya existe (maquina con data cacheada) se salta.
echo "== [4/5] Corpus e indice =="
if [ -f data/processed/chunks.jsonl ]; then
  echo "-- ya existe data/processed/chunks.jsonl; se omite la reconstruccion"
  echo "-- (reindexar si cambiaste el corpus: uv run python -m app.rag.indexer)"
else
  echo "-- descargando PDFs (S3): requiere AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY en .env"
  if ! uv run python -m app.data.download; then
    echo
    echo "!! no se pudo descargar el corpus desde S3."
    echo "   Copialo desde otra maquina del equipo y reejecuta este script:"
    echo "     rsync -av --exclude='evaluation/results' data/ <usuario>@<host>:data/"
    exit 1
  fi
  echo "-- PDFs -> articulos.jsonl"
  uv run python -m app.data.build_articulos
  echo "-- articulos.jsonl -> chunks.jsonl"
  uv run python -m app.data.chunker
  echo "-- chunks.jsonl -> Qdrant"
  uv run python -m app.rag.indexer
  echo
  echo "Si la descarga por S3 no es posible (sin credenciales en la maquina),"
  echo "copia el corpus desde otra maquina del equipo:"
  echo "  rsync -av --exclude='evaluation/results' data/ <usuario>@<host>:data/"
fi

echo "== [5/5] Smoke test del stack =="
uv run python scripts/smoke_stack.py

echo
echo "Listo. Recordá: no uses Ollama nativo para este proyecto"
echo "(docker compose es la fuente de verdad)."
echo
echo "Si la maquina tiene GPU NVIDIA, levantalo con el overlay:"
echo "  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d"

# Imagen unica del proyecto: sirve al API (uvicorn) y a la UI (chainlit).
# El indice vive en Qdrant y los modelos en Ollama (volumenes del compose),
# por eso la imagen no copia /data ni modelos (ADR-001, #21).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PIP_NO_CACHE_DIR=1

RUN pip install --quiet uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY chainlit.md ./
COPY .chainlit/config.toml .chainlit/config.toml
# Textos del login: "Usuario" en vez de "Correo electrónico" (el resto de
# idiomas los autogenera Chainlit al arrancar).
COPY .chainlit/translations/es.json .chainlit/translations/en-US.json .chainlit/translations/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
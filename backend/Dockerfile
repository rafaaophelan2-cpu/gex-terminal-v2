FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para compilar wheels de scipy/numpy si no hay
# manylinux disponible para la arquitectura del build de HF Spaces.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Hugging Face Spaces (Docker SDK) NO tiene filesystem persistente en el
# tier gratuito: cualquier archivo escrito acá se pierde en cada
# rebuild/sleep-wake. El token OAuth de Schwab por eso NO vive en disco de
# forma duradera — se sincroniza con una tabla de Supabase
# (schwab_oauth_token) en integrations/schwab_client.py; esta ruta es solo
# un archivo de trabajo temporal para que schwab-py opere en cada arranque.
ENV SCHWAB_TOKEN_PATH=/tmp/schwab_token.json

# HF Spaces espera el puerto declarado como `app_port` en el frontmatter de
# README.md — 7860 es la convención de la plataforma.
EXPOSE 7860

# Un solo worker: FeedManager y los locks de Schwab son estado compartido en
# memoria de un único proceso por diseño (ver docs/plan del proyecto).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]

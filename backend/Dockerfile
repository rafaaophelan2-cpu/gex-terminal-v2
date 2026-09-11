FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para compilar wheels de scipy/numpy si no hay
# manylinux disponible para la arquitectura del build de Render.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Filesystem no persistente entre deploys: el token OAuth de Schwab se
# sincroniza con una tabla de Supabase (integrations/schwab_client.py) en
# vez de depender de disco local — esta ruta es solo un archivo de trabajo
# temporal para que schwab-py opere en cada arranque.
ENV SCHWAB_TOKEN_PATH=/tmp/schwab_token.json

EXPOSE 8000

# Render inyecta la variable PORT (default 10000) y espera que el
# proceso escuche ahí -- ${PORT:-8000} la respeta si existe y cae a 8000
# para correr el mismo Dockerfile local (docker run sin PORT seteado).
# Un solo worker: FeedManager y los locks de Schwab son estado compartido
# en memoria de un único proceso por diseño (ver docs/plan del proyecto).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1

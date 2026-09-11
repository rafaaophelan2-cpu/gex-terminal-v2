FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para compilar wheels de scipy/numpy si no hay
# manylinux disponible para la arquitectura del build de Fly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# El token OAuth de Schwab se persiste en un Fly Volume montado en /data
# (ver fly.toml) para sobrevivir restarts/deploys sin re-autenticar.
ENV SCHWAB_TOKEN_PATH=/data/schwab_token.json

EXPOSE 8080

# Un solo worker: FeedManager y los locks de Schwab son estado compartido en
# memoria de un único proceso por diseño (ver docs/plan del proyecto).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]

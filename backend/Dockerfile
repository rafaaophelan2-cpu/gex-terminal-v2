# slim-bookworm fijo a propósito (no solo "python:3.11-slim"): esa
# etiqueta ahora resuelve a Debian trixie, que playwright install
# --with-deps todavía no reconoce -- falla buscando paquetes con nombres
# viejos (ttf-unifont) que ya no existen ahí. bookworm es la versión de
# Debian que sí soporta oficialmente.
FROM python:3.11-slim-bookworm

WORKDIR /app

# Dependencias del sistema para compilar wheels de scipy/numpy si no hay
# manylinux disponible para la arquitectura del build de Render.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# PRUEBA (temporal): Chromium para scrapear Open Interest real de Yahoo
# Finance en NDX/VIX (Schwab no lo da para estos símbolos, ver
# oi_fallback.py) -- el objetivo de este paso es solo confirmar si el
# plan gratis de Render (0.1 vCPU / 512MB) aguanta correr un navegador
# headless sin tirar abajo el resto del servicio. --with-deps instala
# las librerías de sistema que Chromium necesita en Debian.
RUN playwright install --with-deps chromium

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

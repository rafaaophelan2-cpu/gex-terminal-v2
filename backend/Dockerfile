FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema para compilar wheels de scipy/numpy si no hay
# manylinux disponible para la arquitectura del build de Koyeb.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Koyeb no exige un puerto fijo por convención (a diferencia de HF Spaces
# con su 7860): el puerto declarado acá debe coincidir con el configurado
# en el panel del servicio de Koyeb al crearlo.
#
# Filesystem no persistente entre deploys: el token OAuth de Schwab se
# sincroniza con una tabla de Supabase (integrations/schwab_client.py) en
# vez de depender de disco local — esta ruta es solo un archivo de trabajo
# temporal para que schwab-py opere en cada arranque.
ENV SCHWAB_TOKEN_PATH=/tmp/schwab_token.json

EXPOSE 8000

# Un solo worker: FeedManager y los locks de Schwab son estado compartido en
# memoria de un único proceso por diseño (ver docs/plan del proyecto).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

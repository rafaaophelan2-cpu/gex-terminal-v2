"""Script de un solo uso: autoriza la app de Schwab (requiere iniciar
sesión en un navegador con tu cuenta real, por eso corre en tu máquina, no
en el servidor) y guarda el token resultante en Supabase en vez de un
archivo local -- Back4app no tiene disco persistente entre deploys.

Antes de correrlo:
  1. Ejecutar schwab_oauth_table.sql en el SQL Editor de Supabase.
  2. Tener un archivo backend/.env con SCHWAB_CLIENT_ID, SCHWAB_CLIENT_SECRET,
     SUPABASE_URL, SUPABASE_KEY (las mismas que ya cargaste en Back4app).

Uso (desde backend/, con el venv activado):
    .venv/Scripts/python.exe scripts/bootstrap_schwab_token.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schwab.auth import client_from_manual_flow
from supabase import create_client

from app.config import get_settings

# Debe coincidir EXACTO con el Callback URL registrado en el Schwab
# Developer Portal para esta app (mismo que ya usaba app.py).
CALLBACK_URL = "https://127.0.0.1"
TOKEN_PATH = Path(__file__).resolve().parent / "_schwab_token_bootstrap.json"


def main():
    settings = get_settings()

    missing = [
        name for name, val in [
            ("SCHWAB_CLIENT_ID", settings.schwab_client_id),
            ("SCHWAB_CLIENT_SECRET", settings.schwab_client_secret),
            ("SUPABASE_URL", settings.supabase_url),
            ("SUPABASE_KEY", settings.supabase_key),
        ] if not val
    ]
    if missing:
        print(f"Faltan estas variables en backend/.env: {', '.join(missing)}")
        sys.exit(1)

    print("Se abrirá el flujo de autorización de Schwab.")
    print("1. Visita la URL que te va a mostrar.")
    print("2. Inicia sesión con tu cuenta real de Schwab y autoriza la app.")
    print("3. El navegador va a intentar redirigir a https://127.0.0.1 y va a")
    print("   fallar/quedar en blanco -- eso es NORMAL, nada corre ahí.")
    print("4. Copia la URL completa de la barra de direcciones en ese momento")
    print("   (empieza con https://127.0.0.1/?code=...) y pégala cuando te la pida.\n")

    client_from_manual_flow(
        api_key=settings.schwab_client_id,
        app_secret=settings.schwab_client_secret,
        callback_url=CALLBACK_URL,
        token_path=str(TOKEN_PATH),
    )

    token_data = json.loads(TOKEN_PATH.read_text())

    supabase = create_client(settings.supabase_url, settings.supabase_key)
    supabase.table("schwab_oauth_token").upsert({
        "id": 1,
        "token_json": token_data,
    }).execute()

    TOKEN_PATH.unlink(missing_ok=True)
    print("\nToken guardado en Supabase (tabla schwab_oauth_token). Listo --")
    print("ya se puede borrar/ignorar este script, el backend lo va a leer solo.")


if __name__ == "__main__":
    main()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Equivalente a st.secrets del app.py de Streamlit. Se llenan vía
    variables de entorno (`fly secrets set ...` en producción, `.env` local
    para desarrollo — nunca commitear ese `.env`)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Schwab
    schwab_client_id: str = ""
    schwab_client_secret: str = ""
    schwab_token_path: str = "schwab_token.json"

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""

    # Firebase Realtime Database
    firebase_db_url: str = ""

    # IA
    groq_api_key: str = ""
    gemini_api_key: str = ""

    # Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 20

    # Entorno
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Equivalente a st.secrets del app.py de Streamlit. Se llenan vía
    variables de entorno (panel del servicio en Render en producción,
    `.env` local para desarrollo — nunca commitear ese `.env`)."""

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
    # Símbolo cuyo SymbolFeed se empuja a /live_levels para el indicador
    # de Quantower -- el indicador lee un único nodo plano, sin dimensión
    # de símbolo, igual que hacía app.py con su único dashboard.
    quantower_symbol: str = "QQQ"

    # IA (solo Groq; Gemini no se usa)
    groq_api_key: str = ""

    # MarketData.app -- fuente de Open Interest REAL para NDX/VIX (Schwab
    # no lo tiene para indices, ver domain/oi_fallback.py). Free tier sin
    # tarjeta ni KYC de USA -- ver integrations/marketdata_client.py.
    marketdata_api_key: str = ""

    # Finnhub -- calendario económico (CPI/FOMC/NFP) para el prompt de la
    # IA, ver integrations/finnhub_client.py. Igual que MarketData.app:
    # tier gratis sin tarjeta ni restricción de país, opcional -- vacío
    # simplemente deja el calendario fuera del contexto de la IA.
    finnhub_api_key: str = ""

    # Auth -- 720 min (12h) cubre una sesión de mercado completa sin
    # desloguear al usuario a mitad de uso. Antes eran 20 min sin ningún
    # refresh silencioso: cualquier request después de esos 20 min (ej.
    # cambiar los DTEs del GRID) fallaba con 401 "No autenticado" en
    # plena sesión activa -- bug real reportado en vivo.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 720

    # Entorno
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # Sin esto, un JWT_SECRET vacío (env var no seteada en Render, o un
    # despliegue nuevo antes de configurarla) hace que create_access_token/
    # decode_access_token firmen y verifiquen silenciosamente con clave
    # vacía -- python-jose no rechaza una clave HS256 vacía, así que
    # CUALQUIERA podría forjar un token válido para cualquiera de los 3
    # usuarios sin ninguna credencial. Falla rápido al arrancar en vez de
    # dejar la API entera abierta sin ningún aviso.
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET no está configurado -- la API no puede arrancar así "
            "(firmaría/verificaría tokens con una clave vacía, forjable por "
            "cualquiera). Configurá la variable de entorno JWT_SECRET."
        )
    return settings

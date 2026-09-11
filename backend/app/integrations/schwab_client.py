import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from schwab.auth import client_from_access_functions

# Schwab evalúa from_date/to_date contra SU propio "hoy" (hora de mercado,
# US Eastern) -- usar datetime.now() (hora local del servidor, que puede
# ser Lima/UTC/lo que sea) puede quedar hasta un día desfasado según la
# hora del día, y Schwab responde 400 "Check Param Values" si from_date
# queda en el pasado desde su perspectiva. Confirmado empíricamente:
# from_date con la fecha de Lima cerca de medianoche fallaba, con la
# fecha de NY funcionaba.
MARKET_TZ = ZoneInfo("America/New_York")

from app.config import get_settings
from app.integrations.supabase_client import get_supabase_client

settings = get_settings()

# Serializa TODAS las llamadas de red a Schwab (chain, velas, quotes) —
# equivalente async de _schwab_client_lock en app.py. schwab-py con
# asyncio=True no garantiza que un refresh de token concurrente con otra
# llamada sea seguro, así que se serializa igual.
_call_lock = asyncio.Lock()

# "Último dato bueno" por cache_key, en memoria del proceso. A diferencia
# de app.py, acá no hace falta el truco de @st.cache_resource: sin reruns
# de Streamlit, un dict de módulo normal ya persiste durante toda la vida
# del proceso (lru_cache/instancia única, no se reinicializa solo).
_last_good: dict[str, object] = {}


def _read_token_sync() -> dict | None:
    client = get_supabase_client()
    if client is None:
        return None
    res = client.table("schwab_oauth_token").select("token_json").eq("id", 1).execute()
    return res.data[0]["token_json"] if res.data else None


def _write_token_sync(token_metadata: dict, *args, **kwargs) -> None:
    """Callback de schwab-py: se llama automáticamente cada vez que la
    librería refresca el token (Schwab invalida el refresh_token a los 7
    días si no se usa/renueva, así que este resync es lo que mantiene el
    acceso vivo indefinidamente). token_metadata ya viene en el mismo
    formato {'creation_timestamp': ..., 'token': {...}} que se leyó.

    *args/**kwargs: schwab-py invoca este callback pasando también los
    kwargs internos de authlib (ej. refresh_token=...) además del token
    ya envuelto -- se ignoran, solo se persiste token_metadata."""
    client = get_supabase_client()
    if client is None:
        return
    client.table("schwab_oauth_token").upsert({"id": 1, "token_json": token_metadata}).execute()


@lru_cache
def get_schwab_client():
    """Cliente único de Schwab para todo el proceso (equivalente al
    @st.cache_resource de app.py). El token se lee/escribe en Supabase en
    vez de un archivo en disco -- Render no tiene filesystem persistente
    entre deploys/restarts. Devuelve None si no hay credenciales o token
    guardado todavía (ver scripts/bootstrap_schwab_token.py)."""
    if not settings.schwab_client_id or not settings.schwab_client_secret:
        return None

    token = _read_token_sync()
    if token is None:
        return None

    return client_from_access_functions(
        api_key=settings.schwab_client_id,
        app_secret=settings.schwab_client_secret,
        token_read_func=lambda: token,
        token_write_func=_write_token_sync,
        asyncio=True,
    )


async def call_with_fallback(cache_key: str, empty_value, fetch_coro_fn):
    """Ejecuta fetch_coro_fn() serializado por _call_lock. Si el resultado
    es vacío o la llamada lanza una excepción, sirve el último valor bueno
    conocido para cache_key en vez de propagar un vacío -- así un fallo
    transitorio en una llamada nunca "vacía" lo que ven las conexiones
    activas. Port async de _schwab_call_with_fallback en app.py (~línea 633)."""
    try:
        async with _call_lock:
            result = await fetch_coro_fn()
        is_empty = (
            result is None
            or (isinstance(result, (dict, list)) and len(result) == 0)
        )
        if not is_empty:
            _last_good[cache_key] = result
            return result
    except Exception:
        pass
    return _last_good.get(cache_key, empty_value)


async def fetch_option_chain(symbol: str, strikes_count: int) -> dict:
    client = get_schwab_client()
    if client is None:
        return {}

    async def _do_fetch():
        today = datetime.now(MARKET_TZ)
        resp = await client.get_option_chain(
            symbol=symbol,
            contract_type=client.Options.ContractType.ALL,
            strike_count=strikes_count,
            from_date=today,
            to_date=today + timedelta(days=90),
        )
        if resp.status_code == 200:
            return resp.json()
        return {}

    return await call_with_fallback(f"chain:{symbol}:{strikes_count}", {}, _do_fetch)


async def fetch_price_history(symbol: str, day: datetime) -> list[dict]:
    """Velas reales de 1 minuto para el día de mercado 'day' (debe venir
    con tzinfo=MARKET_TZ, medianoche NY de ese día) -- port de
    fetch_history_schwab en app.py, usado para superponer velas japonas
    reales sobre el heatmap de LIVE GAMMA en vez de una línea simple de
    spot. Devuelve [{time, open, high, low, close}, ...] en hora NY."""
    client = get_schwab_client()
    if client is None:
        return []

    async def _do_fetch():
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        resp = await client.get_price_history(
            symbol,
            start_datetime=day_start,
            frequency_type=client.PriceHistory.FrequencyType.MINUTE,
            frequency=client.PriceHistory.Frequency.EVERY_MINUTE,
            need_extended_hours_data=False,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        candles = data.get("candles", []) if isinstance(data, dict) else []
        out = []
        for c in candles:
            dt = datetime.fromtimestamp(c["datetime"] / 1000, tz=MARKET_TZ)
            out.append({
                "time": dt.strftime("%H:%M"),
                "open": float(c["open"]), "high": float(c["high"]),
                "low": float(c["low"]), "close": float(c["close"]),
            })
        return out

    return await call_with_fallback(f"candles:{symbol}:{day.strftime('%Y-%m-%d')}", [], _do_fetch)


async def fetch_quote(symbol: str) -> dict:
    client = get_schwab_client()
    if client is None:
        return {}

    async def _do_fetch():
        resp = await client.get_quote(symbol)
        if resp.status_code == 200:
            return resp.json()
        return {}

    return await call_with_fallback(f"quote:{symbol}", {}, _do_fetch)

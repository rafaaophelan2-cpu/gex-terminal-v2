import asyncio
import logging
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
logger = logging.getLogger(__name__)

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
        logger.warning("call_with_fallback('%s'): resultado vacío, usando último valor bueno.", cache_key)
    except Exception:
        # Se tragaba en silencio -- si fetch_coro_fn tira (ej. el token de
        # Schwab quedó inválido), acá es donde de verdad se pierde el
        # rastro: ni siquiera le llega la excepción a quien llama, así que
        # ningún logging más arriba en la cadena (ver _run_loop en
        # market_feed.py) puede verla. Sin loggear ACÁ, un fallo sostenido
        # de Schwab es indistinguible de "no hay dato nuevo todavía".
        logger.exception("call_with_fallback('%s'): fetch_coro_fn() falló, usando último valor bueno si hay.", cache_key)
    return _last_good.get(cache_key, empty_value)


async def fetch_option_chain(symbol: str, strikes_count: int) -> dict:
    client = get_schwab_client()
    if client is not None:
        import time as _time
        try:
            sess_token = client.session.token
            logger.warning(
                "DIAG fetch_option_chain: now=%s expires_at=%s expires_in=%s token_type=%s scope=%s keys=%s",
                _time.time(), sess_token.get('expires_at'), sess_token.get('expires_in'),
                sess_token.get('token_type'), sess_token.get('scope'), list(sess_token.keys()),
            )
        except Exception:
            logger.exception("DIAG fetch_option_chain: no se pudo leer client.session.token")
    if client is None:
        # Este camino NUNCA pasa por call_with_fallback -- sin credenciales
        # o token guardado, no tiene sentido usar el "último dato bueno"
        # (nunca va a poder refrescarlo tampoco), pero antes esto era
        # indistinguible en silencio de cualquier otro motivo de feed
        # vacío. Loggeado para que quede claro en Render que el problema
        # es credenciales/token, no la API de Schwab en sí.
        logger.warning("get_schwab_client() devolvió None (sin client_id/secret o sin token en Supabase) -- %s sin datos.", symbol)
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
        logger.warning("Schwab get_option_chain(%s) devolvió status %s: %s", symbol, resp.status_code, resp.text[:500])
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


async def fetch_nq_price() -> float:
    """Port de fetch_nq_price_schwab en app.py: precio en vivo del futuro
    continuo /NQ, usado solo para calcular conversion_ratio (= nq/spot)
    del push a Quantower -- nunca para GEX/Griegas."""
    client = get_schwab_client()
    if client is None:
        return 0.0

    async def _do_fetch():
        resp = await client.get_quote("/NQ")
        if resp.status_code == 200:
            data = resp.json()
            quote = (data.get("/NQ", {}) or {}).get("quote", {})
            price = float(quote.get("lastPrice", quote.get("closePrice", 0.0)))
            if price > 0:
                return price
        return 0.0

    return await call_with_fallback("nq_price", 0.0, _do_fetch)


async def fetch_vix() -> float:
    """Port de fetch_vix_schwab en app.py: prueba varios símbolos porque
    Schwab no siempre resuelve $VIX con el mismo ticker exacto."""
    client = get_schwab_client()
    if client is None:
        return 0.0

    async def _do_fetch():
        for sym in ["$VIX", "VIX", "$VIX.X"]:
            resp = await client.get_quote(sym)
            if resp.status_code == 200:
                data = resp.json()
                quote = (data.get(sym, {}) or {}).get("quote", {})
                price = float(quote.get("lastPrice", quote.get("closePrice", 0.0)))
                if price > 0:
                    return price
        return 0.0

    return await call_with_fallback("vix_price", 0.0, _do_fetch)

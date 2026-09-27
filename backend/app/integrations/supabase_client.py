import asyncio
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from supabase import Client, create_client

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# El dedup de insert_gex_snapshot compara por symbol+time ("HH:MM", sin
# fecha) -- necesita acotarse al día de mercado en curso para no confundir
# el "09:30" de hoy con el "09:30" ya guardado ayer. Mismo criterio de
# zona horaria que STORAGE_TZ en snapshot_writer.py.
_NY_TZ = ZoneInfo("America/New_York")


@lru_cache
def get_supabase_client() -> Client | None:
    """Instancia única del cliente de Supabase para todo el proceso (mismo
    patrón que get_supabase_client en app.py, pero acá no hace falta el
    @st.cache_resource: sin reruns de Streamlit, un lru_cache normal ya
    persiste durante toda la vida del proceso)."""
    if not settings.supabase_url or not settings.supabase_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_key)


async def fetch_user_by_username(username: str) -> dict | None:
    """Busca en app_users por username (case-insensitive por convención de
    login_user en app.py). supabase-py es síncrono: se corre en un thread
    aparte para no bloquear el event loop de FastAPI."""
    client = get_supabase_client()
    if client is None:
        return None

    def _query():
        res = client.table("app_users").select("*").eq("username", username).execute()
        return res.data[0] if res.data else None

    return await asyncio.to_thread(_query)


async def update_user_password_hash(username: str, new_hash: str) -> None:
    """Usado para el upgrade perezoso de SHA256 -> argon2 tras un login
    exitoso con el hash legado."""
    client = get_supabase_client()
    if client is None:
        return

    def _update():
        client.table("app_users").update({"password_hash": new_hash}).eq("username", username).execute()

    await asyncio.to_thread(_update)


async def fetch_gex_history(
    symbol: str,
    start_utc: str | None = None,
    end_utc: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Snapshots de gex_intraday para un símbolo, ordenados cronológicamente,
    opcionalmente acotados a un rango de created_at (ISO 8601 UTC) -- usado
    para filtrar por día calendario de mercado (ver routes_rest.py). Port
    de fetch_supabase_gex_history en app.py (~línea 103)."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        q = client.table("gex_intraday").select("*").eq("symbol", symbol)
        if start_utc:
            q = q.gte("created_at", start_utc)
        if end_utc:
            q = q.lt("created_at", end_utc)
        res = q.order("created_at", desc=False).limit(limit).execute()
        return res.data or []

    return await asyncio.to_thread(_query)


async def fetch_latest_snapshot(symbol: str) -> dict | None:
    """El snapshot MÁS RECIENTE guardado para 'symbol', sin importar de
    qué día -- fuera de horario de mercado (pre-market, overnight), esto
    es naturalmente "el cierre de la última sesión", exactamente lo que
    necesita un briefing de pre-apertura (ver GET /market/premarket-briefing).
    A diferencia de fetch_gex_history (que pide un rango), esto no
    necesita saber de antemano qué día calendario buscar."""
    client = get_supabase_client()
    if client is None:
        return None

    def _query():
        res = (
            client.table("gex_intraday")
            .select("*")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    return await asyncio.to_thread(_query)


# PostgREST corta cualquier SELECT en su "Max rows" (1,000 en Supabase) SIN
# devolver error: un .limit(5000) devuelve 1,000 filas y nadie se entera.
# Con un snapshot por minuto eso son ~2.5 sesiones de historial, así que las
# dos funciones de abajo (que antes traían "las últimas 5,000 filas" y
# agrupaban por día en Python) veían solo los 2-3 días más recientes: el
# selector de fechas de BACKGAMMA/LIVE GAMMA quedaba corto y el percentil
# real de IV nunca juntaba los 10 días mínimos, así que la web seguía con
# la fórmula estimada (auditoría 26-sep-2026, #9).
#
# En vez de traer filas, se CAMINA hacia atrás de a un día: "la última fila
# antes de X" (limit 1, nunca choca con el tope), se anota su día y X pasa a
# ser el inicio de ese día. Una consulta por día con datos. Los días ya
# cerrados no cambian, así que se guardan en memoria y la caminata se corta
# al llegar a uno conocido: en régimen son 2 consultas por llamada.


def _parse_ts(value: str) -> datetime:
    """created_at de PostgREST a datetime con zona. Tolera 'Z' y fracciones
    de segundo de largo variable (Python 3.10 solo acepta 3 o 6 dígitos)."""
    import re

    v = value.replace("Z", "+00:00")
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", v)
    if m:
        frac = (m.group(2) or ".0")[1:]
        v = f"{m.group(1)}.{(frac + '000000')[:6]}{m.group(3)}"
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _walk_days_back(latest_before, tz, known: dict, max_days: int) -> tuple[dict, bool]:
    """Recorre días hacia atrás llamando latest_before(cursor_iso|None) ->
    fila|None. Devuelve ({día: fila} de los días nuevos, completo). Se
    detiene al quedarse sin filas, al llegar a un día ya conocido que no
    sea hoy, o tras max_days días. 'completo' es False si hubo un error a
    mitad de camino: en ese caso no hay que cachear, porque quedaría un
    hueco entre lo nuevo y lo viejo que ninguna caminata futura rellenaría."""
    today = datetime.now(tz).date().isoformat()
    found: dict[str, dict] = {}
    cursor: str | None = None
    try:
        while len(found) < max_days:
            row = latest_before(cursor)
            if not row:
                break
            day = _parse_ts(row["created_at"]).astimezone(tz).date()
            key = day.isoformat()
            if key != today and key in known:
                break
            if key in found:
                # Sin avance (el cursor no filtró): cortar en vez de girar
                # para siempre contra un backend que ignora el filtro.
                break
            found[key] = row
            cursor = datetime.combine(day, dtime.min, tzinfo=tz).astimezone(timezone.utc).isoformat()
    except Exception:
        logger.exception("Caminata diaria sobre gex_intraday cortada por un error -- se usa lo que había.")
        return found, False
    return found, True


# {(símbolo, zona): {día: True}} y {símbolo: {día: iv}} -- solo días ya
# cerrados; se pierden en cada redeploy y se rearman con una caminata.
_available_dates_cache: dict[tuple[str, str], dict[str, bool]] = {}
_daily_iv_cache: dict[str, dict[str, float]] = {}


async def fetch_available_dates(symbol: str, tz, max_days: int = 400) -> list[str]:
    """Fechas calendario (YYYY-MM-DD, en la zona horaria 'tz') que tienen
    al menos un snapshot DENTRO del horario de mercado (09:30-16:00 NY)
    para 'symbol', más recientes primero -- usado tanto por el selector
    de BACKGAMMA como por LIVE GAMMA para resolver "la última sesión"
    (dates[0] en el frontend).

    El filtro de horario importa incluso con snapshot_writer ya
    gateado a horas de mercado (ver snapshot_writer.py): filas viejas de
    ANTES de ese fix, o cualquier fila fuera de horario insertada por
    otra vía, no deben hacer que este símbolo apunte a un día sin
    ninguna fila útil para el heatmap/drift -- eso dejaba LIVE GAMMA en
    blanco hasta que abriera el mercado real. Los fines de semana se
    descartan: Schwab sirve la última chain conocida 24/7 y se llegaron a
    colar snapshots de sábado/domingo (no cubre feriados de mercado)."""
    client = get_supabase_client()
    if client is None:
        return []

    from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

    def _latest_before(cursor_iso):
        q = (
            client.table("gex_intraday")
            .select("created_at, time")
            .eq("symbol", symbol)
            .gte("time", DEFAULT_SESSION_START)
            .lte("time", DEFAULT_SESSION_END)
        )
        if cursor_iso:
            q = q.lt("created_at", cursor_iso)
        res = q.order("created_at", desc=True).limit(1).execute()
        return (res.data or [None])[0]

    cache = _available_dates_cache.setdefault((symbol, str(tz)), {})
    found, complete = await asyncio.to_thread(_walk_days_back, _latest_before, tz, cache, max_days)
    today = datetime.now(tz).date().isoformat()
    if complete:
        cache.update({d: True for d in found if d != today})

    days = set(cache) | set(found)
    weekdays = [d for d in days if datetime.fromisoformat(d).weekday() < 5]
    return sorted(weekdays, reverse=True)[:max_days]


async def fetch_daily_atm_iv_history(symbol: str, max_days: int = 400) -> list[float]:
    """Un valor de IV ATM por día de mercado de NY (la última lectura de ese
    día, ~el cierre) para 'symbol', más reciente primero -- historial real
    para el percentil de IV de domain/iv_percentile.py. Requiere la columna
    'atm_iv' en gex_intraday (ver scripts/add_atm_iv_column.sql); si todavía
    no existe, PostgREST devuelve un error de columna desconocida, que acá
    se trata como 'sin historial todavía' (loggeado) en vez de propagarlo."""
    client = get_supabase_client()
    if client is None:
        return []

    def _latest_before(cursor_iso):
        q = (
            client.table("gex_intraday")
            .select("created_at, atm_iv")
            .eq("symbol", symbol)
            .not_.is_("atm_iv", "null")
        )
        if cursor_iso:
            q = q.lt("created_at", cursor_iso)
        res = q.order("created_at", desc=True).limit(1).execute()
        return (res.data or [None])[0]

    cache = _daily_iv_cache.setdefault(symbol, {})
    found, complete = await asyncio.to_thread(_walk_days_back, _latest_before, _NY_TZ, cache, max_days)
    fresh = {d: float(r["atm_iv"]) for d, r in found.items()}
    today = datetime.now(_NY_TZ).date().isoformat()
    if complete:
        cache.update({d: v for d, v in fresh.items() if d != today})

    daily = {**cache, **fresh}
    return [daily[d] for d in sorted(daily, reverse=True)[:max_days]]


async def insert_gex_snapshot(snapshot: dict) -> None:
    """Guarda un snapshot en gex_intraday, con el mismo dedup por
    symbol+time que push_to_supabase_bg en app.py (~línea 2598): con
    varias conexiones guardando cada ~60s de forma independiente, dos
    pueden caer casi en el mismo minuto y duplicar la fila.

    'time' es solo "HH:MM" (sin fecha) -- comparado a secas, el "09:30"
    de hoy calza con el "09:30" ya guardado cualquier día anterior y el
    insert se descarta como si fuera un duplicado real, dejando el
    símbolo sin ningún snapshot nuevo apenas se repite el horario de
    mercado (bug encontrado en vivo: LIVE GAMMA quedaba vacío el mismo
    día que se agotaban los "HH:MM" ya vistos en días previos). El dedup
    se acota al día de mercado en curso (NY) para que solo bloquee
    duplicados reales dentro del mismo día."""
    client = get_supabase_client()
    if client is None:
        return

    day_start = datetime.now(_NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    def _insert():
        existing = (
            client.table("gex_intraday")
            .select("id")
            .eq("symbol", snapshot["symbol"])
            .eq("time", snapshot["time"])
            .gte("created_at", day_start.isoformat())
            .lt("created_at", day_end.isoformat())
            .limit(1)
            .execute()
        )
        if existing.data:
            return
        try:
            client.table("gex_intraday").insert(snapshot).execute()
        except Exception:
            # 'atm_iv' requiere una columna que puede no existir todavía
            # (ver scripts/add_atm_iv_column.sql) -- sin este fallback, un
            # insert con esa clave desconocida hace fallar TODO el
            # snapshot (net_gex, spot, strikes incluidos) hasta que se
            # corra la migración, rompiendo LIVE GAMMA/NET DRIFT por un
            # campo que ni siquiera es crítico. Reintenta una vez sin
            # 'atm_iv'; si el fallo era por otra razón, se propaga igual.
            if "atm_iv" in snapshot:
                fallback = {k: v for k, v in snapshot.items() if k != "atm_iv"}
                client.table("gex_intraday").insert(fallback).execute()
            else:
                raise

    await asyncio.to_thread(_insert)


# La columna se llama "user_email" en la tabla chat_messages ya existente
# (creada para app.py) -- se reusa tal cual, pero el valor que se guarda
# ahí es el username del JWT, no un email real: es solo la etiqueta de
# identidad por usuario para scoping (historial de cada quien es privado).
async def fetch_chat_history(username: str, limit: int = 50) -> list[dict]:
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        # Bug real: 'order(desc=False).limit(limit)' devuelve los PRIMEROS
        # `limit` mensajes (los más VIEJOS), no los últimos -- una vez que
        # el historial de un usuario supera `limit`, cada llamada seguía
        # devolviendo ese mismo bloque viejo para siempre, nunca los
        # intercambios recientes. Esto rompe tanto /chat/history (se
        # supone que muestra lo último) como el 'history' que se le manda
        # a Groq como memoria conversacional (routes_chat.py:
        # CHAT_HISTORY_TURNS=12, pensado como "los últimos ~6 idas y
        # vueltas", no los primeros). Se pide DESCENDENTE (los `limit` más
        # recientes) y se revierte en Python para devolver en orden
        # cronológico normal (más viejo -> más nuevo), que es lo que
        # ambos callers esperan.
        res = (
            client.table("chat_messages")
            .select("role, content")
            .eq("user_email", username)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = res.data or []
        rows.reverse()
        return rows

    return await asyncio.to_thread(_query)


async def insert_chat_message(username: str, role: str, content: str) -> None:
    client = get_supabase_client()
    if client is None:
        return

    def _insert():
        client.table("chat_messages").insert({
            "role": role,
            "content": content,
            "user_email": username,
        }).execute()

    await asyncio.to_thread(_insert)


async def fetch_cached_economic_calendar() -> list[dict]:
    """Último calendario económico crudo (payload de ForexFactory, ANTES
    del filtro por semana/impacto de fetch_economic_calendar) que se
    haya guardado con éxito -- fallback DURABLE para cuando el fetch en
    vivo falla, ya sea por un 429 real de ForexFactory o por el bug de
    caché descubierto en vivo (14-sep-2026): el Cache API de Cloudflare
    es POR NODO/PoP, no global -- el backend y una prueba manual pueden
    pegarle a PoPs distintos con estados de caché distintos, así que un
    'ya está cacheado, no debería volver a fallar' resultó falso: cada
    PoP sin caché fresco vuelve a pegarle a ForexFactory por su cuenta.
    A diferencia de _cache en forexfactory_client.py (memoria de
    proceso, se resetea en cada redeploy), esto sobrevive redeploys Y
    fallos transitorios del fetch -- un calendario de hace unas horas
    sigue siendo mucho mejor que uno vacío, ver domain/lessons de este
    proyecto sobre 'cache en memoria + redeploys frecuentes'."""
    client = get_supabase_client()
    if client is None:
        return []

    def _fetch():
        res = client.table("economic_calendar_cache").select("events_json").eq("id", 1).limit(1).execute()
        return res.data[0]["events_json"] if res.data else []

    try:
        return await asyncio.to_thread(_fetch)
    except Exception:
        logger.exception("fetch_cached_economic_calendar() falló -- se devuelve [] (mismo criterio que un fetch en vivo fallido).")
        return []


async def save_economic_calendar_cache(events: list[dict]) -> None:
    """Persiste el payload crudo de ForexFactory recién fetcheado con
    éxito -- ver fetch_cached_economic_calendar() para el motivo. Fila
    única (id=1, upsert), igual que schwab_oauth_token en
    schwab_client.py."""
    client = get_supabase_client()
    if client is None:
        return

    def _save():
        client.table("economic_calendar_cache").upsert({"id": 1, "events_json": events}).execute()

    try:
        await asyncio.to_thread(_save)
    except Exception:
        logger.exception("save_economic_calendar_cache() falló -- no bloquea el fetch en vivo, solo se pierde el fallback de esta vuelta.")


async def clear_chat_history(username: str) -> None:
    client = get_supabase_client()
    if client is None:
        return

    def _delete():
        client.table("chat_messages").delete().eq("user_email", username).execute()

    await asyncio.to_thread(_delete)

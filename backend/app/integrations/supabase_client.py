import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from supabase import Client, create_client

from app.config import get_settings

settings = get_settings()

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


async def fetch_available_dates(symbol: str, tz) -> list[str]:
    """Fechas calendario (YYYY-MM-DD, en la zona horaria 'tz') que tienen
    al menos un snapshot DENTRO del horario de mercado (09:30-16:00 NY)
    para 'symbol', más recientes primero -- usado tanto por el selector
    de BACKGAMMA como por LIVE GAMMA para resolver "la última sesión"
    (dates[0] en el frontend). Trae created_at + time (liviano) y filtra
    en Python; con el volumen actual de datos esto alcanza sin paginar.

    El filtro de horario importa incluso con snapshot_writer ya
    gateado a horas de mercado (ver snapshot_writer.py): filas viejas de
    ANTES de ese fix, o cualquier fila fuera de horario insertada por
    otra vía, no deben hacer que este símbolo apunte a un día sin
    ninguna fila útil para el heatmap/drift -- eso dejaba LIVE GAMMA en
    blanco hasta que abriera el mercado real."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        res = (
            client.table("gex_intraday")
            .select("created_at, time")
            .eq("symbol", symbol)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        return res.data or []

    rows = await asyncio.to_thread(_query)

    from datetime import datetime

    from app.domain.drift import DEFAULT_SESSION_END, DEFAULT_SESSION_START

    dates: list[str] = []
    seen = set()
    for row in rows:
        time_str = row.get("time", "")
        if not (DEFAULT_SESSION_START <= time_str <= DEFAULT_SESSION_END):
            continue
        dt = datetime.fromisoformat(row["created_at"]).astimezone(tz)
        date_str = dt.strftime("%Y-%m-%d")
        if date_str not in seen:
            seen.add(date_str)
            dates.append(date_str)
    return dates


async def fetch_daily_atm_iv_history(symbol: str, max_days: int = 400) -> list[float]:
    """Un valor de IV ATM por día calendario (el más reciente de ese día,
    ~el cierre) para 'symbol' -- historial real para el percentil de IV de
    domain/iv_percentile.py. Requiere la columna 'atm_iv' en gex_intraday
    (ver scripts/add_atm_iv_column.sql); si todavía no existe, PostgREST
    devuelve un error de columna desconocida, que acá se trata como 'sin
    historial todavía' en vez de propagar la excepción -- así el resto de
    la app sigue funcionando aunque la migración no se haya corrido."""
    client = get_supabase_client()
    if client is None:
        return []

    def _query():
        res = (
            client.table("gex_intraday")
            .select("created_at, atm_iv")
            .eq("symbol", symbol)
            .not_.is_("atm_iv", "null")
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
        )
        return res.data or []

    try:
        rows = await asyncio.to_thread(_query)
    except Exception:
        return []

    # Filas ya vienen de más reciente a más vieja -- la primera vez que se
    # ve cada día calendario es su lectura más tardía (el cierre de ese
    # día), que es justo el criterio estándar para una serie diaria de IV.
    daily: dict[str, float] = {}
    for row in rows:
        day = (row.get("created_at") or "")[:10]
        if not day or day in daily:
            continue
        daily[day] = row["atm_iv"]
        if len(daily) >= max_days:
            break
    return list(daily.values())


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
        res = (
            client.table("chat_messages")
            .select("role, content")
            .eq("user_email", username)
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return res.data or []

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


async def clear_chat_history(username: str) -> None:
    client = get_supabase_client()
    if client is None:
        return

    def _delete():
        client.table("chat_messages").delete().eq("user_email", username).execute()

    await asyncio.to_thread(_delete)

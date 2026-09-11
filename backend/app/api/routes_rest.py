from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_auth
from app.domain.drift import compute_drift_series
from app.integrations.supabase_client import fetch_gex_history

router = APIRouter(prefix="/market", tags=["market"])

# Los snapshots se guardan con 'time' en hora de Nueva York (STORAGE_TZ,
# ver snapshot_writer.py) -- el día calendario de mercado se define en esa
# misma zona, no en la del usuario que pide el endpoint.
NY_TZ = ZoneInfo("America/New_York")


@router.get("/drift")
async def get_drift(symbol: str = "QQQ", date: str | None = None, _username: str = Depends(require_auth)):
    """Serie de NET DRIFT (horario de mercado, 09:30-16:00 NY) para
    'symbol' en el día calendario 'date' (YYYY-MM-DD, por defecto hoy en
    NY). Es REST (no WebSocket) porque no necesita empujarse en tiempo
    real tick a tick -- el frontend la vuelve a pedir cada tanto."""
    if date:
        try:
            day_start = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=NY_TZ)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido, usar YYYY-MM-DD.")
    else:
        day_start = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)

    day_end = day_start + timedelta(days=1)

    snapshots = await fetch_gex_history(
        symbol,
        start_utc=day_start.isoformat(),
        end_utc=day_end.isoformat(),
        limit=1000,
    )
    return compute_drift_series(snapshots)

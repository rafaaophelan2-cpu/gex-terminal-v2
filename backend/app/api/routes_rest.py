from fastapi import APIRouter, Depends

from app.core.security import require_auth
from app.domain.drift import compute_drift_series
from app.integrations.supabase_client import fetch_gex_history

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/drift")
async def get_drift(symbol: str = "QQQ", _username: str = Depends(require_auth)):
    """Serie de NET DRIFT del día para 'symbol', reconstruida desde los
    snapshots que snapshot_writer ya guardó en gex_intraday. Es REST (no
    WebSocket) porque no necesita empujarse en tiempo real tick a tick --
    el frontend la vuelve a pedir cada tanto (ver plan)."""
    snapshots = await fetch_gex_history(symbol, limit=500)
    return compute_drift_series(snapshots)

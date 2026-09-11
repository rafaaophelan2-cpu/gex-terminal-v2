import asyncio
import time

import pandas as pd

from app.domain.gex_math import compute_call_put_walls, compute_greeks_exposures, compute_zero_gamma, recalculate_gex_for_spot
from app.domain.metrics import get_nearest_dte_subset
from app.integrations.schwab_client import fetch_option_chain
from app.domain.parsing import parse_schwab_chain

TICK_INTERVAL_SECONDS = 2
# Fase 1 (MVP GEX INFO): IV/T_exp simplificados a un valor fijo razonable.
# El cálculo real de atm_iv (mediana de IV cerca del spot) y T_exp (días a
# la expiración 0DTE real) se porta en Fase 2 junto con el resto de
# Griegas/paneles -- no bloquea tener GEX INFO funcionando en vivo.
DEFAULT_IV = 0.20
DEFAULT_T_EXP = 1 / 365


class SymbolFeed:
    """Estado compartido de UN símbolo, recalculado una sola vez por tick
    sin importar cuántas conexiones WS estén suscritas -- cada conexión
    solo deriva un groupby barato sobre este resultado según su propia
    selección de strike_range. Mismo principio que 'FeedManager' en el
    plan: nunca recalcular Black-Scholes por conexión."""

    def __init__(self, symbol: str, strikes_count: int = 20):
        self.symbol = symbol
        self.strikes_count = strikes_count
        self.df: pd.DataFrame = pd.DataFrame()
        self.spot_price: float = 0.0
        self.schwab_online: bool = False
        self.last_update: float = 0.0
        self.nearest_exp_key: str | None = None

        self._task: asyncio.Task | None = None
        self._subscriber_count = 0

    def add_subscriber(self) -> None:
        self._subscriber_count += 1

    def remove_subscriber(self) -> None:
        self._subscriber_count = max(0, self._subscriber_count - 1)

    @property
    def has_subscribers(self) -> bool:
        return self._subscriber_count > 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick_once()
            except Exception:
                # Fase 4: loggear a console_logs (Supabase), igual que
                # log_to_console en app.py. Por ahora no tumbar el loop.
                self.schwab_online = False
            await asyncio.sleep(TICK_INTERVAL_SECONDS)

    async def _tick_once(self) -> None:
        chain = await fetch_option_chain(self.symbol, self.strikes_count)
        df, exp0 = parse_schwab_chain(chain)

        spot = float(chain.get('underlyingPrice') or 0.0) if isinstance(chain, dict) else 0.0
        if df.empty or spot <= 0:
            self.schwab_online = False
            return

        df = recalculate_gex_for_spot(df, spot_t=spot, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)
        df = compute_greeks_exposures(df, spot_price=spot, t_exp=DEFAULT_T_EXP, atm_iv=DEFAULT_IV)

        self.df = df
        self.spot_price = spot
        self.nearest_exp_key = exp0
        self.schwab_online = True
        self.last_update = time.time()

    def gex_info_payload(self, min_strike: float | None = None, max_strike: float | None = None) -> dict:
        """Slice ya agrupado/filtrado listo para mandar por WS: nearest-DTE
        por defecto, opcionalmente recortado a [min_strike, max_strike]."""
        if self.df.empty:
            return {
                "net_gex_total": 0.0, "flip_level": self.spot_price,
                "walls": {"cw1": self.spot_price, "cw2": self.spot_price, "cw3": self.spot_price,
                          "pw1": self.spot_price, "pw2": self.spot_price, "pw3": self.spot_price},
                "by_strike": [],
            }

        df_nearest = get_nearest_dte_subset(self.df)
        if min_strike is not None and max_strike is not None:
            df_nearest = df_nearest[(df_nearest['strike'] >= min_strike) & (df_nearest['strike'] <= max_strike)]

        by_strike = df_nearest.groupby('strike', as_index=False)[['call_gex', 'put_gex', 'net_gex']].sum().sort_values('strike')

        cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, self.spot_price)
        zero_gamma = compute_zero_gamma(by_strike, self.spot_price)

        return {
            "net_gex_total": float(by_strike['net_gex'].sum()),
            "flip_level": zero_gamma,
            "walls": {"cw1": cw1, "cw2": cw2, "cw3": cw3, "pw1": pw1, "pw2": pw2, "pw3": pw3},
            "by_strike": [
                {"strike": float(r.strike), "net_gex": float(r.net_gex), "call_gex": float(r.call_gex), "put_gex": float(r.put_gex)}
                for r in by_strike.itertuples()
            ],
        }

    def greeks_payload(self, min_strike: float | None = None, max_strike: float | None = None) -> dict:
        """DEX/TEX/VEX/CHEX/VANNA de la pestaña GREEKS: totales (nearest-DTE)
        + perfil por strike de cada una. DEX incluye además el desglose
        call/put (único que lo muestra en app.py); las demás solo el neto."""
        greek_cols = ['net_dex', 'net_tex', 'net_vex', 'net_chex', 'net_vanna', 'call_dex', 'put_dex']
        empty = {
            "totals": {"dex": 0.0, "tex": 0.0, "vex": 0.0, "chex": 0.0, "vanna": 0.0},
            "by_strike": [],
        }
        if self.df.empty or not all(c in self.df.columns for c in greek_cols):
            return empty

        df_nearest = get_nearest_dte_subset(self.df)
        if min_strike is not None and max_strike is not None:
            df_nearest = df_nearest[(df_nearest['strike'] >= min_strike) & (df_nearest['strike'] <= max_strike)]
        if df_nearest.empty:
            return empty

        by_strike = df_nearest.groupby('strike', as_index=False)[greek_cols].sum().sort_values('strike')

        return {
            "totals": {
                "dex": float(by_strike['net_dex'].sum()),
                "tex": float(by_strike['net_tex'].sum()),
                "vex": float(by_strike['net_vex'].sum()),
                "chex": float(by_strike['net_chex'].sum()),
                "vanna": float(by_strike['net_vanna'].sum()),
            },
            "by_strike": [
                {
                    "strike": float(r.strike),
                    "net_dex": float(r.net_dex), "call_dex": float(r.call_dex), "put_dex": float(r.put_dex),
                    "net_tex": float(r.net_tex), "net_vex": float(r.net_vex),
                    "net_chex": float(r.net_chex), "net_vanna": float(r.net_vanna),
                }
                for r in by_strike.itertuples()
            ],
        }


class FeedRegistry:
    """dict[symbol -> SymbolFeed] con ref-count de subscriptores: el loop
    de un símbolo corre solo mientras haya al menos una conexión WS
    suscrita a él, y se detiene solo cuando la última se desconecta."""

    def __init__(self):
        self._feeds: dict[str, SymbolFeed] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, symbol: str, strikes_count: int = 20) -> SymbolFeed:
        async with self._lock:
            feed = self._feeds.get(symbol)
            if feed is None:
                feed = SymbolFeed(symbol, strikes_count)
                self._feeds[symbol] = feed
            feed.add_subscriber()
            feed.start()
            return feed

    async def unsubscribe(self, symbol: str) -> None:
        async with self._lock:
            feed = self._feeds.get(symbol)
            if feed is None:
                return
            feed.remove_subscriber()
            if not feed.has_subscribers:
                feed.stop()
                del self._feeds[symbol]

    def get(self, symbol: str) -> SymbolFeed | None:
        """Lectura sin efecto secundario (no suma/resta subscriptores) --
        para endpoints REST bajo demanda (ej. diagnóstico de IA) que solo
        necesitan leer el último estado calculado de un símbolo que YA
        tiene al menos una conexión WS activa."""
        return self._feeds.get(symbol)

    def active_feeds(self) -> list[SymbolFeed]:
        """Snapshot de los feeds con al menos un subscriptor ahora mismo --
        usado por snapshot_writer/quantower_pusher, que no dependen de
        ninguna conexión WS en particular (deben seguir funcionando aunque
        cambie qué símbolo mira cada usuario)."""
        return list(self._feeds.values())


feed_registry = FeedRegistry()

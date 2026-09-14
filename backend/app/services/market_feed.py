import asyncio
import logging
import time

import pandas as pd

from app.domain.gamma_price_profile import compute_gamma_price_profile
from app.domain.gex_math import compute_call_put_walls, compute_greeks_exposures, compute_zero_gamma, recalculate_gex_for_spot
from app.domain.metrics import compute_metrics_for_dte, get_nearest_dte_subset
from app.domain.oi_fallback import apply_volume_fallback_if_no_oi, merge_external_oi
from app.domain.signals import compute_signals, compute_squeeze_screener
from app.integrations.marketdata_client import fetch_oi_map
from app.integrations.schwab_client import fetch_option_chain
from app.domain.parsing import parse_schwab_chain

TICK_INTERVAL_SECONDS = 2
# Fase 1 (MVP GEX INFO): IV/T_exp simplificados a un valor fijo razonable.
# El cálculo real de atm_iv (mediana de IV cerca del spot) y T_exp (días a
# la expiración 0DTE real) se porta en Fase 2 junto con el resto de
# Griegas/paneles -- no bloquea tener GEX INFO funcionando en vivo.
DEFAULT_IV = 0.20
DEFAULT_T_EXP = 1 / 365

# GRID/Gamma Heatmap/3D SURFACE/3D VOL SURFACE agregan MUCHAS expiraciones
# a la vez (hasta 90 días out) -- el 'strikes_count' que llega de la UI
# (el mismo que el filtro visual "Strike range" de GEX INFO, pensado para
# UNA sola expiración cerca del spot) es demasiado angosto para eso: para
# una expiración a 60-79 días, el open interest real suele estar repartido
# en strikes bastante más lejos del spot actual de lo que ese rango
# -- resultado real reportado por el usuario: "el nuestro sale con casi
# nada de volumen en prácticamente todos los días" comparado con un
# heatmap de referencia con datos densos en muchas más expiraciones.
# Se pide una cadena aparte, bastante más ancha, en un fetch propio y
# periódico (no atado al tick de 2s de GEX INFO/GREEKS/Signals, para no
# multiplicar por ~4 el costo de Black-Scholes de CADA tick en el 0.1
# vCPU del free tier -- ver domain/gex_math.py).
DEEP_CHAIN_STRIKES_COUNT = 100
DEEP_CHAIN_INTERVAL_SECONDS = 45

# Símbolos que Schwab expone como índice cash-settled -- su endpoint de
# option chain solo los reconoce con "$" adelante ("$NDX", no "NDX"),
# confirmado en vivo contra la API real. El resto del sistema (feed
# registry, WS, string de TradingView, Firebase) sigue usando el símbolo
# "limpio" (sin "$") en todos lados -- este mapeo es la ÚNICA frontera
# donde se traduce, justo antes de llamarlo a Schwab.
INDEX_SYMBOLS = {"NDX", "SPX", "VIX"}

# Subconjunto de INDEX_SYMBOLS con fuente de Open Interest real disponible
# via MarketData.app (ver integrations/marketdata_client.py) -- SPX queda
# afuera hasta confirmar en vivo que ese simbolo tambien responde ahi, no
# se probo todavia. Para estos se fusiona OI real + spot en vivo de
# Schwab; el resto sigue con el fallback de volumen (oi_fallback.py).
MARKETDATA_OI_SYMBOLS = {"NDX", "VIX"}


def _schwab_query_symbol(display_symbol: str) -> str:
    return f"${display_symbol}" if display_symbol in INDEX_SYMBOLS else display_symbol


logger = logging.getLogger(__name__)


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
        # True cuando Schwab no da Open Interest real para este símbolo
        # (confirmado en vivo: NDX/SPX/VIX vuelven con OI=0 en TODA la
        # cadena, aunque QQQ/SPY sí lo tienen -- ver oi_fallback.py) y se
        # está usando volumen del día como aproximación en su lugar. La
        # UI/el prompt de la IA lo muestran como advertencia, no como
        # GEX real basado en posicionamiento acumulado.
        self.oi_is_volume_proxy: bool = False
        # Cadena ANCHA/lenta para GRID/Gamma Heatmap/3D SURFACE/3D VOL
        # SURFACE (ver DEEP_CHAIN_STRIKES_COUNT arriba) -- separada de
        # self.df (angosta/rápida, la que ya usan GEX INFO/GREEKS/Signals
        # en cada tick) para no pagar su costo de cálculo cada 2s.
        self.deep_df: pd.DataFrame = pd.DataFrame()
        self.deep_last_update: float = 0.0
        self._deep_task: asyncio.Task | None = None
        # Walls/Zero Gamma de TODAS las expiraciones combinadas (a
        # diferencia de "walls" en gex_info_payload, que siempre es solo
        # la expiración más cercana/0DTE) -- el "Call Resistance/Put
        # Support" macro de Aleks Rosme: rango semanal/mensual, mucho más
        # estable día a día que los niveles 0DTE. Se recalcula junto con
        # deep_df (cada DEEP_CHAIN_INTERVAL_SECONDS), reusando
        # compute_metrics_for_dte tal cual -- no hace falta lógica nueva.
        self.macro_levels: dict = {}
        # IV ATM / percentile: se recalculan UNA vez por tick acá (no por
        # conexión en gex_info_payload) porque no varían con el
        # strike_range de cada usuario -- son una lectura de mercado
        # global, igual que el VIX. Mismo cálculo que compute_metrics_for_dte
        # usa para el prompt de la IA, para que la barra de métricas y el
        # análisis de la IA vean exactamente el mismo número.
        self.iv_str: str = "--"
        self.iv_rank_str: str = "N/A"
        self.atm_iv: float = 0.20
        # Una vez que iv_percentile.py logra calcular un percentil real
        # contra historial de Supabase (ver update_real_iv_percentile),
        # _recalculate() deja de pisarlo con la fórmula estimada en cada
        # tick -- si no, el resultado real duraría 2 segundos en pantalla
        # antes de que el próximo tick lo reemplace por la estimación.
        self._iv_rank_is_real: bool = False

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
        if self._deep_task is None or self._deep_task.done():
            self._deep_task = asyncio.create_task(self._deep_run_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._deep_task is not None:
            self._deep_task.cancel()
            self._deep_task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick_once()
            except Exception:
                # Esto se tragaba en silencio, sin loggear nada -- cuando
                # _tick_once falla de forma sostenida (ej. problema con el
                # token de Schwab), el único síntoma visible para el
                # usuario es "EN VIVO" prendido pero ningún dato llega
                # nunca, sin ningún indicio de por qué en ningún lado. Se
                # loggea acá (Render lo captura en sus logs) para poder
                # diagnosticar la causa real la próxima vez que pase, en
                # vez de tener que reproducirlo a ciegas.
                # TODO Fase 4: además, loggear a console_logs (Supabase).
                logger.exception("Error en el tick de %s -- schwab_online=False hasta el próximo intento.", self.symbol)
                self.schwab_online = False
            await asyncio.sleep(TICK_INTERVAL_SECONDS)

    async def _deep_run_loop(self) -> None:
        while True:
            try:
                await self._deep_tick_once()
            except Exception:
                logger.exception("Error en el tick DEEP (GRID/Gamma Heatmap/3D SURFACE) de %s -- se reintenta en el próximo ciclo.", self.symbol)
            await asyncio.sleep(DEEP_CHAIN_INTERVAL_SECONDS)

    async def _deep_tick_once(self) -> None:
        chain = await fetch_option_chain(_schwab_query_symbol(self.symbol), DEEP_CHAIN_STRIKES_COUNT)
        df, _ = parse_schwab_chain(chain)
        spot = float(chain.get('underlyingPrice') or 0.0) if isinstance(chain, dict) else 0.0
        if df.empty or spot <= 0:
            return
        # Mismo criterio que _tick_once (ver comentario ahí abajo): OI real
        # de MarketData.app si el símbolo lo soporta, si no el fallback de
        # volumen -- sin esto, GRID/Gamma Heatmap/3D SURFACE quedan igual
        # de vacíos que GEX INFO para NDX/SPX/VIX.
        if self.symbol in MARKETDATA_OI_SYMBOLS:
            oi_map = await fetch_oi_map(self.symbol)
            if oi_map:
                df = merge_external_oi(df, oi_map)
            else:
                df, _ = apply_volume_fallback_if_no_oi(df)
        else:
            df, _ = apply_volume_fallback_if_no_oi(df)
        # Un solo recalculate_gex_for_spot alcanza -- GRID/Heatmap/3D
        # SURFACE solo necesitan net_gex/call_gex/put_gex por strike, no
        # las Griegas completas (eso sigue siendo exclusivo de self.df).
        self.deep_df = recalculate_gex_for_spot(df, spot_t=spot, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)
        self.deep_last_update = time.time()

        # Walls "all-expiry" (Call Resistance/Put Support macro, ver
        # comentario en __init__) -- se calculan acá, no en _tick_once,
        # porque necesitan TODAS las expiraciones que trae deep_df
        # (self.df, la cadena angosta de cada tick de 2s, normalmente solo
        # cubre 1-2 expiraciones cercanas).
        exp_keys_all = list(self.deep_df['exp_key'].unique()) if 'exp_key' in self.deep_df.columns else []
        macro = compute_metrics_for_dte(self.deep_df, exp_keys_all, spot)
        self.macro_levels = {
            "cw1": macro["cw1"], "cw2": macro["cw2"], "cw3": macro["cw3"],
            "pw1": macro["pw1"], "pw2": macro["pw2"], "pw3": macro["pw3"],
            "zero_gamma": macro["zero_gamma"],
        }

    async def _tick_once(self) -> None:
        chain = await fetch_option_chain(_schwab_query_symbol(self.symbol), self.strikes_count)
        df, exp0 = parse_schwab_chain(chain)

        spot = float(chain.get('underlyingPrice') or 0.0) if isinstance(chain, dict) else 0.0
        if df.empty or spot <= 0:
            self.schwab_online = False
            return

        # NDX/SPX/VIX (productos de índice exclusivos de CBOE) no traen
        # Open Interest real de Schwab -- confirmado en vivo, 0 de
        # cientos de contratos con OI>0, mismo instante en que QQQ/SPY sí
        # lo tenían. Sin esto, gamma * OI da cero en TODOS los strikes:
        # GEX INFO se veía completamente vacío para esos símbolos.
        # Para NDX/VIX se fusiona el OI REAL de MarketData.app (gratis,
        # sin tarjeta, sin KYC de USA -- ver integrations/marketdata_client.py)
        # con la estructura de la cadena + spot EN VIVO de Schwab: el OI
        # no necesita ser en vivo (se actualiza una sola vez por noche vía
        # OCC), así que fusionarlo cada 15 min con el spot que sí se
        # actualiza cada 2s da un GEX tan real como el de QQQ/SPY. Si esa
        # fuente falla (rate limit, caída, símbolo sin key configurada) se
        # cae al viejo fallback de volumen del día como aproximación.
        if self.symbol in MARKETDATA_OI_SYMBOLS:
            oi_map = await fetch_oi_map(self.symbol)
            if oi_map:
                df = merge_external_oi(df, oi_map)
                self.oi_is_volume_proxy = False
            else:
                df, self.oi_is_volume_proxy = apply_volume_fallback_if_no_oi(df)
        else:
            df, self.oi_is_volume_proxy = apply_volume_fallback_if_no_oi(df)

        df = recalculate_gex_for_spot(df, spot_t=spot, t_exp=DEFAULT_T_EXP, iv=DEFAULT_IV)
        df = compute_greeks_exposures(df, spot_price=spot, t_exp=DEFAULT_T_EXP, atm_iv=DEFAULT_IV)

        self.df = df
        self.spot_price = spot
        self.nearest_exp_key = exp0
        self.schwab_online = True
        self.last_update = time.time()

        metrics = compute_metrics_for_dte(df, [exp0] if exp0 else [], spot)
        self.iv_str = metrics['iv_str']
        self.atm_iv = metrics['atm_iv']
        if not self._iv_rank_is_real:
            self.iv_rank_str = metrics['iv_rank_str']

    def nearest_dte_strikes(self) -> list[float]:
        """Strikes únicos (ordenados) de la expiración más cercana -- lo
        usa ws_market.ConnectionState.strike_window() para convertir
        'strike_range' (pensado como "N strikes arriba/abajo del ATM",
        el mismo significado que ya tiene como strikes_count del fetch a
        Schwab) en un rango de PRECIO real por RANGO/POSICIÓN, nunca por
        una resta de dólares fija -- un ±25 en dólares tiene sentido para
        QQQ (strikes de ~1 USD) pero deja el gráfico vacío en NDX (strikes
        de 25-100 USD) o distorsionado en VIX (strikes de 0.5-1 USD)."""
        if self.df.empty:
            return []
        df_nearest = get_nearest_dte_subset(self.df)
        return sorted(df_nearest['strike'].unique().tolist())

    def gex_info_payload(self, min_strike: float | None = None, max_strike: float | None = None) -> dict:
        """Slice ya agrupado/filtrado listo para mandar por WS: nearest-DTE
        por defecto, opcionalmente recortado a [min_strike, max_strike]."""
        if self.df.empty:
            return {
                "net_gex_total": 0.0, "call_gex_total": 0.0, "put_gex_total": 0.0,
                "flip_level": self.spot_price,
                "walls": {"cw1": self.spot_price, "cw2": self.spot_price, "cw3": self.spot_price,
                          "pw1": self.spot_price, "pw2": self.spot_price, "pw3": self.spot_price},
                "iv_str": "--", "iv_rank_str": "N/A",
                "by_strike": [],
                "price_profile": {"prices": [], "net_gamma": []},
                "oi_is_volume_proxy": self.oi_is_volume_proxy,
                "macro_levels": self.macro_levels,
            }

        df_nearest_full = get_nearest_dte_subset(self.df)
        df_nearest = df_nearest_full
        if min_strike is not None and max_strike is not None:
            df_nearest = df_nearest[(df_nearest['strike'] >= min_strike) & (df_nearest['strike'] <= max_strike)]

        by_strike = df_nearest.groupby('strike', as_index=False)[['call_gex', 'put_gex', 'net_gex']].sum().sort_values('strike')

        cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, self.spot_price)
        zero_gamma = compute_zero_gamma(by_strike, self.spot_price)

        # Gamma Price Profile: SIEMPRE con la cadena completa (no recortada
        # por strike_range) -- un strike hoy fuera de la ventana visible
        # puede ser justo el que domina la curva en un precio hipotético
        # cercano a él.
        price_profile = compute_gamma_price_profile(df_nearest_full, self.spot_price, DEFAULT_T_EXP, DEFAULT_IV)

        return {
            "net_gex_total": float(by_strike['net_gex'].sum()),
            "call_gex_total": float(by_strike['call_gex'].sum()),
            "put_gex_total": float(by_strike['put_gex'].sum()),
            "flip_level": zero_gamma,
            "walls": {"cw1": cw1, "cw2": cw2, "cw3": cw3, "pw1": pw1, "pw2": pw2, "pw3": pw3},
            "iv_str": self.iv_str, "iv_rank_str": self.iv_rank_str,
            "by_strike": [
                {"strike": float(r.strike), "net_gex": float(r.net_gex), "call_gex": float(r.call_gex), "put_gex": float(r.put_gex)}
                for r in by_strike.itertuples()
            ],
            "price_profile": price_profile,
            "oi_is_volume_proxy": self.oi_is_volume_proxy,
            # Call Resistance/Put Support de TODAS las expiraciones (ver
            # self.macro_levels en __init__) -- distinto de "walls" arriba,
            # que siempre es solo la expiración más cercana/0DTE. Puede
            # llegar vacío ({}) hasta el primer tick DEEP (máx
            # DEEP_CHAIN_INTERVAL_SECONDS después de conectar).
            "macro_levels": self.macro_levels,
        }

    def signals_payload(self) -> dict:
        """Panel de Señales + Gamma Squeeze Screener de GEX INFO (ver
        domain/signals.py) -- SIN recortar por strike_range: a diferencia
        del gráfico de barras, estos niveles clave (Magnet, Resistance,
        etc.) pueden caer fuera de la ventana que el usuario eligió para
        visualizar y siguen siendo información válida."""
        empty = {"signals": [], "squeeze": {"direction": None, "state": None, "probability": None, "factors": [], "key_levels": {}}}
        if self.df.empty:
            return empty

        df_nearest = get_nearest_dte_subset(self.df)
        agg_cols = ['call_gex', 'put_gex', 'net_gex', 'openInterest_c', 'openInterest_p', 'volume_c', 'volume_p', 'net_dex']
        agg_map = {c: 'sum' for c in agg_cols if c in df_nearest.columns}
        if not agg_map:
            return empty
        by_strike = df_nearest.groupby('strike', as_index=False).agg(agg_map).sort_values('strike')

        cw1, cw2, cw3, pw1, pw2, pw3 = compute_call_put_walls(by_strike, self.spot_price)
        zero_gamma = compute_zero_gamma(by_strike, self.spot_price)
        walls = {"cw1": cw1, "cw2": cw2, "cw3": cw3, "pw1": pw1, "pw2": pw2, "pw3": pw3, "zero_gamma": zero_gamma}
        net_dex_total = float(by_strike['net_dex'].sum()) if 'net_dex' in by_strike.columns else 0.0

        return {
            "signals": compute_signals(by_strike, self.spot_price, walls),
            "squeeze": compute_squeeze_screener(by_strike, self.spot_price, walls, net_dex_total),
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
            elif strikes_count > feed.strikes_count:
                # Bug real: el feed de un símbolo es COMPARTIDO entre
                # todos los que lo miran (ref-count, un solo fetch a
                # Schwab por símbolo) -- antes 'strikes_count' solo se
                # usaba al CREAR el feed, así que el segundo usuario que
                # pedía un rango más ancho para el mismo símbolo quedaba
                # silenciosamente recortado al rango del primero, sin
                # ningún error. Se ensancha el feed compartido al máximo
                # rango pedido por cualquier suscriptor activo -- nunca se
                # achica solo (si el suscriptor ancho se va, el feed queda
                # más ancho de lo estrictamente necesario, un costo menor
                # y aceptable frente a recortar datos que alguien pidió).
                feed.strikes_count = strikes_count
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

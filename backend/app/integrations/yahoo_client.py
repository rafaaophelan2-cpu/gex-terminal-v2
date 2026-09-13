import logging
import time

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# PRUEBA (temporal): Yahoo Finance SÍ tiene Open Interest real por strike
# para NDX/VIX (confirmado en vivo -- Schwab no lo tiene, ver
# oi_fallback.py), pero cerró el acceso directo a su API pública (exige
# un "crumb" + cookies de sesión que solo se resuelven confiablemente
# simulando un navegador real). Este módulo scrapea la página de opciones
# vía un Chromium headless e intercepta la respuesta JSON que la propia
# página ya pide -- el objetivo INMEDIATO es solo confirmar si el free
# tier de Render (0.1 vCPU / 512MB) aguanta correr un navegador sin
# tirar abajo el resto del servicio. Si no aguanta, se saca por completo.
YAHOO_INDEX_PREFIX = {"VIX": "^VIX", "NDX": "^NDX", "SPX": "^SPX"}


async def fetch_yahoo_option_chain_raw(symbol: str) -> dict | None:
    """Devuelve el JSON crudo de optionChain de Yahoo Finance para 'symbol'
    (VIX/NDX/SPX -- se traduce solo al símbolo con "^" que usa Yahoo para
    índices), o None si el scrape falla por cualquier motivo."""
    yahoo_symbol = YAHOO_INDEX_PREFIX.get(symbol, symbol)
    url = f"https://finance.yahoo.com/quote/{yahoo_symbol}/options/"

    captured: dict = {}
    start = time.monotonic()

    async def _on_response(resp):
        if "/v7/finance/options/" in resp.url:
            try:
                captured["json"] = await resp.json()
            except Exception:
                pass

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--disable-gpu", "--no-sandbox"])
            try:
                page = await browser.new_page()
                page.on("response", _on_response)
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(4000)
            finally:
                await browser.close()
    except Exception:
        logger.exception("fetch_yahoo_option_chain_raw(%s) falló.", symbol)
        return None

    elapsed = time.monotonic() - start
    logger.info("fetch_yahoo_option_chain_raw(%s) tardó %.1fs -- encontró data=%s", symbol, elapsed, "json" in captured)
    return captured.get("json")

import re

# Finnhub (/news?category=general, ver integrations/finnhub_client.py) NO
# trae qué ticker impacta cada noticia -- a diferencia de herramientas
# como FinancialJuice, que taggean cada item a mano/con su propio motor
# (ej. "Energy, US Bonds, US Indexes, USD" en las capturas que pegó el
# usuario). Sin ese dato, "solo noticias que impactan a QQQ o NQ" (pedido
# explícito del usuario) se resuelve acá con una heurística por palabras
# clave sobre headline+summary -- no es un clasificador perfecto: puede
# dejar pasar algo borderline o perderse algo con wording raro, pero es
# lo mejor que se puede hacer con una fuente gratis sin tageo por ticker.
#
# Cubre los mismos temas que ya aparecen tageados en las capturas del
# usuario (Fed/tasas, petróleo-geopolítica, USD/Treasuries) más lo que
# mueve puntualmente a Nasdaq-100/tech (los pesos más grandes de QQQ).
QQQ_NQ_KEYWORDS = {
    # Fed / tasas / macro EE.UU.
    "fed", "federal reserve", "fomc", "powell", "rate cut", "rate hike",
    "interest rate", "rate decision", "cpi", "inflation", "ppi",
    "jobs report", "nonfarm payroll", "unemployment", "jobless claims",
    "gdp", "pce",
    # Índices / mercado en general
    "nasdaq", "s&p 500", "s&p500", "dow jones", "wall street",
    "stock market", "stocks", "equities", "sell-off", "selloff", "rally",
    "correction", "bear market", "bull market", "recession", "crash",
    # Big tech / semis / IA (los pesos más grandes de QQQ)
    "apple", "microsoft", "nvidia", "amazon", "meta", "alphabet",
    "google", "tesla", "broadcom", "amd", "chip", "semiconductor",
    "artificial intelligence", "ai", "tech stocks", "big tech",
    "earnings",
    # Petróleo / geopolítica (mueve risk sentiment -> Nasdaq futures)
    "oil", "crude", "opec", "iran", "israel", "russia", "ukraine",
    "hormuz", "war", "attack", "attacks", "attacked", "invasion",
    "sanctions", "sanction", "tariff", "china", "emergency", "nuclear",
    "default",
    # USD / bonos (VIX/NQ correlacionan con esto)
    "treasury", "yield", "dollar", "usd", "bond market",
}

# Subconjunto más chico y severo -- lo que en un calendario tipo
# FinancialJuice se pintaría directamente en rojo (folder de máximo
# impacto), no solo naranja/relevante.
HIGH_IMPACT_KEYWORDS = {
    "war", "attack", "attacks", "attacked", "invasion", "crash",
    "rate hike", "rate cut", "fed decision", "rate decision", "recession",
    "default", "sanction", "sanctions", "emergency", "nuclear",
}


# Word-boundary, no simple substring -- confirmado con un caso real: "war"
# (QQQ_NQ_KEYWORDS) matcheaba dentro de "award" con un `in` plano, lo que
# colaba noticias totalmente irrelevantes. \b funciona igual para frases
# con espacio adentro ("rate cut") -- el boundary es sobre el string
# completo del patrón, no entre cada palabra interna.
def _build_pattern(keywords: set[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b")


_RELEVANT_PATTERN = _build_pattern(QQQ_NQ_KEYWORDS)
_HIGH_IMPACT_PATTERN = _build_pattern(HIGH_IMPACT_KEYWORDS)


def filter_relevant_news(articles: list[dict]) -> list[dict]:
    """Filtra 'articles' (ver fetch_market_news) a los que probablemente
    impactan QQQ/NQ según QQQ_NQ_KEYWORDS, y le suma "important": bool a
    cada uno que sobrevive según HIGH_IMPACT_KEYWORDS -- ver el
    disclaimer arriba, es una heurística, no un clasificador real."""
    result: list[dict] = []
    for article in articles:
        headline = article.get("headline") or ""
        summary = article.get("summary") or ""
        text = f"{headline} {summary}".lower()

        if not _RELEVANT_PATTERN.search(text):
            continue

        result.append({**article, "important": bool(_HIGH_IMPACT_PATTERN.search(text))})

    return result

"""
Google News Sentiment Scanner
Scans Google News RSS for each market every 30 minutes.
Extracts headlines, classifies sentiment, blocks trades against bad news.

Based on Zoran's spec: "Google News scanned each market. Contradicts signal = BLOCKED"
"""
import logging
import time
import re
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Keyword mappings for each market
MARKET_KEYWORDS = {
    'BTC': ['bitcoin', 'btc', 'crypto market'],
    'ETH': ['ethereum', 'eth', 'ether'],
    'SOL': ['solana', 'sol crypto'],
    'XRP': ['ripple', 'xrp'],
    'AVAX': ['avalanche', 'avax'],
    'SUI': ['sui crypto', 'sui network'],
    'XAU': ['gold price', 'gold market', 'xau'],
    'XAG': ['silver price', 'silver market'],
    'WTI': ['oil price', 'wti crude', 'crude oil'],
    'BRENT': ['brent crude', 'brent oil'],
    'GAS': ['natural gas price', 'natgas'],
    'SPX': ['s&p 500', 'sp500', 'stock market'],
    'NVDA': ['nvidia', 'nvda'],
    'TSLA': ['tesla', 'tsla'],
    'AAPL': ['apple stock', 'aapl'],
    'MSFT': ['microsoft', 'msft'],
    'META': ['meta platforms', 'meta stock', 'facebook stock'],
    'AMZN': ['amazon stock', 'amzn'],
    'GOOGL': ['google stock', 'alphabet', 'googl'],
    'NFLX': ['netflix', 'nflx'],
    'MSTR': ['microstrategy', 'mstr'],
    'PLTR': ['palantir', 'pltr'],
}

# Bearish keywords in headlines
BEARISH_WORDS = [
    'crash', 'plunge', 'dump', 'sell-off', 'selloff', 'tank', 'tumble',
    'collapse', 'fear', 'recession', 'bearish', 'downgrade', 'warn',
    'crisis', 'panic', 'loss', 'losses', 'drop', 'drops', 'fell',
    'decline', 'slump', 'worst', 'risk', 'ban', 'fraud', 'hack',
    'lawsuit', 'fine', 'penalty', 'investigation', 'sec charges',
]

# Bullish keywords in headlines
BULLISH_WORDS = [
    'surge', 'rally', 'boom', 'soar', 'jump', 'bullish', 'upgrade',
    'record high', 'all-time high', 'ath', 'breakout', 'moon',
    'approval', 'approved', 'partnership', 'deal', 'acquisition',
    'beat expectations', 'earnings beat', 'strong earnings',
    'institutional', 'adoption', 'etf approved', 'buy signal',
]


@dataclass
class NewsSentiment:
    ticker: str
    bias: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    score: int = 0         # -5 to +5
    headlines: list = field(default_factory=list)
    last_updated: float = 0.0
    error: str = ""


class GoogleNewsSentiment:
    """Scans Google News RSS for market sentiment."""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.enabled = cfg.get('enabled', True)
        self.refresh_seconds = cfg.get('refresh_seconds', 1800)  # 30 min
        self.block_on_conflict = cfg.get('block_on_conflict', True)
        self.min_block_score = cfg.get('min_block_score', 3)  # Score magnitude to block

        # Cache: {ticker: NewsSentiment}
        self._cache: dict[str, NewsSentiment] = {}

    def get_sentiment(self, ticker: str) -> NewsSentiment:
        """Get cached sentiment for a ticker, refresh if stale."""
        cached = self._cache.get(ticker)
        now = time.time()

        if cached and (now - cached.last_updated) < self.refresh_seconds:
            return cached

        # Refresh
        sentiment = self._fetch_news(ticker)
        self._cache[ticker] = sentiment
        return sentiment

    def should_block(self, ticker: str, direction: str) -> tuple[bool, str]:
        """
        News NEVER blocks trades (Option C: confirm-only mode).
        Zoran discovery: keyword-based headline sentiment creates noise,
        blocks valid chart setups. The chart already captures reality.
        News only adds bonus points via score_adjustment().
        
        Returns (False, "") always — kept for API compatibility.
        """
        return False, ""

    def score_adjustment(self, ticker: str, direction: str) -> tuple[int, str]:
        """
        Option C: News confirms but never penalizes.
        +1 bonus if news aligns with direction. 0 if neutral or opposing.
        Never -1. The chart is king — news is just a tailwind.
        """
        if not self.enabled:
            return 0, ""

        sentiment = self.get_sentiment(ticker)

        if sentiment.bias == "NEUTRAL" or abs(sentiment.score) < 2:
            return 0, ""

        # Confirmation bonus only — news aligns with trade direction
        if (direction == "LONG" and sentiment.bias == "BULLISH") or \
           (direction == "SHORT" and sentiment.bias == "BEARISH"):
            return 1, f"📰 News confirms {direction} ({sentiment.bias}, score={sentiment.score}) — +1 bonus"

        # Opposing news = no penalty, just log it
        if (direction == "LONG" and sentiment.bias == "BEARISH") or \
           (direction == "SHORT" and sentiment.bias == "BULLISH"):
            logger.debug(f"[NEWS] {ticker}: news opposes {direction} ({sentiment.bias}) — ignored (chart > headlines)")
            return 0, ""

        return 0, ""

    def _fetch_news(self, ticker: str) -> NewsSentiment:
        """Fetch Google News RSS for a ticker and analyze sentiment."""
        keywords = MARKET_KEYWORDS.get(ticker, [ticker.lower()])
        query = keywords[0]  # Use primary keyword

        result = NewsSentiment(ticker=ticker, last_updated=time.time())

        try:
            url = f"https://news.google.com/rss/search?q={urllib.request.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
            })
            response = urllib.request.urlopen(req, timeout=10)
            xml_data = response.read().decode('utf-8')

            root = ET.fromstring(xml_data)
            items = root.findall('.//item')[:10]  # Last 10 headlines

            bullish_count = 0
            bearish_count = 0

            for item in items:
                title = item.find('title')
                if title is not None and title.text:
                    headline = title.text.lower()
                    result.headlines.append(title.text)

                    for word in BEARISH_WORDS:
                        if word in headline:
                            bearish_count += 1
                            break

                    for word in BULLISH_WORDS:
                        if word in headline:
                            bullish_count += 1
                            break

            # Calculate sentiment score (-5 to +5)
            result.score = min(5, bullish_count) - min(5, bearish_count)

            if result.score >= 2:
                result.bias = "BULLISH"
            elif result.score <= -2:
                result.bias = "BEARISH"
            else:
                result.bias = "NEUTRAL"

            logger.info(f"[NEWS] {ticker}: {result.bias} (score={result.score}, bull={bullish_count}, bear={bearish_count})")

        except Exception as e:
            result.error = str(e)
            logger.warning(f"[NEWS] {ticker}: fetch failed — {e}")

        return result

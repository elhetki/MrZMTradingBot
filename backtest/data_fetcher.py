"""
Historical Data Fetcher for Backtesting
Fetches 1m and 5m candles from Hyperliquid Info API (no auth needed).
Handles pagination for 6+ months of data.
"""

from __future__ import annotations
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import requests

logger = logging.getLogger(__name__)

# Hyperliquid public API endpoint
HL_API_URL = "https://api.hyperliquid.xyz/info"

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}

INTERVAL_HL = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
}

# Max candles per request (Hyperliquid limit ~5000)
MAX_CANDLES_PER_REQUEST = 5000


class HistoricalDataFetcher:
    """
    Fetches historical OHLCV candles from Hyperliquid.
    Handles pagination to retrieve months of data.
    """

    def __init__(self, base_url: str = HL_API_URL, rate_limit_ms: int = 200):
        self.base_url = base_url
        self.rate_limit_ms = rate_limit_ms  # ms between requests

    def fetch(
        self,
        ticker: str,
        interval: str = "5m",
        months: int = 6,
        end_time: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical candles for a ticker.

        Args:
            ticker: Market symbol (e.g., 'BTC', 'ETH')
            interval: Candle interval ('1m', '5m', '15m', '1h')
            months: How many months back to fetch
            end_time: End time (defaults to now)

        Returns:
            DataFrame with OHLCV data, indexed by timestamp
        """
        if end_time is None:
            end_time = datetime.utcnow()

        start_time = end_time - timedelta(days=months * 30)

        logger.info(
            f"Fetching {ticker} {interval} candles: "
            f"{start_time.strftime('%Y-%m-%d')} → {end_time.strftime('%Y-%m-%d')}"
        )

        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        interval_ms = INTERVAL_MS.get(interval, 300_000)
        hl_interval = INTERVAL_HL.get(interval, "5")

        all_candles: list[pd.DataFrame] = []
        current_start = start_ms
        request_count = 0

        while current_start < end_ms:
            current_end = min(current_start + MAX_CANDLES_PER_REQUEST * interval_ms, end_ms)

            df = self._fetch_chunk(ticker, hl_interval, current_start, current_end)
            if df is not None and not df.empty:
                all_candles.append(df)
                last_ts = int(df.index[-1].timestamp() * 1000)
                current_start = last_ts + interval_ms
            else:
                # Skip ahead if no data returned
                current_start = current_end + interval_ms

            request_count += 1
            if request_count % 10 == 0:
                logger.info(f"  Progress: {len(all_candles)} chunks fetched...")

            # Rate limiting
            time.sleep(self.rate_limit_ms / 1000)

        if not all_candles:
            logger.warning(f"No historical data found for {ticker} {interval}")
            return None

        df = pd.concat(all_candles)
        df = df[~df.index.duplicated(keep="last")]
        df.sort_index(inplace=True)

        logger.info(
            f"Fetched {len(df)} candles for {ticker} {interval} "
            f"({start_time.strftime('%Y-%m-%d')} → {end_time.strftime('%Y-%m-%d')})"
        )
        return df

    def _fetch_chunk(
        self,
        ticker: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> Optional[pd.DataFrame]:
        """Fetch a single chunk of candles."""
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": ticker,
                "interval": interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }

        try:
            resp = requests.post(
                self.base_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            candles_raw = resp.json()

            if not candles_raw:
                return None

            return self._parse(candles_raw)

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP error fetching {ticker}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing candles for {ticker}: {e}")
            return None

    def _parse(self, raw: list) -> pd.DataFrame:
        """Parse raw candle list into DataFrame."""
        records = []
        for c in raw:
            records.append({
                "timestamp": pd.Timestamp(c["t"], unit="ms", tz="UTC"),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
                "trades": int(c.get("n", 0)),
            })

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        return df

    def fetch_multiple(
        self,
        tickers: list[str],
        interval: str = "5m",
        months: int = 6,
    ) -> dict[str, pd.DataFrame]:
        """Fetch historical data for multiple tickers."""
        results = {}
        for ticker in tickers:
            logger.info(f"Fetching {ticker}...")
            df = self.fetch(ticker, interval, months)
            if df is not None:
                results[ticker] = df
            time.sleep(0.5)  # Be nice to the API
        return results

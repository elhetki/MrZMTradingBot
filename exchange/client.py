"""
Hyperliquid Exchange Client
Wraps the hyperliquid-python-sdk for:
  - Market data (candles, orderbook, price) — no auth needed
  - Order placement — requires API key
  - Testnet support via TESTNET_API_URL
"""

from __future__ import annotations
import logging
import time
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Hyperliquid candle interval map
INTERVAL_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "240",
    "1d": "D",
}


class HyperliquidClient:
    """
    Unified client for Hyperliquid API.
    Supports read-only (no auth) and trading (with API key) modes.
    """

    def __init__(self, config: dict):
        self.config = config
        self.dry_run = config.get("dry_run", True)
        self.testnet = config.get("testnet", False)
        self._info = None
        self._exchange = None
        self._connected = False
        self._init_client()

    def _init_client(self):
        """Initialize the Hyperliquid SDK clients."""
        try:
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants

            base_url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL

            # Info API — always available (no auth)
            self._info = Info(base_url=base_url, skip_ws=True)

            # Exchange API — only when NOT dry run and keys provided
            if not self.dry_run:
                wallet_address = self.config.get("wallet_address", "")
                private_key = self.config.get("private_key", "")
                if wallet_address and private_key:
                    self._exchange = Exchange(
                        wallet=private_key,
                        base_url=base_url,
                    )
                    logger.info("Exchange API initialized (LIVE MODE)")
                else:
                    logger.warning("No wallet credentials — order placement disabled")

            self._connected = True
            mode = "TESTNET" if self.testnet else "MAINNET"
            run_mode = "DRY RUN" if self.dry_run else "LIVE"
            logger.info(f"Hyperliquid client connected: {mode} | {run_mode}")

        except ImportError:
            logger.error("hyperliquid-python-sdk not installed. Run: pip install hyperliquid-python-sdk")
            self._connected = False
        except Exception as e:
            logger.error(f"Failed to initialize Hyperliquid client: {e}")
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._info is not None

    # ──────────────────────── Market Data ────────────────────────

    def get_candles(
        self,
        ticker: str,
        interval: str = "5m",
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV candles from Hyperliquid Info API.

        Args:
            ticker: Market symbol (e.g., 'BTC', 'ETH')
            interval: Candle interval ('1m', '5m', '15m', '1h', etc.)
            limit: Number of candles to fetch
            start_time: Start timestamp in milliseconds (optional)
            end_time: End timestamp in milliseconds (optional)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if not self.is_connected():
            logger.error("Not connected to Hyperliquid")
            return None

        hl_interval = INTERVAL_MAP.get(interval, "5")

        try:
            now_ms = int(time.time() * 1000)
            interval_ms = self._interval_to_ms(interval)

            if end_time is None:
                end_time = now_ms
            if start_time is None:
                start_time = end_time - (limit * interval_ms)

            candles_raw = self._info.candles_snapshot(
                name=ticker,
                interval=hl_interval,
                startTime=start_time,
                endTime=end_time,
            )

            if not candles_raw:
                logger.warning(f"No candles returned for {ticker} {interval}")
                return None

            df = self._parse_candles(candles_raw)
            return df

        except Exception as e:
            logger.error(f"Error fetching candles for {ticker}: {e}")
            return None

    def _parse_candles(self, raw: list) -> pd.DataFrame:
        """Parse raw Hyperliquid candle data into a DataFrame."""
        records = []
        for c in raw:
            # Hyperliquid candle format: {t, T, s, i, o, c, h, l, v, n}
            records.append({
                "timestamp": pd.Timestamp(c["t"], unit="ms", tz="UTC"),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
                "trades": int(c.get("n", 0)),
            })

        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _interval_to_ms(self, interval: str) -> int:
        """Convert interval string to milliseconds."""
        mapping = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
            "1d": 86_400_000,
        }
        return mapping.get(interval, 300_000)

    def get_price(self, ticker: str) -> Optional[float]:
        """Get current mid price for a ticker."""
        if not self.is_connected():
            return None
        try:
            # Get L2 orderbook and return mid
            book = self._info.l2_snapshot(ticker)
            if book and "levels" in book:
                bids = book["levels"][0]
                asks = book["levels"][1]
                if bids and asks:
                    best_bid = float(bids[0]["px"])
                    best_ask = float(asks[0]["px"])
                    return (best_bid + best_ask) / 2
            # Fallback: use all mids
            mids = self._info.all_mids()
            return float(mids.get(ticker, 0)) or None
        except Exception as e:
            logger.error(f"Error getting price for {ticker}: {e}")
            return None

    def get_all_prices(self) -> dict[str, float]:
        """Get all current mid prices."""
        if not self.is_connected():
            return {}
        try:
            mids = self._info.all_mids()
            return {k: float(v) for k, v in mids.items()}
        except Exception as e:
            logger.error(f"Error getting all prices: {e}")
            return {}

    def get_orderbook(self, ticker: str, depth: int = 5) -> Optional[dict]:
        """Get L2 orderbook snapshot."""
        if not self.is_connected():
            return None
        try:
            return self._info.l2_snapshot(ticker)
        except Exception as e:
            logger.error(f"Error getting orderbook for {ticker}: {e}")
            return None

    def get_user_state(self, wallet_address: str) -> Optional[dict]:
        """Get user account state (balance, positions)."""
        if not self.is_connected():
            return None
        try:
            return self._info.user_state(wallet_address)
        except Exception as e:
            logger.error(f"Error getting user state: {e}")
            return None

    # ──────────────────────── Order Placement ────────────────────────

    def place_market_order(
        self,
        ticker: str,
        direction: str,
        size: float,
        leverage: int,
        slippage_limit_pct: float = 0.01,
    ) -> Optional[dict]:
        """
        Place a market order.
        In dry run mode, this is a no-op (handled by DryRunEngine).

        Args:
            ticker: Market symbol
            direction: 'LONG' or 'SHORT'
            size: Size in base asset units
            leverage: Leverage multiplier
            slippage_limit_pct: Max acceptable slippage

        Returns:
            Order response dict or None
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Market order: {direction} {size} {ticker} @ {leverage}x")
            return {"status": "dry_run", "ticker": ticker, "direction": direction, "size": size}

        if self._exchange is None:
            logger.error("Exchange not initialized — cannot place order")
            return None

        try:
            is_buy = direction == "LONG"
            # Use slippage-aware price
            price = self.get_price(ticker)
            if price is None:
                return None

            result = self._exchange.market_open(
                name=ticker,
                is_buy=is_buy,
                sz=size,
                px=None,  # market order
                slippage=slippage_limit_pct,
            )
            logger.info(f"Order placed: {direction} {size} {ticker} | Result: {result}")
            return result

        except Exception as e:
            logger.error(f"Error placing order for {ticker}: {e}")
            return None

    def close_position(
        self,
        ticker: str,
        direction: str,
        size: float,
        fraction: float = 1.0,
    ) -> Optional[dict]:
        """
        Close a position (fully or partially).
        In dry run mode, this is a no-op (handled by DryRunEngine).
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Close position: {ticker} {direction} size={size} fraction={fraction:.2f}")
            return {"status": "dry_run", "action": "close"}

        if self._exchange is None:
            logger.error("Exchange not initialized")
            return None

        try:
            close_size = size * fraction
            is_buy = direction == "SHORT"  # Close short = buy
            result = self._exchange.market_close(
                name=ticker,
                sz=close_size,
            )
            return result
        except Exception as e:
            logger.error(f"Error closing position for {ticker}: {e}")
            return None

    def set_leverage(self, ticker: str, leverage: int, is_cross: bool = False) -> bool:
        """Set leverage for a market."""
        if self.dry_run:
            return True
        if self._exchange is None:
            return False
        try:
            self._exchange.update_leverage(leverage, ticker, is_cross)
            return True
        except Exception as e:
            logger.error(f"Error setting leverage for {ticker}: {e}")
            return False

"""
Volume Gate — Hard filter (not just scoring)
=============================================
Zoran's rule: No volume = no trade. Period.

Checks current candle volume against 20-candle rolling average.
If volume is below threshold → entry BLOCKED entirely.

This is separate from the existing VolumeConfirmation (which gives +2 score).
This is a GATE — it kills the trade before scoring even starts.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VolumeGateResult:
    allowed: bool
    volume_ratio: float      # current_vol / ma_vol
    current_volume: float
    ma_volume: float
    reason: str

    def summary(self) -> str:
        status = "✅ PASS" if self.allowed else "🚫 BLOCKED"
        return f"{status} | Vol ratio: {self.volume_ratio:.2f}x | {self.reason}"


class VolumeGate:
    """
    Hard volume filter — blocks entries on thin volume.
    
    Logic:
    - Calculate 20-candle rolling average volume
    - Current candle volume must be >= threshold * MA
    - Default threshold: 0.8 (80% of average)
    - Below threshold = fake breakout territory = no trade
    
    Config keys (under "volume_gate"):
        enabled: bool (default True)
        ma_period: int (default 20) — rolling average period
        min_ratio: float (default 0.8) — minimum vol/MA ratio to allow entry
        strong_ratio: float (default 1.5) — ratio considered "strong volume"
    """

    def __init__(self, config: dict):
        vg_cfg = config.get("volume_gate", {})
        self.enabled = vg_cfg.get("enabled", True)
        self.ma_period = vg_cfg.get("ma_period", 20)
        self.min_ratio = vg_cfg.get("min_ratio", 0.8)
        self.strong_ratio = vg_cfg.get("strong_ratio", 1.5)

    def check(self, df: pd.DataFrame) -> VolumeGateResult:
        """
        Check if current volume is sufficient for entry.
        
        Args:
            df: OHLCV DataFrame with 'volume' column
            
        Returns:
            VolumeGateResult with allowed=True/False
        """
        if not self.enabled:
            return VolumeGateResult(
                allowed=True,
                volume_ratio=1.0,
                current_volume=0.0,
                ma_volume=0.0,
                reason="Volume gate disabled",
            )

        if len(df) < self.ma_period + 1:
            return VolumeGateResult(
                allowed=True,
                volume_ratio=1.0,
                current_volume=0.0,
                ma_volume=0.0,
                reason="Insufficient data for volume gate",
            )

        # Current candle volume
        current_vol = float(df["volume"].iloc[-1])

        # 20-candle rolling average (excluding current candle to avoid lookahead)
        vol_ma = float(df["volume"].iloc[-(self.ma_period + 1):-1].mean())

        if vol_ma == 0:
            return VolumeGateResult(
                allowed=False,
                volume_ratio=0.0,
                current_volume=current_vol,
                ma_volume=0.0,
                reason="Volume MA is zero — no trading activity",
            )

        ratio = current_vol / vol_ma

        if ratio < self.min_ratio:
            return VolumeGateResult(
                allowed=False,
                volume_ratio=ratio,
                current_volume=current_vol,
                ma_volume=vol_ma,
                reason=f"Volume too thin: {ratio:.2f}x avg (need {self.min_ratio}x)",
            )

        strength = "STRONG" if ratio >= self.strong_ratio else "OK"
        return VolumeGateResult(
            allowed=True,
            volume_ratio=ratio,
            current_volume=current_vol,
            ma_volume=vol_ma,
            reason=f"Volume {strength}: {ratio:.2f}x avg",
        )

"""
Logging setup for MahmudBot.
Every decision, every trade, every skip — all logged.
"""

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(
    name: str = "mahmudbot",
    log_dir: str = "logs",
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure a logger with rotating file and console handlers.
    All bot decisions, trades, and skips are recorded.
    """
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers on reloads
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console Handler ────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # ── Main Rotating File Handler ─────────────────────────────────
    main_file = Path(log_dir) / "mahmudbot.log"
    file_handler = logging.handlers.RotatingFileHandler(
        str(main_file),
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # ── Trades-Only File Handler ───────────────────────────────────
    trades_file = Path(log_dir) / "trades.log"
    trades_handler = logging.handlers.RotatingFileHandler(
        str(trades_file),
        maxBytes=max_bytes,
        backupCount=3,
    )
    trades_handler.setLevel(logging.INFO)
    trades_handler.setFormatter(formatter)
    trades_handler.addFilter(_TradeFilter())
    logger.addHandler(trades_handler)

    return logger


class _TradeFilter(logging.Filter):
    """Only pass log records that contain trade keywords."""
    KEYWORDS = ("OPEN ", "CLOSE", "ENTRY", "EXIT", "TRADE", "DRY RUN")

    def filter(self, record: logging.LogRecord) -> bool:
        return any(kw in record.getMessage().upper() for kw in self.KEYWORDS)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the mahmudbot namespace."""
    return logging.getLogger(f"mahmudbot.{name}")

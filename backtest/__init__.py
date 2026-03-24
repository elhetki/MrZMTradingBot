"""
MahmudBot Backtest Engine
Fetch historical data, run strategy, report statistics.
"""
from .engine import BacktestEngine
from .data_fetcher import HistoricalDataFetcher
from .reporter import BacktestReporter

__all__ = ["BacktestEngine", "HistoricalDataFetcher", "BacktestReporter"]

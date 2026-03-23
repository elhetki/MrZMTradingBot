# MrZMTradingBot v2.0
### Automated Multi-Market Trading System for Hyperliquid
*Built by Zoran @ The Trading Gym — 20 years of screen time, automated.*

> *"Your biggest enemy in trading is you." This bot doesn't have that problem.*

---

## What Is This?

MrZMTradingBot is a fully automated trading bot that runs locally and trades perpetual futures on [Hyperliquid](https://hyperliquid.xyz) — the largest decentralized perps exchange ($7B+ daily volume). It scans 26 markets across 4 asset classes, detects high-probability setups using Zoran's exact trading strategy from The Trading Gym Manual, and executes with a tiered exit system that protects every green trade.

No cloud. No subscriptions. No API key sharing. You own the code.

---

## 26 Markets — 4 Asset Classes

| Class | Markets | Leverage |
|-------|---------|----------|
| **Crypto** | BTC, ETH, SOL | 40x |
| **Commodities** | Brent Oil, WTI, Gold, Silver, Natural Gas, Aluminium | 20-40x |
| **Index** | S&P 500 | 20x |
| **Stocks** | NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, AMD, NFLX, PLTR, ORCL, MSTR, COIN, HOOD, HIMS, BABA | 20x |

### Smart Market Hours

The bot knows when each market is open and only scans during active sessions:

| Market | Hours (UTC) |
|--------|-------------|
| Crypto | 24/7 |
| Commodities | Sun 22:00 → Fri 21:00 |
| US Stocks | Mon-Fri 08:00 → 21:00 |

---

## Strategy: Z.M System v2.0

The A+ setup from The Trading Gym Manual — the exact strategy that took 20 years to master.

### The 4-EMA System

| EMA | Role |
|-----|------|
| 🔵 **200** | Long-term trend. Above = Bullish. Below = Bearish. |
| 🔴 **48** | Last line of defense. If it holds, we ride. |
| 🟢 **13** | Pullback entries above 200. Shorts below. |
| 🟠 **8** | Trend indicator. Follow the 8, follow the money. |

### A+ Entry — Full Confluence Required

The bot only enters when the **full stack** aligns:

1. Price above/below 200 EMA (trend direction)
2. 13/48 EMA cross (momentum shift)
3. Bounce off 48 EMA (last defense holds)
4. 8 EMA trend confirmed (riding the wave)
5. Bull Flag or Bear Flag (continuation pattern)
6. Volume confirms the move
7. Supply/Demand zone alignment

**No confluence = no trade. Period.**
*"Never make a random entry."* — Rule #2

### Market Structure — BOS & CHOCH

- **BOS** (Break of Structure) → Trend continuation. The bot rides it.
- **CHOCH** (Change of Character) → Trend reversal. The bot catches the flip early, marks the S/D zone, and waits for the retrace to enter.

### Volume Confirmation

| Price | Volume | Action |
|-------|--------|--------|
| ↑ Up | ↑ Up | ✅ Enter — strong move |
| ↑ Up | ↓ Down | ❌ Skip — weak/fake |
| ↓ Down | ↑ Up | ✅ Enter — strong move |
| ↓ Down | ↓ Down | ❌ Skip — weak/fake |

### Multi-Signal Scoring

On top of the Z.M system, a point-based scoring system ensures multiple signals align. Minimum score of **5** required.

| Signal | Points |
|--------|--------|
| RSI extreme zone (<35 / >65) | +2 |
| EMA trend alignment | +2 |
| EMA crossover (just happened) | +3 |
| Bollinger Band extreme | +2 |
| Chart pattern (engulfing, S/D bounce) | +3 |
| Chart pattern (flag, triangle, momentum) | +2 |
| Price momentum confirmation | +1 |

Only trades with score **5+** AND probability **65%+** are executed.

---

## Exit Strategy: 4-Stage Tiered System

All percentages are leveraged P&L — your actual profit on the position.

| Stage | Trigger | Action |
|-------|---------|--------|
| **1. Initial** | Entry | SL at -3% |
| **2. Break-Even** | +2% profit | SL moves to entry + 0.5%. **Green trade never goes red.** |
| **3. Partial Close** | +5% profit | Close 2/3 of position. Remaining 1/3 trails at 2%. |
| **4. Take Profit** | +8% profit | Close everything. Scan for next setup. |

*"NEVER LET YOUR GREEN CANDLE BECOME RED."* — Rule #1

---

## Position Sizing

| Day | Size | Reason |
|-----|------|--------|
| Monday | 70% | Warmup after weekend |
| Tue–Thu | 100% | Golden zone — peak liquidity |
| Friday | 70% | *"Those guys wanna go long in some clubs or buy a new Rolex."* |
| Weekend | 50% | Lower volume, wider spreads |

First trade of the day is **always light**.

---

## Risk Management

| Parameter | Value |
|-----------|-------|
| Stop Loss | -3% leveraged P&L |
| Break-Even | +2% trigger |
| Partial Close | 2/3 at +5% |
| Trailing Stop | 2% after partial |
| Take Profit | +8% |
| Max positions | 3 simultaneous |
| Max daily loss | $50 → bot stops |
| Max consecutive losses | 3 → bot pauses |
| Cooldown | 5 min between trades per market |
| Bet size | $10 per trade (configurable) |
| Correlation guard | Max 1 same-direction crypto position |
| SL hard cap | Never > 2x original value |
| Direction bias ceiling | ±10 probability points max |

### Per-Market Slippage Limits

| Market | Slippage Limit |
|--------|---------------|
| BTC / ETH | 0.05% |
| SOL | 0.15% |
| Commodities | 0.30% |

---

## Self-Learning Brain

After every trade, the bot analyzes what happened and adjusts its own strategy.

**What it tracks:** Pattern win rates, RSI zone profitability, LONG vs SHORT performance, score thresholds, SL hit frequency.

**What it adjusts:** Avoids losing patterns (>70% loss rate), prefers winning patterns (>65% win rate), adjusts directional bias, widens SL if stopped out too often.

### Guardrails

| Guardrail | Rule |
|-----------|------|
| Min sample size | 15 trades per pattern before adjusting |
| Rolling window | Last 500 trades only |
| Asset isolation | Learnings tracked per ticker — no cross-contamination |
| SL hard cap | Never exceeds 2x original |
| Direction ceiling | Max ±10 probability points bias |

Everything persists to `learnings.json`. Restart the bot → it loads its brain and continues.

---

## Dashboard — Matrix Edition

Real-time web dashboard at `http://localhost:8888` with green Matrix rain aesthetic:

- **26 markets** grouped by asset class — live prices, RSI, position status
- **P&L bar** — win rate, open positions count
- **Active positions** — entry, SL, TP, current P&L, stage badge
- **Equity curve** — visual P&L over time
- **Brain panel** — learning engine stats
- **Trade history** — every trade with full details
- **Activity log** — real-time stream of bot actions
- **Close button** per position + Close All emergency button

---

## Signal Execution

### Signal Mode (on 5-min candle close)
Calculates all indicators on confirmed candle data — clean, stable signals. No mid-candle noise.

### Exit Mode (every 2 seconds)
Manages SL/TP/BE/trailing on open positions with real-time price data.

This split eliminates false entries from incomplete candle data while keeping exit management responsive.

---

## Installation

### Requirements
- Windows 10/11 or Mac
- Python 3.10+

### Setup
```bash
git clone https://github.com/elhetki/MrZMTradingBot.git
cd MrZMTradingBot
pip install requests
```

Start the bot:
```bash
python bot.py
```

Or on Windows, double-click `START.bat`.

The bot connects to Hyperliquid, loads candles for all 26 markets, opens the dashboard, and starts scanning.

### Configuration
Edit `config.json` to change markets, leverage, bet size, TP/SL percentages, RSI thresholds, sound on/off, DRY RUN vs LIVE.

---

## Dry Run Results (v2.0)

| Metric | Value |
|--------|-------|
| Total Trades | 94 |
| Win Rate | 62.8% |
| Wins / Losses | 59 / 35 |
| Total P&L | +$1.69 (at $10 bets) |

Break-even protection working — most wins exit at BE_STOP (+2%). Losses controlled at -3% SL.

---

## Roadmap

- [x] Multi-market scanning (26 assets, 4 asset classes)
- [x] Z.M Strategy v2.0 (4-EMA, BOS/CHOCH, S/D zones, volume)
- [x] Smart market hours
- [x] Matrix dashboard
- [x] Self-learning brain with guardrails
- [x] Candle close signal execution
- [x] Correlation guard
- [x] Per-market slippage limits
- [ ] Cloud deployment (24/7 without PC)
- [ ] Mobile dashboard
- [ ] Live trading integration (Hyperliquid API wallet)
- [ ] Telegram alerts (signals + trade notifications)
- [ ] Backtesting engine
- [ ] Funding rate tracking
- [ ] WebSocket migration (v3.0)

---

## ⚠️ Disclaimers

- Starts in **DRY RUN mode** — tracks trades but does NOT execute real ones
- To trade live: Hyperliquid wallet with funds + API key + set `"dry_run": false`
- **Never risk money you can't afford to lose**
- Past performance does not guarantee future results
- This is a tool, not financial advice

---

*Built with passion by Zoran and Claude AI.*
*The Trading Gym — "Never go against the market. Trend is your friend."* 💪

*For the full version history, see [CHANGELOG.md](CHANGELOG.md)*

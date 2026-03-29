# MrZMTradingBot v3.0 — Pegasus
### AI-Enhanced Automated Trading System for Hyperliquid
*Built on Z.M's Trading Gym Strategy · Enhanced with Daily AI Intelligence*

> *"Your biggest enemy in trading is you."* — This bot doesn't have that problem.
> And now it has an AI coach that makes it smarter every single day.

---

## Architecture Overview

```
MrZMTradingBot/
├── bot.py                    # Main orchestrator — scan loop + exit loop
├── config.json               # All tunable parameters (single source of truth)
├── strategy/                 # Signal generation
│   ├── ema.py                # 4-EMA system (8/13/48/200)
│   ├── entry.py              # Entry logic — full confluence evaluation
│   ├── exit_manager.py       # SL/TP + funding guard (halal-compliant)
│   ├── scoring.py            # Multi-signal scoring engine (16 max points)
│   ├── patterns.py           # 23 chart pattern detection
│   ├── structure.py          # BOS/CHOCH market structure
│   ├── zones.py              # Supply/Demand zone detection
│   ├── chop_filter.py        # Choppy market rejection (3-check system)
│   ├── mtf.py                # Multi-timeframe filter (15m/30m/1h)
│   ├── orderbook.py          # WOBI — L2 order book intelligence
│   ├── volatility_regime.py  # IPM regime detection (calm/trending/storm)
│   └── volume.py             # Volume confirmation
├── exchange/
│   ├── client.py             # Hyperliquid API client
│   └── dry_run.py            # Paper trading engine
├── utils/
│   ├── risk_manager.py       # Multi-layer risk enforcement
│   ├── learning_brain.py     # Self-learning engine (500-trade rolling)
│   ├── telegram_alerts.py    # Trade alerts to Telegram
│   ├── google_news.py        # RSS sentiment (confirm-only, never blocks)
│   ├── news_sentiment.py     # Funding rate + Fear & Greed
│   ├── market_hours.py       # Per-asset-class trading hours
│   └── logger.py             # Logging config
├── intelligence/
│   ├── daily_coach.py        # Daily AI performance analysis + auto-tuning
│   ├── run_daily.sh          # Cron wrapper (21:00 CET)
│   ├── trade_journal.json    # Rolling 90-day trade journal
│   └── changelog.json        # Every config change with reasoning
├── backtest/
│   ├── engine.py             # Backtesting engine
│   ├── data_fetcher.py       # Historical data from Hyperliquid
│   └── reporter.py           # Backtest results reporting
├── dashboard/                # Web dashboard (localhost:8888)
├── configs/                  # Config variants for testing
├── learnings.json            # Brain state (persisted across restarts)
└── alerts.log                # Full trade alert history
```

---

## 20 Markets — 4 Asset Classes

| Class | Markets | Leverage | Hours |
|-------|---------|----------|-------|
| **Crypto** | BTC, ETH, SOL*, AVAX, SUI, XRP | 40x | 24/7 |
| **Oil** | Brent, WTI | 20x | 24/7 on Hyperliquid |
| **Metals** | Gold, Silver | 20x | 24/7 on Hyperliquid |
| **Stocks** | NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, NFLX, PLTR, MSTR | 20x | US hours |
| **Index** | S&P 500 | 20x | US hours |

*\*SOL auto-disabled by Daily Coach on 2026-03-28 (15% WR, bleeding). Will re-enable when conditions improve.*

---

## Strategy: Z.M System v2.5

### The 4-EMA System (from The Trading Gym Manual)

| EMA | Role |
|-----|------|
| 🔵 **200** | Long-term trend. Above = Bullish. Below = Bearish. |
| 🔴 **48** | Last line of defense. Bounce = strong entry. |
| 🟢 **13** | Pullback level. 13/48 cross = momentum shift. |
| 🟠 **8** | Trend indicator. Follow the 8, follow the money. |

### Entry — 7-Layer Filtering Pipeline

Every potential trade passes through ALL layers in sequence. Any layer can block.

```
Market Scan
  → Layer 0: Chop Filter (3-check: ADX + Bollinger + ATR — 2/3 must pass)
  → Layer 1: Multi-Timeframe (15m + 30m + 1h — 2/3 must agree on direction)
  → Layer 2: News Sentiment (confirm-only — adds +1 bonus, never blocks)
  → Layer 3: WOBI Order Book (L2 bid/ask wall analysis — can veto)
  → Layer 4: Scoring Engine (EMA + RSI + BB + patterns + momentum)
  → Layer 5: Risk Manager (position limits, loss caps, correlation guard)
  → Layer 6: Slippage Check (per-market thresholds)
  → EXECUTE (if score ≥ 5 AND probability ≥ 50%)
```

### Scoring Table (16 max points)

| Signal | Points |
|--------|--------|
| Price above/below 200 EMA (trend) | +3 |
| 13/48 EMA cross (momentum shift) | +3 |
| 48 EMA bounce (last defense holds) | +2 |
| 8 EMA trend alignment | +2 |
| Chart pattern (engulfing, S/D, BOS/CHOCH) | +3 |
| Chart pattern (flag, triangle, wedge) | +2 |
| Bollinger Band extreme | +2 |
| RSI extreme zone (<35 / >65) | +2 |
| Volume confirmation | +1 |
| WOBI order book confirmation | +2 |
| News sentiment alignment | +1 |
| Price momentum (5-candle) | +1 |

**Minimum: Score ≥ 5 AND Probability ≥ 50%**

### 23 Chart Patterns Detected

**Reversal:** Double Top/Bottom, Head & Shoulders (+ inverse), Pin Bars, Doji, Bullish/Bearish Engulfing
**Continuation:** Bull/Bear Flags, Ascending/Descending Triangles, Wedges, Cup & Handle
**Momentum:** Three Soldiers/Crows, Momentum Burst
**Key Levels:** Support Bounce, Resistance Rejection, S/D Zone Entry

### Market Structure — BOS & CHOCH

- **BOS** (Break of Structure) → Trend continuation
- **CHOCH** (Change of Character) → Trend reversal — bot catches the flip, marks S/D zone, waits for retrace

---

## Exit Strategy: Clean SL/TP + Funding Guard

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Stop Loss** | -3.5% leveraged | Cut losers fast. R:R 1:3. |
| **Take Profit** | +10.5% leveraged | Bank consistent wins (matched to Zoran's live results) |
| **Hard Stop** | -5.25% | Absolute safety net — never exceeded |
| **Funding Guard** | Close 2min before funding tick | **Halal compliance** — zero interest/riba exposure |

### Why No Trailing Stop (Yet)
Current system uses fixed SL/TP. Trailing stop is on the optimization roadmap — would lock in profits on runners that hit +8% before reversal.

### Funding Guard — Halal Compliance
Hyperliquid charges/pays funding rates every hour. Holding through a funding tick means paying or receiving interest — haram. The funding guard automatically closes ALL positions 2 minutes before each hourly tick. This is non-negotiable.

---

## Risk Management — 8 Layers

| Layer | Rule | Default |
|-------|------|---------|
| **Daily Loss Cap** | Bot pauses when daily losses hit limit | $500 |
| **Hourly Loss Cap** | Bot pauses until next hour | $300 |
| **Consecutive Losses** | Pause after N losses in a row | 3 |
| **Max Positions** | Never more than N open | 3 |
| **Max Same Direction** | Can't stack 3 longs or 3 shorts | 2 |
| **Correlation Guard** | Max 1 same-direction crypto position | Crypto only |
| **Cooldown** | Minimum time between trades per market | 600s |
| **Slippage Rejection** | Reject if fill price deviates too far | Per-market |
| **Daily Profit Lock** | Lock gains after +10% day | 10% |

### Per-Market Slippage Limits

| Market | Limit | Typical Spread |
|--------|-------|---------------|
| BTC/ETH | 0.05% | ~0.003-0.01% |
| SOL/AVAX/SUI/XRP | 0.15% | ~0.05-0.1% |
| Oil/Metals | 0.30% | ~0.1-0.2% |
| Stocks | 0.20% | ~0.05-0.15% |

### Position Sizing — Day of Week

| Day | Size | Reason |
|-----|------|--------|
| Monday | 70% | Warmup after weekend |
| Tue–Thu | 100% | Peak liquidity |
| Friday | 70% | Profit-taking day |
| Weekend | 35% | Low volume (reduced from 50% by Daily Coach) |

First trade of every day is always at 50% of day size.

---

## Self-Learning Brain

After every trade, the bot analyzes what happened and adjusts.

### What It Tracks (per ticker)
- Pattern win rates (23 patterns × per market)
- RSI zone profitability (oversold/overbought/neutral)
- LONG vs SHORT performance
- Score threshold effectiveness
- Stop loss hit frequency

### What It Adjusts
- **Avoids losing patterns** — >70% loss rate over 15+ trades → pattern skipped
- **Prefers winning patterns** — >65% win rate → score boost
- **Direction bias** — shifts probability ±10 points toward winning direction
- **SL width** — widens if >60% of trades hit SL (capped at 2x original)

### Guardrails (prevents overfitting)

| Guardrail | Rule |
|-----------|------|
| Min sample | 15 trades before any adjustment |
| Rolling window | Last 500 trades only |
| Asset isolation | Per-ticker — no cross-contamination |
| SL hard cap | Never > 2x original value |
| Direction ceiling | Max ±10 probability points |

Brain persists to `learnings.json`. Survives restarts.

---

## 🧠 Daily Intelligence Coach (NEW — v3.0)

The bot's AI layer. Runs once daily at 21:00 CET.

### Phase 1: Performance Autopsy
- Parses all trades from alerts.log
- Per-market, per-hour, per-direction breakdown
- Exit reason analysis (TP/SL/funding/hard stop)
- Loss streak detection
- Win rate trends vs previous days

### Phase 2: Self-Tuning
Based on Phase 1, automatically adjusts config.json:
- **Disable bleeding markets** (>10 trades, <25% WR, negative P&L)
- **Adjust TP/SL** based on hit rates
- **Weekend sizing** reduction if weekend WR drops
- **Direction imbalance alerts**

Every change logged with reasoning in `intelligence/changelog.json`.

### Phase 3: Research & Edge Discovery
Generates targeted research queries based on performance gaps:
- High SL hit rate → research dynamic SL strategies
- Low win rate → research better entry filters
- Poor R:R → research exit optimization
- Always: community intel, platform updates

### Daily Telegram Report
```
🧠 PEGASUS DAILY INTEL — Mar 29

🔴 P&L: $-6.85 | 21 trades | 19% WR
📊 Avg Win: $+0.12 | Avg Loss: $-0.43 | R:R: 0.3:1

🔧 Changes made:
  • SOL disabled (15% WR, bleeding)
  • Weekend sizing 0.5 → 0.35

🔬 Research queue:
  • Entry filtering improvements
  • Exit optimization strategies
```

---

## News Sentiment — Confirm Only (Option C)

**History:** Originally, Google News RSS could BLOCK trades when headlines contradicted the signal direction. Zoran discovered this killed oil trades — oil was trending hard but clickbait headlines ("oil drops on fears") triggered false bearish sentiment, blocking valid longs.

**Current behavior (v3.0):**
- News scans Google RSS every 30 minutes per market
- If news CONFIRMS trade direction → +1 bonus score point
- If news OPPOSES trade direction → ignored (logged, not blocked)
- **News never blocks a trade. Chart is king.**

---

## Execution Architecture

### Dual-Loop Design

| Loop | Frequency | Purpose |
|------|-----------|---------|
| **Signal Loop** | Every 5-min candle close | Calculate indicators on CONFIRMED candle data. No mid-candle noise. |
| **Exit Loop** | Every 2 seconds | Manage SL/TP/funding guard on open positions with live prices. |

### Blackout Windows (no entries)

| Window | UTC | Reason |
|--------|-----|--------|
| London Close | 15:00–16:00 | Historically worst hour (9% WR in testing) |
| US Open | 13:30–14:30 | High volatility, whipsaw-prone |

---

## Volatility Regime Detection (IPM)

| Regime | Condition | Action |
|--------|-----------|--------|
| ☀️ CALM | Low ATR + tight BB | Normal sizing |
| 🌤️ TRENDING | Moderate ATR | Normal sizing, normal thresholds |
| 🌪️ STORM | High ATR + wide BB | Min score raised, position size reduced |

Prevents entering volatile, unpredictable markets with full size.

---

## Lessons Learned (Bugs That Cost Money)

These are real bugs found during testing. All fixed.

| Bug | Loss | Fix |
|-----|------|-----|
| Stale entry prices (candle close, not live) | SL/TP miscalculated | Use live mid-price for entries |
| Re-entry spam after SL | 3x stopped out in 2min | 5min cooldown + duplicate detection |
| Leverage drift (40x instead of 20x) | Amplified losses | Hard config enforcement on startup |
| Price gap through SL (SOL) | $2,509 | Per-market slippage rejection |
| Mid-candle indicator noise | False signals | Signal on confirmed candle close only |
| Crypto correlation stacking | 60x effective exposure | Max 1 same-direction crypto |
| 100-trade learning window too small | Brain never learned | Expanded to 500 trades |
| News blocking valid oil trades | Missed $900+ in profits | News → confirm-only mode |
| SOL bleeding in choppy conditions | -$4.39/day | Auto-disabled by Daily Coach |

---

## Setup

### Requirements
- Python 3.10+
- Hyperliquid account + API key
- Telegram bot (optional, for alerts)

### Install
```bash
git clone https://github.com/elhetki/MrZMTradingBot.git
cd MrZMTradingBot
pip install requests
cp .env.example .env.secrets
# Edit .env.secrets with your API keys
```

### Run
```bash
# Dry run (default — paper trading)
python bot.py

# With dashboard
python bot.py --dashboard

# Live trading (requires funded account!)
python bot.py --live
```

### Cron Jobs
```bash
# Daily intelligence report at 21:00 CET
0 19 * * * /path/to/intelligence/run_daily.sh

# Trade alert forwarder (every minute)
* * * * * /path/to/alert-forwarder.sh
```

---

## Config Reference (config.json)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `dry_run` | true | Paper trading mode |
| `bet_size` | 100.0 | USD per trade |
| `max_positions` | 3 | Max simultaneous positions |
| `daily_loss_cap` | 500.0 | Daily loss limit |
| `hourly_loss_cap` | 300.0 | Hourly loss limit |
| `consecutive_loss_limit` | 3 | Pause after N consecutive losses |
| `cooldown_seconds` | 600 | Min seconds between trades per market |
| `max_same_direction` | 2 | Max positions in same direction |
| `scoring.min_score` | 5 | Minimum entry score |
| `scoring.min_probability` | 0.50 | Minimum entry probability |
| `exit.sl_pct` | -3.5 | Stop loss (leveraged %) |
| `exit.tp_pct` | 10.5 | Take profit (leveraged %) |
| `exit.hard_stop_pct` | -5.25 | Absolute max loss per trade |
| `exit.funding_guard` | true | Close before funding ticks |
| `exit.funding_guard_minutes` | 2 | Minutes before tick to close |

---

## Roadmap

- [x] 20 markets across 4 asset classes
- [x] Z.M 4-EMA strategy with full confluence scoring
- [x] 23 chart pattern detection
- [x] BOS/CHOCH market structure analysis
- [x] Multi-timeframe filter (15m/30m/1h)
- [x] WOBI order book intelligence
- [x] Chop filter + volatility regime detection
- [x] Self-learning brain with guardrails
- [x] Telegram trade alerts
- [x] Backtesting engine
- [x] Funding guard (halal compliance)
- [x] Daily AI intelligence coach
- [x] Google News sentiment (confirm-only)
- [ ] Trailing stop option
- [ ] ATR-based dynamic position sizing
- [ ] WebSocket migration (lower latency)
- [ ] Cloud deployment (24/7 without PC)
- [ ] Mobile dashboard
- [ ] Per-market TP/SL optimization

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v1.0 | Mar 2026 | 5 markets, basic scoring, 4-stage exit |
| v1.1 | Mar 2026 | Bug fixes: stale prices, re-entry spam, leverage drift, slippage |
| v1.2 | Mar 2026 | Candle close signals, correlation guard, per-market slippage, 500-trade window |
| v2.0 | Mar 2026 | 26 markets, Z.M strategy, BOS/CHOCH, S/D zones, Matrix dashboard |
| v2.5 | Mar 2026 | Chop filter, 23 patterns, MTF, WOBI, clean SL/TP, funding guard, volatility regime |
| v3.0 | Mar 2026 | Zoran-matched config, news confirm-only, Daily AI Coach, intelligence layer |

*For the original development history, see [CHANGELOG.md](CHANGELOG.md)*

---

*Built by Mahmud & Jarvis AI · Strategy by Zoran @ The Trading Gym*
*"Never go against the market. Trend is your friend."* 💪

# MrZMTradingBot
### Automated Multi-Market Trading System for Hyperliquid
*Built by Zoran @ The Trading Gym*

---

## What Is This?

MrZMTradingBot is a fully automated trading bot that runs on your local machine and trades perpetual futures on Hyperliquid — the largest decentralized perps exchange doing $7B+ daily volume. It scans 5 markets simultaneously, detects high-probability setups using technical analysis and chart pattern recognition, executes trades with a smart tiered exit strategy, and learns from every single trade to get better over time.

No cloud. No subscriptions. No API key sharing. Everything runs locally on your PC. You own the code.

---

## Markets (5 Simultaneous)

| Market | Ticker | Type | Leverage | Why |
|--------|--------|------|----------|-----|
| Bitcoin | BTC | Crypto | 20x | $2.6B daily volume, most liquid perp |
| Ethereum | ETH | Crypto | 20x | $800M volume, strong trends |
| Solana | SOL | Crypto | 20x | High volatility, great for patterns |
| Brent Oil | xyz:BRENTOIL | Commodity | 35x | War-driven volatility, 24/7 trading |
| Gold | xyz:GOLD | Commodity | 15x | Safe haven, trending with conflict |

The bot can hold up to 3 positions at the same time across different markets. It always picks the highest-probability signal.

---

## Strategy: Multi-Signal Scoring System

The bot does NOT rely on a single indicator. It uses a point-based scoring system where multiple signals must align before entering a trade. A minimum score of 5 is required.

### Indicators Used
- RSI (14) — Relative Strength Index for overbought/oversold detection
- EMA 9/21 — Fast and slow Exponential Moving Averages for trend direction
- EMA Crossover Detection — Catches the exact moment trend flips
- Bollinger Bands (20, 2) — Volatility bands for mean reversion plays
- Price Momentum — 5-candle momentum for trend confirmation

### Chart Pattern Detection
The bot scans every 5-minute candle for these patterns:
- Bull Flag / Bear Flag — Tight consolidation after a strong move
- Triangle Breakout — Converging highs and lows with directional breakout
- Support Bounce / Resistance Rejection — Price reacting to key levels
- Bullish / Bearish Engulfing — Strong reversal candle patterns
- Momentum Breakout — 3 consecutive directional candles with increasing volume

### How Scoring Works

| Signal | Points |
|--------|--------|
| RSI in extreme zone (<35 or >65) | +2 |
| RSI approaching zone (35-45 or 55-65) | +1 |
| EMA trend alignment | +2 |
| EMA crossover (just happened) | +3 |
| Bollinger Band extreme position | +2 |
| Chart pattern (engulfing, support bounce) | +3 |
| Chart pattern (flag, triangle, momentum) | +2 |
| Price momentum confirmation | +1 |

Example trade: EMA bullish (+2) + Support Bounce (+3) + RSI at 38 (+2) = Score 7 = HIGH CONFIDENCE LONG

Only trades with score 5+ AND probability 65%+ are executed. No coin flips.

---

## Exit Strategy: 4-Stage Tiered System

This is where the real edge is. The bot doesn't just set a flat TP/SL — it uses a dynamic, tiered exit plan that protects profits and limits losses.

All percentages are based on leveraged P&L (your actual profit on the bet), not raw price movement.

### The 4 Stages

**Stage 1: INITIAL**
- Entry with fixed Stop Loss at -5% leveraged P&L
- At 35x leverage on oil, that's about $0.15 price movement
- Protects against immediate adverse moves

**Stage 2: BREAK-EVEN** (triggers at +5% profit)
- Stop Loss automatically moves to entry price + 0.5% offset
- From this point forward, you CANNOT lose money on this trade
- Sound alert plays when this triggers

**Stage 3: PARTIAL CLOSE** (triggers at +10% profit)
- Bot closes 2/3 (66%) of the position and locks in profit
- Remaining 1/3 runs with an activated trailing stop (3%)
- This secures most of the gain while letting winners run

**Stage 4: TAKE PROFIT** (triggers at +20% profit)
- Close everything. Full take profit.
- Bot immediately starts scanning for the next setup

### Risk Management
- Max 3 positions open simultaneously
- Max daily loss: $50 — bot stops trading if hit
- Max 3 consecutive losses — bot pauses and waits for better conditions
- Cooldown: 2 minutes between trades per market
- $10 bet size per trade (configurable)

---

## Self-Learning Brain

This is the feature that makes MrZMTradingBot different. After every single trade, the bot analyzes what happened and adjusts its own strategy.

### What It Tracks
- Which chart patterns lead to wins vs losses
- Which RSI zones are profitable for entries
- LONG vs SHORT — which direction performs better
- Which score thresholds actually win
- Whether the stop loss is too tight (getting stopped out too often)

### What It Adjusts Automatically
- Avoids losing patterns — if BULL_FLAG loses 70%+ of trades, the bot stops using it as a signal
- Prefers winning patterns — if SUPPORT_BOUNCE wins 65%+, it gets a score boost
- Direction bias — if LONG trades win 70% while SHORT wins 30%, the bot favors LONG
- SL width — if 70%+ of trades hit stop loss, the bot widens it automatically
- Score threshold — learns what minimum score actually produces wins

### Persistence
Everything saves to `learnings.json`. When you restart the bot, it loads its brain and picks up where it left off. The more it trades, the smarter it gets.

---

## Live Dashboard

The bot comes with a real-time web dashboard (runs locally at http://localhost:8888) showing:

- **5 Market Strip** — live prices, RSI, EMA direction for all markets
- **Active Positions** — entry, TP, SL, current P&L, SL stage badge
- **Performance Stats** — total P&L, win rate, wins/losses
- **Brain Panel** — what the self-learning engine has figured out
- **Equity Curve** — visual chart of your P&L over time
- **Trade History** — every trade with market, direction, entry, exit, P&L, reason
- **Activity Log** — real-time stream of bot actions

Everything updates every 2 seconds from live Hyperliquid data.

---

## Sound Alerts

The bot plays distinct sound alerts on Windows:
- 🔔 Rising chime — Signal detected
- ✅ Punchy confirmation — Trade executed
- 💰 Cha-ching — Take profit hit
- 🔄 Soft blip — Stop loss moved to break-even
- ⚠️ Low warning — Stop loss hit

---

## Tech Stack

- **Python 3.10+** — Trading engine
- **Hyperliquid API** — Real-time price feeds and 5-minute candles
- **HTML/CSS/JS Dashboard** — Local web interface
- No dependencies beyond `requests` library
- No cloud, no subscriptions — runs 100% on your machine
- DRY RUN mode — Paper trade with real data before risking money

---

## Installation (2 Minutes)

### Requirements
- Windows 10/11
- Python 3.10+ (https://python.org — check "Add to PATH" during install)

### Setup
```bash
git clone https://github.com/jarvisjeecation/MrZMTradingBot.git
cd MrZMTradingBot
pip install requests
```

Then double-click `START.bat` or run:
```bash
python bot.py
```

That's it. The bot connects to Hyperliquid, loads candles for all 5 markets, opens the dashboard in your browser, and starts scanning.

### Configuration
Edit `config.json` to change:
- Markets and leverage
- Bet size
- TP/SL percentages
- RSI thresholds
- Min probability
- Sound on/off
- DRY RUN vs LIVE

---

## ⚠️ Important Disclaimers

- The bot starts in **DRY RUN mode** — it tracks trades but does NOT execute real ones
- To trade live, you need a Hyperliquid wallet with funds and API key
- Set `"dry_run": false` in config.json only when you're ready
- **Never risk money you can't afford to lose**
- Past performance does not guarantee future results
- This is a tool, not financial advice — always do your own research
- Test extensively in DRY RUN before going live

---

## Roadmap

- [ ] Live trading integration with Hyperliquid Exchange API
- [ ] More chart patterns (double top/bottom, head & shoulders)
- [ ] Multi-timeframe analysis (1m + 5m + 15m confluence)
- [ ] Telegram alerts integration
- [ ] More markets (NASDAQ, S&P500, SILVER, individual stocks)
- [ ] Backtesting engine with historical data
- [ ] Mobile dashboard

---

*Built with passion by Zoran and Claude AI. Shared with The Trading Gym.*
*MrZMTradingBot v1.0 — March 2026*

---

## Learning Engine v2 — Guardrails

Based on community feedback from The Trading Gym, the self-learning engine now has 5 hard guardrails to prevent overfitting and runaway adjustments:

### 1. Minimum Sample Size
The bot requires **15 trades per pattern** before adjusting any scores. No more overfitting on a 3-trade winning streak. Until a pattern has 15+ data points, it uses default scoring.

### 2. Rolling Window (Last 100 Trades)
Only the **last 100 trades** are analyzed. Older trades decay naturally. If the market shifts from choppy to trending, the bot adapts within ~100 trades instead of being anchored to stale data from weeks ago.

### 3. Asset-Isolated Learnings
All learnings are tracked **per ticker**. If BEAR_ENGULFING loses on Gold, it only affects Gold — Solana keeps its own independent track record. No cross-contamination.

```
[BTC]       AVOID BULL_FLAG (32% win rate, 18 trades)
[BRENTOIL]  PREFER SUPPORT_BOUNCE (71% win rate, 24 trades)
[SOL]       NEUTRAL — insufficient data
```

### 4. Stop Loss Hard Cap
Stop loss can **never exceed 2x its original value**. If base SL is 5%, the absolute maximum is 10% — mathematically enforced, no exceptions. The learning engine can widen SL, but it hits a wall.

```
Base SL: 5.0% → Max allowed: 10.0%
Current: 7.2% [WITHIN LIMITS]
```

### 5. Direction Bias Ceiling
Maximum **±10 probability points** for LONG vs SHORT bias. Even if LONG wins 90% of trades, SHORT signals only get -10pts penalty — they can still fire at 55%+. The bot never goes blind to valid counter-trend signals.

```
LONG bias: +8pts (from 72% win rate)
SHORT still viable: needs 63%+ base probability to fire
```

All guardrails are displayed on startup and logged with every learning adjustment.

*Community feedback → shipped same day* 💪


---

## Patch v1.1 — Critical Bug Fixes

*Overnight results: 69 trades, W:37 L:32 (53% WR). Break-even protection and learning engine both working correctly. Execution layer had gaps — now patched.*

### Bug 1: Stale Entry Prices
**Problem:** Bot entered trades using candle close prices instead of live mid-prices. SL/TP calculated from wrong price level.
**Fix:** Entries now use live Hyperliquid mid-price. SL and TP recalculated from actual execution price.

### Bug 2: Re-Entry Spam
**Problem:** After a stop-loss, bot immediately re-entered the same trade at the same price. SOL got stopped out 3x in a row within 2 minutes.
**Fix:** Cooldown increased to 5 minutes. Added duplicate signal detection — blocks re-entry if same direction and price is within 0.05% of last signal.

### Bug 3: Leverage Drift
**Problem:** Crypto leverage had drifted to 40x instead of intended 20x, amplifying losses.
**Fix:** Hard reset — BTC/ETH/SOL = 20x, BRENTOIL = 20x, GOLD = 15x. Enforced on startup.

### Bug 4: SL Gap / Slippage Losses
**Problem:** SOL entry at $87.27 with SL at $87.16, but exited at $86.72 — price gapped through the stop level. $2,509 loss.
**Fix:** Slippage protection added. Bot rejects any entry where live price has moved >0.1% from signal price. Prevents entering fast-moving markets with stale data.

### Updated Risk Parameters (v1.1)

| Market | Leverage | Bet Size |
|--------|----------|----------|
| BTC | 20x | $10.00 |
| ETH | 20x | $10.00 |
| SOL | 20x | $10.00 |
| BRENTOIL | 20x | $10.00 |
| GOLD | 15x | $10.00 |

| Parameter | Value |
|-----------|-------|
| Cooldown | 5 min between trades |
| Max consecutive losses | 3 then pause |
| SL cap | Never > 2x original |
| Slippage rejection | > 0.1% = reject |

**Lesson:** Strategy + learning engine performed well (53% WR, break-even triggers firing). But high-frequency leveraged perps need extremely tight execution controls. Small execution bugs → big losses. Now patched.

*MrZMTradingBot v1.1 — March 2026*


---

## Patch v1.2 — Community Feedback Response #2

*Addressing 6 observations from The Trading Gym community*

### Fix 1: Candle Close Signals (Biggest Impact)
**Problem:** Bot recalculated RSI/EMA/BB every 2 seconds using live mid-candle close. Indicators were noisy and unstable — signals fired on incomplete data.
**Fix:** Split the main loop into two distinct modes:
- **Signal mode** — only runs on confirmed 5-min candle close (clean, stable indicators)
- **Exit mode** — runs every 2 seconds (manages SL/TP/BE/trailing on open positions)

This eliminates false entries from mid-candle noise while keeping exit management responsive.

### Fix 2: Correlation Guard (Prevents Stacked Risk)
**Problem:** Bot went LONG on BTC, ETH, and SOL simultaneously. All dropped together. At 20x each, that's effectively 60x directional exposure to one correlated move.
**Fix:** Added correlation guard for crypto assets:
- Max 1 same-direction crypto position at any time
- If BTC is LONG, ETH/SOL can only open SHORT or skip
- Commodities (BRENTOIL, GOLD) are independent — no correlation restriction

```
[GUARD] BTC LONG active → ETH LONG signal BLOCKED (correlated)
[GUARD] BTC LONG active → GOLD LONG signal ALLOWED (uncorrelated)
[GUARD] BTC LONG active → SOL SHORT signal ALLOWED (opposite direction)
```

### Fix 3: Per-Market Slippage Limits
**Problem:** Flat 0.1% slippage threshold for all markets. BTC spread is ~0.003%, but SOL is 0.05-0.1% and commodities on xyz dex can be even wider. Bot was either rejecting valid commodity trades or accepting bad crypto entries.
**Fix:** Per-market slippage thresholds:

| Market | Slippage Limit | Typical Spread |
|--------|---------------|----------------|
| BTC | 0.05% | ~0.003% |
| ETH | 0.05% | ~0.01% |
| SOL | 0.15% | ~0.05-0.1% |
| BRENTOIL | 0.30% | ~0.1-0.2% |
| GOLD | 0.30% | ~0.1-0.2% |

### Fix 4: Learning Engine Window Increase
**Problem:** 100 buckets (5 markets × 10 patterns × 2 directions) sharing a 100-trade rolling window. Most buckets never reach the 15-trade minimum for learning to kick in.
**Fix:** Rolling window increased from 100 → 500 trades. Combined with per-ticker isolation, each market now has ~100 trades in its own window across ~20 buckets — enough for meaningful pattern learning.

```
Before: 100 trades ÷ 100 buckets = ~1 trade per bucket (useless)
After:  500 trades ÷ 20 buckets per market = ~25 trades per bucket ✅
```

### Tracked: Funding Rate Awareness (Not Yet Implemented)
**Observation:** At 20x leverage, a -0.01% funding rate = -0.2% effective cost every 8 hours. Holding across 2-3 funding periods can turn a small win into a loss.
**Status:** Not critical for current strategy — trades last minutes, rarely crossing a funding window. Will be added when hold times increase. Implementation plan:
- Query Hyperliquid funding rate before entry
- If negative funding > -0.03% and trade direction matches the paying side, reduce score by -1
- Display current funding rates on dashboard

### Tracked: WebSocket Migration (v2.0)
**Observation:** WebSocket would give lower latency, lighter resources, and no rate-limit risk vs current REST polling.
**Status:** Current REST polling works for testing phase. WebSocket planned for v2.0 as it requires async architecture refactor (aiohttp/websockets).

### Updated Parameters (v1.2)

| Parameter | v1.1 | v1.2 |
|-----------|------|------|
| Signal calculation | Every 2s (live) | On 5-min candle close only |
| Exit management | Every 2s | Every 2s (unchanged) |
| Rolling window | 100 trades | 500 trades |
| Slippage (BTC/ETH) | 0.1% flat | 0.05% |
| Slippage (SOL) | 0.1% flat | 0.15% |
| Slippage (commodities) | 0.1% flat | 0.30% |
| Crypto correlation | None | Max 1 same-direction |

*Community feedback → shipped same day* 💪

*MrZMTradingBot v1.2 — March 2026*


---

## v2.0 — Major Upgrade: 26 Markets + Z.M Strategy

*Massive expansion: from 5 markets to 26, new strategy engine, smart market hours, new dashboard.*

### 26 Markets Across 4 Asset Classes

| Class | Markets | Leverage |
|-------|---------|----------|
| **Crypto** | BTC, ETH, SOL | 40x |
| **Commodities** | BRENT OIL, WTI, GOLD, SILVER, NATGAS, ALUMINIUM | 20-40x |
| **Index** | S&P 500 | 20x |
| **Stocks** | NVDA, TSLA, AAPL, MSFT, META, AMZN, GOOGL, AMD, NFLX, PLTR, ORCL, MSTR, COIN, HOOD, HIMS, BABA | 20x |

One bot. 26 markets. Every asset class.

### Z.M Strategy v2.0 — Integrated

Zoran's A+ setup from The Trading Gym Manual is now coded directly into the bot:

- **8 / 13 / 48 / 200 EMA system** — exact setup from the manual
- **BOS & CHOCH detection** — Break of Structure and Change of Character for market structure analysis
- **Supply & Demand zone entries** — institutional-level entry zones
- **Volume confirmation** — filters strong moves from weak/fake moves
- **Bull Flag / Bear Flag** — continuation pattern detection
- **Smart position sizing** — lighter positions Monday/Friday, heavier Tuesday-Thursday (peak liquidity days)

The bot now trades the way Zoran trades. Same confluences. Same rules.

### Smart Market Hours

The bot knows when each market is open and only scans during active sessions:

| Market | Hours (UTC) |
|--------|-------------|
| Crypto | 24/7 — always scanning |
| Commodities | Sun 22:00 → Fri 21:00 |
| US Stocks | Mon-Fri 08:00 → 21:00 |

No wasted scans on closed markets. No false signals on stale data.

### Dashboard — Matrix Edition

Full redesigned dashboard with hacker-style green Matrix rain aesthetic:
- All 26 markets grouped by asset class with live prices, RSI, position status
- P&L bar with win rate and open positions count
- Trade history table + equity curve chart
- Brain performance panel (learning engine stats)
- Close button per position + Close All emergency button

### Dry Run Results (v2.0)

| Metric | Value |
|--------|-------|
| Total Trades | 94 |
| Win Rate | 62.8% |
| Wins | 59 |
| Losses | 35 |
| Total P&L | +$1.69 (at $10 bets) |

Break-even protection working as designed — most wins exit at BE_STOP (+2%), protecting profits early. Losses controlled at -3% SL.

### Roadmap

- [x] Multi-market (26 assets)
- [x] Z.M Strategy v2.0
- [x] Market hours awareness
- [x] Matrix dashboard
- [x] Self-learning brain
- [ ] Cloud deployment (bot runs 24/7 without PC)
- [ ] Mobile dashboard access from anywhere
- [ ] Live trading integration (Hyperliquid API wallet)
- [ ] Telegram alerts (signals + trade notifications)
- [ ] Backtesting engine for historical validation

*MrZMTradingBot v2.0 — March 2026*


---

## Z.M Strategy Deep Dive

*The exact A+ setup from The Trading Gym Manual — 20 years of screen time, automated.*

### The 4-EMA System

| EMA | Color | Role |
|-----|-------|------|
| 200 | 🔵 Blue | Long-term trend. Above = Bullish. Below = Bearish. |
| 48 | 🔴 Red | Last line of defense. If it holds, we ride. |
| 13 | 🟢 Green | Pullback entries above 200. Shorts below. |
| 8 | 🟠 Orange | Trend indicator. Follow the 8, follow the money. |

The bot reads all four EMAs together — exactly like Zoran does on the 2min and 15min charts.

### A+ Setup — Full Confluence Required

The bot only enters when the full stack aligns:

1. ✅ Price above/below 200 EMA (trend direction)
2. ✅ 13/48 EMA cross (momentum shift)
3. ✅ Bounce off 48 EMA (last defense holds)
4. ✅ 8 EMA trend confirmed (riding the wave)
5. ✅ Bull Flag or Bear Flag (continuation pattern)
6. ✅ Volume confirms the move (strong, not weak)
7. ✅ Supply/Demand zone alignment

No confluence = no trade. Period.
*"Never make a random entry."* — Rule #2

### Market Structure — BOS & CHOCH

The bot reads market structure like it's taught in the manual:

- **BOS** (Break of Structure) → Trend continuation. The bot rides it.
- **CHOCH** (Change of Character) → Trend reversal. The bot catches the flip early, marks the demand/supply zone, and waits for the retrace to enter.

Higher highs + higher lows = bullish BOS.
Break of a higher low = CHOCH → bearish reversal.

Based on pages 24-29 of The Trading Gym Manual.

### Volume Confirmation Matrix

| Price | Volume | Signal | Action |
|-------|--------|--------|--------|
| Up | Up | Strong bullish | ✅ Enter long |
| Up | Down | Weak / fake | ❌ Skip |
| Down | Up | Strong bearish | ✅ Enter short |
| Down | Down | Weak / fake | ❌ Skip |

The bot never enters weak moves. Only strong, volume-confirmed setups.

### Z.M Position Sizing Rules

| Day | Size | Reason |
|-----|------|--------|
| Monday | 70% | Warmup after weekend |
| Tuesday | 100% | Golden zone — peak liquidity |
| Wednesday | 100% | Golden zone |
| Thursday | 100% | Golden zone |
| Friday | 70% | *"Friday is profit taking day, because those guys wanna go long in some clubs or buy a new Rolex."* |
| Weekend | 50% | Lower volume, wider spreads |

First trade of the day: ALWAYS light.

### Risk Management (v2.0)

| Parameter | Value |
|-----------|-------|
| Stop Loss | -3% leveraged P&L |
| Break-Even trigger | +2% (green trade never goes red) |
| Partial close | 2/3 at +5% |
| Trailing stop | 2% after partial |
| Take Profit | +8% |
| Max positions | 3 simultaneous |
| Learning window | 500 trades rolling |

*"NEVER LET YOUR GREEN CANDLE BECOME RED."* — Rule #1

### What Makes This Different

This bot isn't built from a YouTube tutorial or ChatGPT template. It's built from 20 years of screen time. Every rule, every EMA, every confluence comes from real trades, real losses, and real lessons — the same ones in The Trading Gym Manual.

It trades the way Zoran trades. It thinks the way he thinks. It follows the rules he follows. And it does it 24/7 without fear, without FOMO, and without emotion.

*"Your biggest enemy in trading is you."*
This bot doesn't have that problem.

*MrZMTradingBot v2.0 — The Z.M Update — March 2026*


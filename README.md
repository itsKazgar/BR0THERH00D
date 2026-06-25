<h1 align="center">BR0THERH00D</h1>

<p align="center">
  <b>A council of AI agents that share one memory and run a Solana trading desk —
  fully automated, free to run, non-custodial.</b>
</p>

<p align="center">
  Scans the market → debates each candidate → votes under hard risk rules →
  buys and sells on-chain, on its own.
</p>

---

## What it is

Most "AI trading bots" are one model in a loop. BR0THERH00D is a **team**:
13 voices — real AI reasoning agents plus rule-and-memory voters — sit on one
chessboard-style council and debate every candidate. A weighted quorum must
agree, and two seats hold veto power, before any money moves. It runs on free
AI models and free RPC tiers, and it never holds your keys for anyone but you.

> Full design: [`ARCHITECTURE.md`](ARCHITECTURE.md) ·
> Security & known issues (read before live): [`SECURITY.md`](SECURITY.md)

---

## Quick start (paper mode — no money, ~2 minutes)

```bash
# 1. install
pip install -r requirements.txt

# 2. configure — copy the template and add your free keys
cp .env.example .env
#   open .env and set:
#     GROQ_API_KEY=...     (free at console.groq.com)
#     HELIUS_API_KEY=...   (free at helius.dev)
#   leave TRADE_MODE=paper

# 3. run
python Start.py
```

`Start.py` is the only thing you ever run — it's the menu, the engine, and the
trader, all in one process. Pick a mode and it starts scanning, debating, and
paper-trading immediately — no wallet, no risk.

Press Ctrl+C any time for a clean shutdown.

---

## The five modes (the Start.py menu)

| # | Mode | What it does |
|---|------|--------------|
| 1 | Solo Paper Trade | The trader alone, simulated, no council debate |
| 2 | Paper + Agents | Full 13-seat council debates every candidate (simulated money) |
| 3 | Live Trading | Real funds. Requires a funded wallet. Only after testing |
| 4 | Dashboard | Launches the browser dashboard to build / edit agents |
| 5 | Assistant Mode | A personal AI assistant that shares the bot's memory |

Modes 2 and 3 also start six background workers (Whale Tracker, Pump Hunter,
News Scout, Risk Manager, Memory Keeper, Social Scanner) that feed the shared
brain so the council always has fresh data to vote on.

---

## Configuration (.env)

You only need an AI key to start in paper mode.

### AI brain (pick at least one - Groq is the free default)
| Var | Notes |
|---|---|
| GROQ_API_KEY | free + fast, recommended to start (console.groq.com) |
| OPENROUTER_API_KEY | free models too |
| ANTHROPIC_API_KEY / OPENAI_API_KEY | optional, if you want Claude / GPT |
| OLLAMA_URL + OLLAMA_MODEL | run a local model - no key, no cost |

### Trading
| Var | Notes |
|---|---|
| TRADE_MODE | paper (default) or live |
| SOLANA_RPC | your RPC URL - use a free Helius / QuickNode key |
| HELIUS_API_KEY | free at helius.dev - powers Whale Tracker + faster RPC |
| WALLET_ADDRESS | your public key |
| WALLET_PRIVATE_KEY | only for live trading. base58. Keep it secret. |

### Loop tuning (optional)
| Var | Default | Meaning |
|---|---|---|
| FAST_INTERVAL | 60 | seconds between social / watchlist scans |
| FULL_INTERVAL | 300 | seconds between market-wide scans |
| MIN_AGENTS_TRADE | 4 | council quorum required to trade |
| MIN_TOKEN_AGE_HOURS | 2 | reject tokens younger than this |

---

## Going live - the safety path (do NOT skip)

This bot buys and sells real money on its own. Earn that trust in steps:

1. Paper (TRADE_MODE=paper) - watch a full buy/sell cycle in simulation.
2. Devnet - point SOLANA_RPC at a devnet endpoint; confirm on-chain with fake money.
3. One tiny live trade (~$1) - watch both the buy and sell confirm on Solscan.
4. Then scale up.

Kill switch: python sellall.py sells every open position (asks to confirm).
emergency_agent.py arms an auto-sell on shutdown.

> The multi-user Telegram bot (telegram_bot.py) is not safe for public
> multi-user money yet - see SECURITY.md. Running it through Start.py
> is the path that's ready to test.

---

## How it works (30-second version)

Start.py scans and enriches a candidate, then the 13-seat council votes
(weighted, 2 veto seats, quorum required). If approved, core/jupiter.py
signs and confirms the buy. When TP or SL hits, the same module signs and
confirms the sell. An exit-advisory layer can nudge the stop tighter or
looser based on whether the original thesis still holds, learning from
this bot's own past wins and losses. Every agent reads and writes one
shared brain (SQLite).

- Non-custodial execution - swaps sign locally with your key.
- Confirmed on-chain - a trade is only recorded once it lands.
- Resilient - market calls retry with backoff; one flaky API never crashes a cycle.

---

## Project layout

Start.py - the menu AND the engine, all one process
core/unified_council.py - the 13-seat council
core/exit_consensus.py - exit advisory layer, learns from outcomes
core/persona_evolution.py - per-agent trust scoring
core/jupiter.py - buy / sell execution
core/consensus.py - the rule-based voters
core/brain.py - shared SQLite memory
agents/trading/ - scanner, trader
agents/intel/ - whale_tracker, news_scout, pump_hunter, risk_manager, memory_keeper
collective.py - the AI personas (SEER, QUANT, EXEC, GUARDIAN, CHAIN, REAPER)
brotha_api.py - dashboard API
ARCHITECTURE.md - full technical overview
SECURITY.md - security posture + known issues

Note: loop.py and colors.py are leftover files from an earlier iteration.
Start.py now does everything they used to do - they're not part of the
supported path, safe to ignore.

---

## Troubleshooting

- "No AI configured" -> add a GROQ_API_KEY to .env (free).
- Whale Tracker votes blind every time -> add a HELIUS_API_KEY (free at helius.dev).
- Slow / rate-limited -> set a real SOLANA_RPC, consider a second AI key.
- Nothing trades -> that's normal, the council is strict by design.
- Want it quieter -> full logs are in logs/brotha.log.

---

## Disclaimer

Trading crypto is risky; this software can lose money. It is provided as-is,
for research and educational use. You are responsible for testing it
(paper -> devnet -> small live) before risking real funds.

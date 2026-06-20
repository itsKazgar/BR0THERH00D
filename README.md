<h1 align="center">BR0THER-H00D</h1>

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

Most "AI trading bots" are one model in a loop. BR0THER-H00D is a **team**:
specialist agents (scanner, whale-tracker, news-scout, analyst, risk-manager…)
share one SQLite memory and vote on every trade. A **quorum** must agree and the
**Risk Manager can veto** before any money moves. It runs on free AI models and
free RPC tiers, and it never holds your keys for anyone but you.

> Full design: [`ARCHITECTURE.md`](ARCHITECTURE.md) ·
> Security & known issues (read before live): [`SECURITY.md`](SECURITY.md)

---

## Quick start (paper mode — no money, ~2 minutes)

```bash
# 1. install
pip install -r requirements.txt

# 2. configure — copy the template and add ONE free AI key to start
cp .env.example .env
#   open .env and set GROQ_API_KEY=...   (free at console.groq.com)
#   leave TRADE_MODE=paper

# 3. run
python Start.py
```

Pick **mode 1 or 2** at the menu. It starts scanning, debating, and paper-trading
immediately — no wallet, no risk. Watch the live heartbeat:

```
[♥ 14m02s] cycles=14 · full=3 · social=22 · debates=5 · trades=1 | next full scan in 142s
```

Press **Ctrl+C** any time for a clean shutdown.

---

## The five modes (the `Start.py` menu)

| # | Mode | What it does |
|---|------|--------------|
| 1 | **Solo Paper Trade** | Auto-trader only, simulated — the simplest way to watch it work |
| 2 | **Paper + Agents** | Auto-trader **+ the 8 intel agents** feeding the council (full simulation) |
| 3 | **Live Trading** | Real funds. Requires a funded wallet. **Only after testing — see below** |
| 4 | **Custom Mode** | Build / edit your own agents |
| 5 | **Assistant Mode** | A personal AI assistant that shares the bot's memory (prices, research, notes, todos) |

---

## Configuration (`.env`)

You only need an **AI key** to start in paper mode. Everything else is optional
until you go live.

### AI brain (pick at least one — Groq is the free default)
| Var | Notes |
|---|---|
| `GROQ_API_KEY` | free + fast, recommended to start (console.groq.com) |
| `OPENROUTER_API_KEY` | free models too |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | optional, if you want Claude / GPT |
| `OLLAMA_URL` + `OLLAMA_MODEL` | run a local model — no key, no cost |

The system auto-detects whatever you provide and falls back gracefully. One model
call per task — more keys buy resilience, **not** multiplied cost.

### Trading
| Var | Notes |
|---|---|
| `TRADE_MODE` | `paper` (default) or `live` |
| `SOLANA_RPC` | your RPC URL — use a free Helius / QuickNode key for real use |
| `WALLET_ADDRESS` | your public key |
| `WALLET_PRIVATE_KEY` | **only for live trading.** base58. Keep it secret. |

### Loop tuning (optional — sensible defaults)
| Var | Default | Meaning |
|---|---|---|
| `FAST_INTERVAL` | 60 | seconds between social / watchlist scans |
| `FULL_INTERVAL` | 300 | seconds between market-wide scans |
| `MIN_AGENTS_TRADE` | 4 | council quorum required to trade |
| `MIN_TOKEN_AGE_HOURS` | 2 | reject tokens younger than this |

---

## Going live — the safety path (do NOT skip)

This bot **buys and sells real money on its own.** Earn that trust in steps:

1. **Paper** (`TRADE_MODE=paper`) — watch a full buy → sell cycle in simulation.
2. **Devnet** — point `SOLANA_RPC` at a devnet endpoint; confirm a buy *and* a
   sell land on-chain with fake money.
3. **One tiny live trade** (~$1) — set `WALLET_PRIVATE_KEY`, `TRADE_MODE=live`,
   and watch both the buy and the sell confirm on Solscan.
4. **Then** scale up.

Kill switch: `python sellall.py` sells every open position (asks to confirm).
`emergency_agent.py` arms an auto-sell on shutdown.

> ⚠ The multi-user **Telegram** bot (`telegram_bot.py`) is **not** safe for public
> multi-user money yet — see [`SECURITY.md`](SECURITY.md). The single-user
> agent / loop above is the path that's ready to test.

---

## How it works (30-second version)

```
loop.py  ──▶  scan + enrich a candidate
         ──▶  THE COUNCIL  (weighted vote + risk veto + quorum)
         ──▶  approved?   →  core/jupiter.py  buy_token()   (sign + confirm)
         ──▶  TP / SL hit? →  core/jupiter.py  sell_token()  (sign + confirm)
              every agent reads / writes one shared brain (SQLite)
```

- **Non-custodial execution** — swaps sign locally with your key; nothing is held
  server-side.
- **Confirmed on-chain** — a trade is only recorded once the transaction lands.
- **Resilient** — all market calls retry with backoff (`core/http.py`); one flaky
  API never crashes a cycle.

---

## Project layout

```
Start.py              interactive launcher (the menu)
loop.py               the automated intelligence loop
core/
  jupiter.py          buy / sell execution (sign + confirm, real decimals)
  consensus.py        rule-based weighted council + veto
  brain.py            shared SQLite memory
  http.py             resilient HTTP (timeout + retry + backoff)
agents/
  trading/            scanner, trader
  intel/              whale_tracker, news_scout, pump_hunter, risk_manager, analyst, …
  assistant.py        personal assistant mode
collective.py         LLM council (debate + quorum + fail-safe veto)
brotha_api.py         dashboard API (auth-gated)
ARCHITECTURE.md       full technical overview
SECURITY.md           security posture + known issues (read before live)
```

---

## Troubleshooting

- **"No AI configured"** → add a `GROQ_API_KEY` to `.env` (free).
- **Slow / rate-limited** → set a real `SOLANA_RPC` (Helius free tier).
- **Nothing trades** → that's normal; the council is strict. Lower
  `MIN_AGENTS_TRADE` or `MIN_TOKEN_AGE_HOURS` to loosen it (paper first).
- **Want it quieter** → full logs are in `logs/brotha.log`; the console only shows
  warnings + the heartbeat.

---

## Disclaimer

Trading crypto is risky; this software can lose money. It is provided as-is, for
research and educational use. **You** are responsible for testing it (paper →
devnet → small live) before risking real funds.

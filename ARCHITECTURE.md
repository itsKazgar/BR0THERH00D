# Architecture — BR0THERH00D

A technical overview of how the system is put together: the components, how data
flows, where decisions are made, and the deliberate trade-offs. Written to be
read top-to-bottom by someone seeing the codebase for the first time.

---

## 1. What it is

A Solana trading system driven by a **council of specialist AI agents** that
share one memory. Agents scan the market, reason over candidates, vote on
trades under hard risk rules, and execute non-custodially through Jupiter. A web
dashboard and a Telegram bot sit on top for control and visibility.

**Stack:** Python · FastAPI + Flask · SQLite · solders/solana-py · Jupiter
aggregator · Helius RPC · pluggable LLMs (Groq / OpenRouter / Anthropic / OpenAI
/ local Ollama).

---

## 2. Entry points

| Entry | Runs | Purpose |
|---|---|---|
| `app.py` | `gunicorn app:app` (Procfile) | Public web app — the member gate / landing |
| `Start.py` | `python Start.py` | Interactive launcher — pick a mode, spawns agents |
| `brotha_api.py` | `uvicorn brotha_api:app` | Dashboard API (status, trades, files, control) |
| `telegram_bot.py` | long-running process | Telegram control surface |

There are **two trading orchestrations** (a known consolidation point, see §7):

- **Agent flow** — `Start.py` spawns each agent in `agents/` as its own process.
- **Loop flow** — `loop.py` drives the root-level modules in a single loop.

---

## 3. Component map

```
                        ┌────────────────────────┐
   market data feeds ──▶│  scanner / market_data │──┐
   (DexScreener, Gecko) └────────────────────────┘  │  candidates
                                                     ▼
                        ┌────────────────────────────────────┐
                        │            THE COUNCIL               │
                        │  consensus.py (rule-based, weighted) │
                        │  collective.py + multi_model_router  │
                        │  (LLM agents, quorum + veto)         │
                        └────────────────────────────────────┘
                                     │ verdict (BUY/HOLD/PASS)
                                     ▼
                        ┌────────────────────────┐
                        │   trader / jupiter.py  │  non-custodial
                        │   risk rules + exits   │  swap + confirm
                        └────────────────────────┘
                                     │
                   ┌─────────────────┼──────────────────┐
                   ▼                 ▼                  ▼
              core/brain.db     dashboard (HTTP)    Telegram
              (shared memory)   brotha_api.py       telegram_bot.py
```

### Agents (`agents/`)
- **trading/** — `scanner.py` (finds candidates), `trader.py` (executes, manages
  exits).
- **intel/** — `whale_tracker`, `news_scout`, `pump_hunter`, `risk_manager`,
  `analyst`, `memory_keeper`, `social_scout` — each a specialist that votes /
  writes to shared memory.

### The council (`core/`, `collective.py`, `multi_model_router.py`)
Two implementations, by design different in nature:
- **`core/consensus.py`** — deterministic, weighted voting with a Risk-Manager
  veto and a quorum (`VOTES_NEEDED`). Fast, auditable, no LLM cost.
- **`collective.py` + `multi_model_router.py`** — LLM agents debate; verdicts are
  parsed to a strict `BUY/HOLD/PASS` enum, gated by quorum, with **fail-safe
  veto** (a safety agent that errors blocks the trade rather than being ignored).

### Execution (`core/jupiter.py`)
Non-custodial swap engine: quotes from Jupiter, signs locally with the operator
key, broadcasts, and **polls `getSignatureStatuses` to confirm on-chain before
reporting success**. Token decimals are resolved on-chain (no hard-coded
assumptions); slippage is bounded (1% default).

### Shared memory (`core/brain.py` → SQLite)
Every agent reads/writes one persistent store, so signals compound across agents
and sessions. The scanner's find informs the analyst's call informs the risk
manager's veto.

### AI routing (`ai_engine.py`, `core/llm.py`)
Provider-agnostic: detects available keys and routes each agent to a suitable
model, falling back gracefully (Groq → OpenRouter → Ollama → rules). One model
call per task — more keys buy resilience, not multiplied cost.

---

## 4. Data stores

| Store | Holds |
|---|---|
| `core/brain.db` | shared agent memory, learnings, tomes, custom agents |
| `data/agent.db` | paper-trading portfolio / positions |
| `brotha.db` | dashboard/webhook events |

---

## 5. Security posture

- **Non-custodial trading** — swaps sign in the operator's own wallet; no funds
  are held by any web surface.
- **Dashboard API auth fails closed** — no token configured ⇒ access denied.
  Sensitive routes (wallet/keys/file/logs/control) require the token.
- **Secrets never served** — `.env` is excluded from the file API; keys come
  only from environment.
- **Public-mode hardening** — `DASHBOARD_PUBLIC=1` disables the interactive
  terminal and stops the token from being auto-handed out.
- **CORS** restricted to configured origins (never `*`).

> For an internet-facing deploy set: `DASHBOARD_PUBLIC=1`, a long random
> `DASHBOARD_TOKEN`, `HOOD_SECRET`, and your `SOLANA_RPC`.

---

## 6. Running it

```bash
pip install -r requirements.txt
cp .env.example .env      # add an AI key (Groq is a free default) + SOLANA_RPC
python Start.py           # interactive: pick Paper or Live mode
```

Start in **paper mode** — it mirrors the live engine with no funds at risk.

---

## 7. Known trade-offs / roadmap

Honest engineering notes (the parts a reviewer should know):

- **Two orchestrations coexist** (agent flow vs loop flow). Consolidating to one
  is the next structural cleanup; both currently work.
- **`trading.py` sell side is bookkeeping-only** — the multi-user Telegram path
  records closes but does not yet broadcast a token→SOL swap. Flagged in code;
  must be wired + tested before live use of that path. The primary
  `agents/trading/trader.py` + `core/jupiter.py` path does execute and confirm.
- **Logging** — moving from `print` to structured `logging` (with a trade audit
  trail) is in progress.
- **Tests** — execution (`core/jupiter.py`) and the council vote are the
  priority targets for a proper test suite.

---

## 8. Design principles

1. **Non-custodial first** — never hold user funds; sign locally.
2. **Fail safe with money** — confirm transactions, veto on uncertainty, treat a
   failed safety check as a block, never a silent approve.
3. **Cheap by default** — runs on free LLMs and free RPC tiers; more keys add
   resilience, not cost.
4. **One shared brain** — agents compound knowledge instead of working in silos.

# BR0THERH00D — cleanup & upgrade plan

Based on tracing the actual import graph (not guesses).

## Architecture reality (verified)

Production runs **`app.py`** (`Procfile: gunicorn app:app`). There are **two
parallel trading flows** in the repo:

- **Loop flow:** `loop.py` → `scanner.py`, `collective.py`, `alpha_engine.py`,
  `market_data.py`, `paper_trader.py`  (root-level modules)
- **Agent flow:** `Start.py` → spawns `agents/trading/*` + `agents/intel/*`
  as separate processes

Both partly coexist. The biggest structural upgrade is **picking one** as
canonical and retiring the other — but that's a design decision, so cleanup
below does NOT touch it.

## Step 1 — cleanup (safe, automated)

Run once from the repo root:

```bash
bash cleanup.sh
git add -A && git commit -m "chore: remove junk, backups, logs, stale collective/ dir"
```

Removes (all verified unused): terminal-paste artifact files, `*.bak`/`*.bak2`,
log files, the empty `db` stub, and the **stale `collective/` directory** (no
`__init__.py`, so nothing imports it — `from collective import` resolves to
`collective.py`, which is kept). Refreshes `.gitignore` so they don't return.

## Step 2 — pick a canonical flow (decision needed)

Decide: **agent flow** (`Start.py` + `agents/`) or **loop flow** (`loop.py`)?
The agent flow is newer and cleaner. Once chosen, retire the other and the
now-orphaned root modules (`trading.py`, `trader.py`, and whichever loop-only
files are no longer reached). Do this with tests in place, not blindly.

## Step 3 — code-quality upgrades (highest value first)

1. **Logging, not prints.** ~700 `print()` calls → Python `logging` with levels
   and a rotating file handler. In a trading bot you need a real audit trail.
2. **Kill bare `except:`** (~125 of them). A swallowed exception in a sell or
   stop-loss is money lost silently. Catch specific errors; log the rest.
3. **Split the monolith.** `telegram_bot.py` is 3,100+ lines. Break into
   `commands/`, `handlers/`, `formatting/`.
4. **Tests for the money paths.** Right now there's one `smoke_test.py`. Add
   tests around `core/jupiter.py` (swaps), the council vote, and position
   sizing / stop-loss.
5. **Project hygiene.** `pyproject.toml`, type hints on the core modules, and a
   `README` that states which flow is canonical so a newcomer isn't lost.

## Step 4 — substance upgrades

- **Trade audit log:** every decision (council votes, reason, fill price,
  slippage) to a structured log or table — makes the bot debuggable and
  trustworthy.
- **Config over constants:** thresholds/limits in one config, not scattered.
- **Reuse the hardened `core/jupiter.py`** everywhere (real decimals, on-chain
  confirmation, honeypot check) so no legacy path uses weaker execution.

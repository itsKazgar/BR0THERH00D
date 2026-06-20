# SECURITY & KNOWN ISSUES — read before going live

A full line-by-line review was done. The **fixable, safe** issues are fixed (see
git history / CODE_REVIEW.md). The items below need a **design decision + live
testing** and were deliberately NOT blind-patched, because a wrong fix to a
money path loses funds. Treat these as blockers for real-money / multi-user use.

## 🔴 Critical — the multi-user Telegram path (`telegram_bot.py`)
Do **not** run `telegram_bot.py` as a public multi-user money bot until these are
addressed:

1. **Wallet private keys are stored in plaintext** in SQLite
   (`users.wallet_private`, `private_tx_queue.temp_wallet_priv`). Anyone with
   read access to `data/agent.db` (or a backup/leak) can drain every wallet.
   → Don't custody user keys. Use non-custodial signing (the user signs in their
   own wallet, like the h00d.fun swap), or at minimum encrypt at rest with a key
   that isn't on the same box.
2. **Trades have no authorization or spend cap.** `buy_confirm_*`, `/autotrade`,
   and `/council trade` execute swaps with no per-user limit; `DAILY_SPEND_LIMIT`
   is defined but never enforced.
3. **`/autotrade off` targets the wrong table** (`auto_strategies` vs
   `autonomous_tasks`) — users may be unable to stop the auto-trader. Verify the
   table name and test stop/start before enabling autotrade.
4. **Default-amount buys.** The confirm button falls back to `0.1 SOL` if no
   amount was chosen — a spend should never be defaulted.
5. **"Private send" is UI theater** — it replies "queued!" but never moves funds.
   Either implement it or remove the button (misleading in a money app).
6. **Many commands are defined but never registered** (`/price`, `/balance`,
   `/wallet`, `/market`, `/council`, …) — they silently do nothing.

## 🟡 The sell side is now WIRED — but test before you trust it
`core/jupiter.py` now has a real `sell_token()` (plus `buy_token`,
`load_keypair`, `get_token_balance`) that signs + confirms a token→SOL swap
on-chain. The exit paths route through it:
- `agents/trading/trader.py` — auto TP/SL full-exit sells the actual on-chain
  balance via `jupiter.sell_token(...)`. This is the automated loop's brakes.
- `sellall.py` — LIVE mode now actually sells every position on-chain.
- `emergency_agent.py` — kill switch now actually sells on shutdown.
- `trading.py` `close_position` (Telegram path) — still bookkeeping-only; route
  it through `jupiter.sell_token` too if you use the Telegram trading flow.

⚠ **This moves real money autonomously and has NOT been run live from here.**
Before trusting it: (1) paper mode, (2) devnet, (3) one tiny live trade to watch
a buy AND a sell confirm on Solscan. Set `WALLET_PRIVATE_KEY` in `.env` for live.

## 🟠 Other notes
- Several data sources are dead in 2026 (public Nitter mirrors,
  `frontend-api.pump.fun`) → those intel layers return empty silently.
- Pervasive bare `except:` swallows API errors, so trade decisions can run on
  stale/missing data with no signal. Adding structured logging is the next pass.

## ✅ Hardening already applied
- Dashboard API (`brotha_api.py`): auth fails closed, CORS locked, secret/file
  routes gated, `.env` unreadable, terminal disabled in public mode.
- Swap engine (`core/jupiter.py`): on-chain confirmation, real decimals, 1% slippage.
- Council: real verdict parsing, quorum, fail-safe veto, no-data ≠ buy.
- SSRF blocked in `scraper.py` / `assistant_tools.py`.
- Crash guards (divide-by-zero on entry price / buy-sell ratio).
- Dead/broken files removed (`Analyst.py`, `Whaletracker.py`, `Moneykeepr.py`,
  `jupiter_price.py`, `extra_cmds.py`).

## The rule
Run **paper mode** first. Keep `brotha_api.py` on localhost unless
`DASHBOARD_PUBLIC=1` + a strong `DASHBOARD_TOKEN` are set. Do not run the
multi-user Telegram trading bot with real keys until items 1–6 above are done.

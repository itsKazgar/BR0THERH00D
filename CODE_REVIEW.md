# BR0THERH00D — full code review

Read file-by-file across the live code paths (API, trading, AI council, swap
engine). Findings are concrete with `file:line`. Tagged by severity. Nothing was
changed — this is the report.

> Headline: the product is ambitious and mostly works, but it has **critical
> security holes in the dashboard API** and **money-losing bugs in the trade
> execution and council logic** that must be fixed before any live trading or
> public exposure.

---

## 🔴 CRITICAL — dashboard API (`brotha_api.py`)
This FastAPI app (exposed on `0.0.0.0` by `Start.py` mode 4 / the terminal) is
the highest-risk surface.

1. **RCE via WebSocket shell** — `brotha_api.py:1248` `/ws/terminal` spawns a PTY
   running `Start.py` and pipes raw bytes. Behind a bypassable token (below) this
   is remote code execution.
2. **Auth fails OPEN** — `:95-101` `_token_ok()` returns `True` when the token is
   falsy. If the token ever fails to persist, *every* protected route opens.
3. **Token disclosure** — `:130-137` `/auth/handshake` hands the dashboard token
   to any request that *looks* local (`request.client.host == 127.0.0.1`),
   which a proxy/SSRF can spoof.
4. **Secret file read** — `:1141` `GET /file?path=.env` is **unauthenticated** and
   `.env` is in the allowed extensions → returns wallet private key + all API
   keys + the dashboard token to anyone.
5. **Free wallet/keys** — `:358` `POST /wallet/create` is unauthenticated and
   returns a fresh **private key**.
6. **RCE via custom agents** — `:724` `POST /agents/custom/code` writes
   attacker Python; the "safety" check is a substring blocklist (bypass with
   `__import__`, `eval`, `open`). The bot then imports it.
7. **Source disclosure** — `:758` `GET /agents/custom/code` unauthenticated,
   returns all custom-agent source.
8. **CORS `*`** — `:52` every endpoint callable cross-origin from any website.

→ **Do not expose `brotha_api.py` to any network until these are fixed.** It's
fine only on `127.0.0.1` for local single-user use, and even then the gate
needs to fail *closed*.

## 🔴 CRITICAL — money-losing bugs (trade execution)

1. **No transaction confirmation** — `core/jupiter.py:84` `execute_swap` returns
   `success:True` the moment `sendTransaction` returns a signature. A dropped /
   failed-on-chain tx is recorded as a **successful buy/sell**. Affects every
   path: `agents/trading/trader.py:454/543/705/734`, `trading.py:411`.
2. **Wrong sell amounts** — sells pass hardcoded `input_decimals=6`
   (`trader.py:540/702/731`); any 9-decimal token (most pump.fun coins) sells
   10³× the wrong size.
3. **30% default slippage** — `core/jupiter.py:10` `slippage_bps=3000`. Massive
   MEV/loss exposure on every trade.
4. **Take-profit never sells** — `trading.py:498-518` sets `tp_hit=1` and logs but
   never calls a swap; positions ride past TP with only SL able to close.
5. **Paper accounting wrong** — `paper_trader.py:171/176` abandons the moon-bag
   tokens on every TP; `:265` portfolio value double-counts realized PnL.
6. **Conflicting DB schemas** — `paper_trader.py` and root `trader.py` define
   different `positions` tables on the **same** `data/agent.db`; whichever runs
   `CREATE TABLE IF NOT EXISTS` first wins, the other's inserts misalign.
7. **Two SOL price sources** — `core/jupiter.py` uses CoinGecko while sizing uses
   another; the same trade is priced twice → size drift, and CoinGecko is
   rate-limited (single point of failure).

## 🟠 HIGH — the AI council is shakier than it looks
The "council" is the selling point, so these matter for credibility.

1. **Substring voting** — `multi_model_router.py:195` decides via `"BUY" in
   text.upper()`. "do **not** BUY" counts as BUY; hedged answers count as both.
2. **Defaults to BUY/abstain-as-yes** — `consensus.py:122-130` Memory Keeper votes
   BUY on "no data / neutral"; `collective.py:87` the **veto is bypassed** if the
   safety agent errors (returns HOLD, which fires neither veto nor pass).
3. **Unvalidated LLM JSON → trade** — `collective.py:34-41` takes the substring
   between `{` and `}`, `json.loads`, and trusts `decision`/`confidence` with no
   enum/schema check.
4. **Prompt injection everywhere** — token names + scraped social text are
   interpolated raw into prompts (`council.py:180`, `collective.py:47`,
   `multi_model_router.py:133`). A malicious token name can rewrite the agents'
   instructions.
5. **No LLM timeouts/retries that matter** — `llm.py` Ollama `timeout=120` stalls
   the loop; failures degrade to empty strings treated as valid answers.
6. **Two divergent councils** — rule-based (`core/consensus.py`, `VOTES_NEEDED=7`)
   vs LLM-text (`collective.py`/`multi_model_router.py`), different DBs and vote
   semantics. Risk: the "safe" one is bypassed by the other.

## 🟠 HIGH — web app (`app.py`, the Procfile prod entry)
1. **Stored XSS** — `app.py:227/266/270` usernames rendered with `|safe` and not
   run through `_esc()`; `<`,`>`,quotes allowed in usernames → stored XSS.
2. **Per-worker secret key** — `app.py:16` falls back to a random key per process;
   under multi-worker gunicorn, sessions break unless `HOOD_SECRET` is set.
3. **Pay bypass** — `app.py:203` `/pay/dev-approve` self-activates when PayPal
   creds are unset (fail-open on config).

## 🟡 MEDIUM — structure & correctness
- **Wallet env var mismatch** — `add_wallet.py` writes `WALLET_PRIVATE_KEY`,
  `brotha_api.py` reads `WALLET_PRIVATE_KEY_B58`, live mode reads
  `WALLET_ADDRESS`. The setup tool's key likely isn't found at trade time.
- **Threshold/comment mismatches** — `trading.py:43-47`, `scanner.py:225/40`,
  `consensus.py:27` document one number and enforce another (e.g. "TP 60%" but
  code is 15%; "3/5 votes" but `VOTES_NEEDED=7`). Misleads anyone trusting it.
- **Duplication** — three trading engines, two councils, `collective/` dead dir.
- **~700 `print()`**, **~125 bare `except:`** — in a trading bot, a swallowed
  exception around a sell is silent money loss.

## ✅ What's good
- No hardcoded secrets / no `eval`/`exec` / no shell injection found.
- All keys come from env.
- The architecture *ideas* (council, tiered exits, honeypot checks in the newer
  code) are sound — the issues are in execution, not vision.

---

## Priority order to fix
1. **Lock down `brotha_api.py`** — auth fail-closed, remove unauth secret/keys/
   file/shell routes, restrict CORS, never expose off localhost. (security)
2. **Trade execution** — add tx confirmation polling, real decimals on sells,
   sane slippage (1–3%), make TP actually sell. (money)
3. **Council** — parse model output to a strict enum, enforce quorum, fix
   veto-on-error, treat failures as abstentions not approvals. (money + trust)
4. **Pick one trading engine + one council**, delete the rest. (clarity)
5. **Logging + kill bare excepts** on money paths. (debuggability)

> Note: a hardened `core/jupiter.py` (real decimals, confirmation, honeypot,
> bounded slippage) was written previously but lives on a feature branch — the
> `main` reviewed here still has the old version. Getting that branch merged
> fixes several of the money bugs above at once.

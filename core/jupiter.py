"""
Jupiter swap layer — works on ANY Solana SPL token.

Design goals (and the bugs this fixes):
  • Real on-chain decimals for every token, looked up from RPC and cached.
    The old code hard-coded input_decimals=6 on sells, so a 9-decimal token
    was sold at 1000x the wrong size. get_quote now resolves the true decimals
    itself; the input_decimals argument is only a fallback if RPC is down.
  • Bounded slippage. The old default was 3000 bps (30%). Default is now
    sane and every quote is clamped to MAX_SLIPPAGE_BPS.
  • Verified execution. execute_swap now confirms the transaction on-chain
    (getSignatureStatuses) before reporting success, so a position is never
    recorded for a swap that never landed. Set JUPITER_SKIP_CONFIRM=1 to
    restore the old fire-and-forget behaviour.
  • "Fetch any coin": resolve_token() turns a symbol/name OR a mint into a
    mint address; is_tradable()/honeypot_check() confirm a coin can actually
    be bought AND sold before real funds move.

All network calls fail safe (return None / False / an error string) rather
than raising, so callers degrade gracefully when an API is unreachable.
"""

import os, time, base64, requests

# Jupiter endpoints. JUPITER_BASE lets you point at the paid host (api.jup.ag)
# or the free tier (lite-api.jup.ag) without code changes.
JUPITER_BASE  = os.getenv("JUPITER_BASE", "https://api.jup.ag").rstrip("/")
JUPITER_QUOTE = f"{JUPITER_BASE}/swap/v1/quote"
JUPITER_SWAP  = f"{JUPITER_BASE}/swap/v1/swap"

RPC_URL       = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")

USDC_MINT     = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_MINT      = "So11111111111111111111111111111111111111112"
USDC_DECIMALS = 6
SOL_DECIMALS  = 9

# Slippage guardrails (basis points). 100 bps = 1%.
DEFAULT_SLIPPAGE_BPS = int(os.getenv("DEFAULT_SLIPPAGE_BPS", "100"))
MAX_SLIPPAGE_BPS     = int(os.getenv("MAX_SLIPPAGE_BPS", "1000"))   # hard ceiling = 10%

# Confirmation
CONFIRM_TIMEOUT_S = int(os.getenv("JUPITER_CONFIRM_TIMEOUT", "60"))
SKIP_CONFIRM      = os.getenv("JUPITER_SKIP_CONFIRM", "") not in ("", "0", "false", "False")

# ── caches ────────────────────────────────────────────────────────────────
_decimals_cache: dict = {SOL_MINT: SOL_DECIMALS, USDC_MINT: USDC_DECIMALS}
_resolve_cache:  dict = {}


def _clamp_slippage(bps) -> int:
    try:
        bps = int(bps)
    except (TypeError, ValueError):
        bps = DEFAULT_SLIPPAGE_BPS
    if bps <= 0:
        bps = DEFAULT_SLIPPAGE_BPS
    return min(bps, MAX_SLIPPAGE_BPS)


# ── token metadata ─────────────────────────────────────────────────────────
def get_token_decimals(mint: str, fallback=None):
    """Real on-chain decimals for an SPL mint, via RPC getTokenSupply. Cached.

    Returns the integer decimals, or `fallback` (then None) if it can't be
    determined — callers must handle None rather than silently assume 6.
    """
    if mint in _decimals_cache:
        return _decimals_cache[mint]
    try:
        r = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenSupply", "params": [mint],
        }, timeout=10)
        dec = int(r.json()["result"]["value"]["decimals"])
        _decimals_cache[mint] = dec
        return dec
    except Exception:
        return fallback


def _looks_like_mint(s: str) -> bool:
    # base58 (no 0 O I l); Solana mints are 32–44 chars.
    if not s or " " in s:
        return False
    if not (32 <= len(s) <= 44):
        return False
    return s.isalnum() and all(c not in "0OIl" for c in s)


def resolve_token(query: str):
    """Turn a mint, symbol, or name into a mint address.

    • If `query` already looks like a mint, it's returned as-is.
    • Otherwise we search DexScreener for the highest-liquidity Solana match.
    Returns the mint string, or None if nothing usable is found.
    """
    if not query:
        return None
    query = query.strip()
    if _looks_like_mint(query):
        return query

    key = query.lower()
    if key in _resolve_cache:
        return _resolve_cache[key]

    try:
        r = requests.get(
            "https://api.dexscreener.com/latest/dex/search",
            params={"q": query}, timeout=10)
        pairs = r.json().get("pairs") or []
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"
                     and p.get("baseToken", {}).get("address")]

        def liq(p):
            return (p.get("liquidity") or {}).get("usd", 0) or 0

        exact = [p for p in sol_pairs
                 if p["baseToken"].get("symbol", "").lower() == key]
        pick = max(exact or sol_pairs, key=liq, default=None)
        if pick:
            mint = pick["baseToken"]["address"]
            _resolve_cache[key] = mint
            return mint
    except Exception:
        pass
    return None


# ── quoting ────────────────────────────────────────────────────────────────
def get_quote(input_mint: str, output_mint: str, amount: float,
              slippage_bps=DEFAULT_SLIPPAGE_BPS, input_decimals=None):
    """Get a Jupiter quote.

    `amount` semantics (unchanged for callers):
      • input is SOL  → `amount` is a USD value, converted SOL→lamports.
      • input is USDC → `amount` is a USD value.
      • input is any other token → `amount` is a HUMAN token count
        (e.g. 1234.5 tokens), scaled by the token's real decimals.

    Decimals are now resolved on-chain; `input_decimals` is only used as a
    fallback when the RPC lookup fails.

    Returns (quote_dict, None) on success, or (None, "error string").
    """
    try:
        slippage_bps = _clamp_slippage(slippage_bps)

        if input_mint == SOL_MINT:
            sol_price = _sol_price_usd()
            if not sol_price:
                return None, "could not fetch SOL price for conversion"
            amount_raw = int((amount / sol_price) * (10 ** SOL_DECIMALS))
        elif input_mint == USDC_MINT:
            amount_raw = int(amount * (10 ** USDC_DECIMALS))
        else:
            dec = get_token_decimals(input_mint, fallback=input_decimals)
            if dec is None:
                return None, f"could not resolve decimals for {input_mint}"
            amount_raw = int(amount * (10 ** dec))

        if amount_raw <= 0:
            return None, f"amount_raw={amount_raw} too small"

        r = requests.get(JUPITER_QUOTE, params={
            "inputMint":   input_mint,
            "outputMint":  output_mint,
            "amount":      amount_raw,
            "slippageBps": slippage_bps,
        }, timeout=12)
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            return None, data["error"]
        if not data or not data.get("routePlan"):
            return None, "no route found (token may be untradable)"
        return data, None
    except Exception as e:
        return None, str(e)


def _sol_price_usd():
    """SOL price in USD, derived from a Jupiter 1 SOL → USDC quote (no extra API)."""
    try:
        r = requests.get(JUPITER_QUOTE, params={
            "inputMint":   SOL_MINT,
            "outputMint":  USDC_MINT,
            "amount":      10 ** SOL_DECIMALS,   # exactly 1 SOL
            "slippageBps": 50,
        }, timeout=10)
        out = int(r.json()["outAmount"])
        return out / (10 ** USDC_DECIMALS)
    except Exception:
        return None


# ── tradability / honeypot screen ──────────────────────────────────────────
def is_tradable(mint: str, probe_usd: float = 5.0) -> bool:
    """True if a small SOL→token buy currently routes."""
    q, err = get_quote(SOL_MINT, mint, probe_usd)
    return err is None and bool(q)


def honeypot_check(mint: str, probe_usd: float = 5.0) -> dict:
    """Quote a buy then a sell of what that buy yields.

    A token that can be bought but not sold (no sell route, or a catastrophic
    price impact) is the classic honeypot. Returns:
      {"safe": bool, "reason": str, "buy_impact": float, "sell_impact": float}
    Fails safe: any unexpected error → safe=False.
    """
    try:
        buy, err = get_quote(SOL_MINT, mint, probe_usd)
        if err or not buy:
            return {"safe": False, "reason": f"no buy route: {err}",
                    "buy_impact": 0.0, "sell_impact": 0.0}

        dec = get_token_decimals(mint)
        if dec is None:
            return {"safe": False, "reason": "unknown decimals",
                    "buy_impact": 0.0, "sell_impact": 0.0}

        tokens_out = int(buy["outAmount"]) / (10 ** dec)
        sell, serr = get_quote(mint, SOL_MINT, tokens_out)
        if serr or not sell:
            return {"safe": False, "reason": f"cannot sell (honeypot): {serr}",
                    "buy_impact": float(buy.get("priceImpactPct", 0) or 0),
                    "sell_impact": 0.0}

        buy_impact  = float(buy.get("priceImpactPct", 0) or 0)
        sell_impact = float(sell.get("priceImpactPct", 0) or 0)
        # >35% impact on a $5 sell means the route is a trap.
        if sell_impact > 0.35:
            return {"safe": False, "reason": f"sell impact {sell_impact:.0%} too high",
                    "buy_impact": buy_impact, "sell_impact": sell_impact}
        return {"safe": True, "reason": "ok",
                "buy_impact": buy_impact, "sell_impact": sell_impact}
    except Exception as e:
        return {"safe": False, "reason": f"check error: {e}",
                "buy_impact": 0.0, "sell_impact": 0.0}


# ── execution ──────────────────────────────────────────────────────────────
def execute_swap(wallet_keypair, quote_response: dict) -> dict:
    """Sign, send, and (unless JUPITER_SKIP_CONFIRM) confirm a swap.

    Returns {"success": bool, "tx": str, "confirmed": bool, "error": str}.
    `success` means the transaction was sent AND confirmed on-chain — a quote
    that never lands will not report success, so no phantom position is booked.
    """
    try:
        from solders.transaction import VersionedTransaction

        pubkey = str(wallet_keypair.pubkey())
        body = {
            "quoteResponse":             quote_response,
            "userPublicKey":             pubkey,
            "wrapAndUnwrapSol":          True,
            "dynamicComputeUnitLimit":   True,
            "prioritizationFeeLamports": "auto",
        }
        r = requests.post(JUPITER_SWAP, json=body, timeout=15)
        swap_data = r.json()
        if "error" in swap_data:
            return {"success": False, "tx": "", "confirmed": False, "error": swap_data["error"]}

        tx_bytes  = base64.b64decode(swap_data["swapTransaction"])
        tx        = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(tx.message, [wallet_keypair])

        rpc_r = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method":  "sendTransaction",
            "params":  [
                base64.b64encode(bytes(signed_tx)).decode(),
                {"encoding": "base64", "skipPreflight": False,
                 "preflightCommitment": "confirmed"},
            ],
        }, timeout=30)
        result = rpc_r.json()
        if "error" in result:
            return {"success": False, "tx": "", "confirmed": False, "error": str(result["error"])}

        tx_sig = result.get("result", "")
        if not tx_sig:
            return {"success": False, "tx": "", "confirmed": False, "error": "no signature returned"}

        if SKIP_CONFIRM:
            return {"success": True, "tx": tx_sig, "confirmed": False, "error": ""}

        ok, cerr = confirm_transaction(tx_sig)
        return {"success": ok, "tx": tx_sig, "confirmed": ok,
                "error": "" if ok else f"sent but not confirmed: {cerr}"}
    except Exception as e:
        return {"success": False, "tx": "", "confirmed": False, "error": str(e)}


def confirm_transaction(tx_sig: str, timeout_s: int = CONFIRM_TIMEOUT_S):
    """Poll getSignatureStatuses until the tx is confirmed/finalized or times out."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.post(RPC_URL, json={
                "jsonrpc": "2.0", "id": 1,
                "method":  "getSignatureStatuses",
                "params":  [[tx_sig], {"searchTransactionHistory": True}],
            }, timeout=10)
            val = (r.json().get("result", {}).get("value") or [None])[0]
            if val:
                if val.get("err"):
                    return False, f"on-chain error: {val['err']}"
                if val.get("confirmationStatus") in ("confirmed", "finalized"):
                    return True, ""
        except Exception:
            pass
        time.sleep(2)
    return False, "confirmation timed out"


# ── wallet / token balances ─────────────────────────────────────────────────
def load_keypair():
    """Load the trading wallet as a solders Keypair from env.

    Accepts WALLET_PRIVATE_KEY (or WALLET_PRIVATE_KEY_B58) as base58, or a JSON
    int array. Returns None if unset/invalid — callers must handle None and must
    NOT trade without a key.
    """
    pk = (os.getenv("WALLET_PRIVATE_KEY") or os.getenv("WALLET_PRIVATE_KEY_B58") or "").strip()
    if not pk:
        return None
    try:
        from solders.keypair import Keypair
        if pk.startswith("["):
            import json
            return Keypair.from_bytes(bytes(json.loads(pk)))
        import base58
        return Keypair.from_bytes(base58.b58decode(pk))
    except Exception:
        return None


def get_token_balance(pubkey: str, mint: str) -> float:
    """How many of `mint` the wallet holds, in human units (0.0 if none)."""
    try:
        r = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [pubkey, {"mint": mint}, {"encoding": "jsonParsed"}],
        }, timeout=10)
        accounts = r.json().get("result", {}).get("value", [])
        total = 0.0
        for a in accounts:
            ui = a["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmount")
            total += float(ui or 0)
        return total
    except Exception:
        return 0.0


# ── high-level buy / sell (sign + confirm) ───────────────────────────────────
def buy_token(wallet_keypair, mint: str, usd_amount: float,
              slippage_bps=DEFAULT_SLIPPAGE_BPS) -> dict:
    """Buy `usd_amount` (USD) worth of `mint` with SOL. Signs + confirms.
    Returns {"success","tx","confirmed","error"}.
    """
    quote, err = get_quote(SOL_MINT, mint, usd_amount, slippage_bps=slippage_bps)
    if err or not quote:
        return {"success": False, "tx": "", "confirmed": False, "error": f"no buy route: {err}"}
    return execute_swap(wallet_keypair, quote)


def sell_token(wallet_keypair, mint: str, amount_tokens: float = None,
               fraction: float = 1.0, slippage_bps=DEFAULT_SLIPPAGE_BPS) -> dict:
    """Sell an SPL token back to SOL — sign + confirm on-chain.

    This is the real exit the automated loop calls on take-profit / stop-loss /
    emergency — the 'brakes' that were previously missing (old code only updated
    a database and falsely reported a sale).

      • amount_tokens: exact human token amount to sell.
      • If amount_tokens is None, sells `fraction` (default 1.0 = everything) of
        the wallet's CURRENT on-chain balance of `mint` — so it always sells what
        you actually hold, never a stale tracked number.

    Returns {"success","tx","confirmed","sold_tokens","sol_received","error"}.
    Fails safe (success=False) on any error.
    """
    res = {"success": False, "tx": "", "confirmed": False,
           "sold_tokens": 0.0, "sol_received": 0.0, "error": ""}
    try:
        pubkey = str(wallet_keypair.pubkey())
        if amount_tokens is None:
            held = get_token_balance(pubkey, mint)
            amount_tokens = held * max(0.0, min(fraction, 1.0))
        if not amount_tokens or amount_tokens <= 0:
            res["error"] = "nothing to sell (zero balance/amount)"
            return res

        quote, err = get_quote(mint, SOL_MINT, amount_tokens, slippage_bps=slippage_bps)
        if err or not quote:
            res["error"] = f"no sell route: {err}"
            return res

        swap = execute_swap(wallet_keypair, quote)
        res["tx"]        = swap.get("tx", "")
        res["confirmed"] = swap.get("confirmed", False)
        if not swap.get("success"):
            res["error"] = swap.get("error", "swap failed/not confirmed")
            return res

        res["success"]     = True
        res["sold_tokens"] = amount_tokens
        try:
            res["sol_received"] = int(quote.get("outAmount", 0)) / (10 ** SOL_DECIMALS)
        except Exception:
            pass
        return res
    except Exception as e:
        res["error"] = str(e)
        return res


# ── balances ───────────────────────────────────────────────────────────────
def get_wallet_balance(pubkey: str) -> dict:
    """SOL and USDC balances for a wallet."""
    out = {"sol": 0.0, "usdc": 0.0}
    try:
        r = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance", "params": [pubkey],
        }, timeout=10)
        out["sol"] = round(r.json().get("result", {}).get("value", 0) / 1e9, 4)

        r2 = requests.post(RPC_URL, json={
            "jsonrpc": "2.0", "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [pubkey, {"mint": USDC_MINT}, {"encoding": "jsonParsed"}],
        }, timeout=10)
        accounts = r2.json().get("result", {}).get("value", [])
        if accounts:
            ui = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
            out["usdc"] = round(float(ui or 0), 2)
        return out
    except Exception as e:
        out["error"] = str(e)
        return out

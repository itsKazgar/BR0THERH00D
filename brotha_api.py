"""
brotha_api.py — BR0THA Dashboard API Server
Fixed: duplicate routes, /status shape, POST /votes, POST /keys, /env/update

Run: uvicorn brotha_api:app --host 0.0.0.0 --port 8000 --reload
"""

import os, sys, sqlite3, json, time, subprocess, random
from datetime import datetime
from pathlib import Path

BOT_DIR = Path(__file__).parent
sys.path.insert(0, str(BOT_DIR))

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from emergency_agent import install_emergency_handler
from dotenv import load_dotenv

load_dotenv(BOT_DIR / ".env", override=True)
install_emergency_handler()

# ── lazy imports ───────────────────────────────────────────────────────────────
try:
    from agent_personas import COUNCIL_CONFIG, PERSONAS
    PERSONAS_OK = True
except Exception as e:
    PERSONAS_OK = False
    PERSONAS = {}
    COUNCIL_CONFIG = {}
    print(f"[WARN] agent_personas: {e}")

try:
    from paper_trader import get_portfolio, get_open_positions, init_paper_db
    PAPER_OK = True
except Exception as e:
    PAPER_OK = False
    print(f"[WARN] paper_trader: {e}")

DB_PATH  = BOT_DIR / "data" / "agent.db"
ENV_PATH = BOT_DIR / ".env"

app = FastAPI(title="BR0THA API", version="2.0")

@app.get("/")
def dashboard():
    return FileResponse(str(BOT_DIR / "brotha_dashboard.html"))

# CORS: same-origin dashboard needs none; allow only explicitly-listed origins.
# Set BROTHA_ALLOWED_ORIGINS=https://your.site (comma-separated) if you embed the
# dashboard cross-origin. Default = localhost only. Never "*": this API exposes
# wallet/keys/file routes.
_origins = [o.strip() for o in os.getenv(
    "BROTHA_ALLOWED_ORIGINS",
    "http://localhost,http://127.0.0.1,http://localhost:8000,http://127.0.0.1:8000"
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AUTH GATE  —  auto-generates a token on first run, persists it to .env,
#  and hands it to the dashboard automatically when both run on the same machine.
#  Local users never see or think about it. Remote users are protected by default.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import hmac, secrets

def _load_or_create_token() -> str:
    """Return the dashboard token. If none exists, generate one and save it to .env."""
    tok = os.getenv("DASHBOARD_TOKEN", "").strip()
    if tok:
        return tok
    # generate a fresh one
    tok = secrets.token_urlsafe(24)
    try:
        env_file = BOT_DIR / ".env"
        existing = env_file.read_text() if env_file.exists() else ""
        if "DASHBOARD_TOKEN=" in existing:
            # replace the empty value line
            lines = existing.splitlines()
            lines = [(f"DASHBOARD_TOKEN={tok}" if l.strip().startswith("DASHBOARD_TOKEN=") else l) for l in lines]
            env_file.write_text("\n".join(lines) + "\n")
        else:
            with open(env_file, "a") as f:
                f.write(f"\nDASHBOARD_TOKEN={tok}\n")
        os.environ["DASHBOARD_TOKEN"] = tok
        print(f"\n  🔐 Auto-generated a dashboard access code and saved it to .env.")
        print(f"     The dashboard picks this up automatically on this machine — nothing to do.")
        print(f"     For remote access, your code is:  {tok}\n")
    except Exception as e:
        print(f"  ⚠️  could not persist DASHBOARD_TOKEN ({e}); using in-memory token for this session")
        os.environ["DASHBOARD_TOKEN"] = tok
    return tok

DASHBOARD_TOKEN = _load_or_create_token()

# Public-deployment flag. Set DASHBOARD_PUBLIC=1 on any internet-facing host:
# it stops /auth/handshake from auto-handing out the token (must be entered),
# and disables the interactive terminal websocket.
_PUBLIC = os.getenv("DASHBOARD_PUBLIC", "").strip().lower() in ("1", "true", "yes")

def _token_ok(token: str) -> bool:
    """Constant-time compare. FAILS CLOSED: no token configured = deny."""
    if not DASHBOARD_TOKEN:
        return False          # was: return True (fail-open) — never allow an empty gate
    if not token:
        return False
    return hmac.compare_digest(token, DASHBOARD_TOKEN)

def _is_local(request) -> bool:
    """True only if the request genuinely originates from the same machine (loopback).
    If the bot sits behind a reverse proxy, ALL requests appear local — so when a
    proxy forwarding header is present, we treat the request as REMOTE to be safe
    (the user just enters the code once, which is correct for a public deployment)."""
    try:
        # If a proxy is in front, don't trust loopback — force the code path.
        fwd = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        if fwd:
            return False
        host = request.client.host if request and request.client else ""
        return host in ("127.0.0.1", "::1", "localhost")
    except Exception:
        return False

def require_auth(authorization: str = Header(default=""), x_dashboard_token: str = Header(default="")):
    """FastAPI dependency for sensitive HTTP endpoints.
    Accepts 'Authorization: Bearer <token>' or 'X-Dashboard-Token: <token>'."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_dashboard_token:
        token = x_dashboard_token.strip()
    if not _token_ok(token):
        raise HTTPException(status_code=401, detail="unauthorized")
    return True

@app.get("/auth/handshake")
def auth_handshake(request: Request):
    """Dashboard calls this on connect. If the request is LOCAL (same machine),
    hand back the token automatically so local users never type anything.
    If REMOTE, return only that a gate exists — the token must be supplied.
    On a public deployment (DASHBOARD_PUBLIC=1) the token is NEVER auto-returned."""
    if _is_local(request) and not _PUBLIC:
        return {"local": True, "gate_enabled": True, "token": DASHBOARD_TOKEN}
    return {"local": False, "gate_enabled": True, "token": None}

@app.get("/auth/check")
def auth_check(authorization: str = Header(default=""), x_dashboard_token: str = Header(default="")):
    """Verify a token the user typed (remote access)."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_dashboard_token:
        token = x_dashboard_token.strip()
    return {"gate_enabled": bool(DASHBOARD_TOKEN), "ok": _token_ok(token)}


_bot_process = None

# ── helpers ────────────────────────────────────────────────────────────────────

def db():
    os.makedirs(DB_PATH.parent, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def write_env_key(key: str, value: str):
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.strip().startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")

def fear_and_greed() -> dict:
    import httpx
    try:
        r = httpx.get("https://api.alternative.me/fng/?limit=1", timeout=5)
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except:
        return {"value": 50, "label": "Neutral"}

def bot_running() -> bool:
    global _bot_process
    if _bot_process and _bot_process.poll() is None:
        return True
    try:
        import psutil
        for proc in psutil.process_iter(["cmdline"]):
            cmdline = " ".join(proc.info["cmdline"] or [])
            if "loop.py" in cmdline or "telegram_bot.py" in cmdline or "start.py" in cmdline or "trader.py" in cmdline:
                return True
    except:
        pass
    return False

# ── startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    os.makedirs(BOT_DIR / "data", exist_ok=True)
    if PAPER_OK:
        try:
            init_paper_db()
        except:
            pass
    print("BR0THA API v2 running — http://0.0.0.0:8000")
    print("Docs → http://localhost:8000/docs")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATUS  —  dashboard reads: trades, version, positions[]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/status")
def get_status():
    fg = fear_and_greed()
    positions = []
    trade_count = 0
    balance = 100.0
    total_pnl = 0.0
    try:
        import sqlite3, json as _json
        _db = sqlite3.connect(str(BOT_DIR / "core" / "brain.db"))
        _live = os.getenv('TRADE_MODE','paper').lower() == 'live'
        _key  = 'trader_live' if _live else 'trader_paper'
        _row = _db.execute("SELECT data FROM state WHERE agent=?", (_key,)).fetchone()
        _db.close()
        if _row:
            _data = _json.loads(_row[0])
            balance = round(_data.get("balance", 100.0), 2)
            total_pnl = round(_data.get("total_pnl", 0.0), 2)
            trade_count = _data.get("trades", 0)
            for _mint, _pos in _data.get("positions", {}).items():
                positions.append({
                    "symbol":   _pos.get("name", _mint[:8]),
                    "strategy": "scalp" if _pos.get("hold_cap", 120) <= 20 else "swing",
                    "amount":   round(_pos.get("size_usd", 0), 2),
                    "pnl":      round(_pos.get("pnl_usd", 0), 2),
                    "status":   "open",
                })
    except Exception as _e:
        print(f"[status] error: {_e}")
    return {
        "trades":        trade_count,
        "version":       "2.0",
        "positions":     positions,
        "balance":       balance,
        "total_pnl":     total_pnl,
        "running":       bot_running(),
        "fear_greed":    fg["value"],
        "fg_label":      fg["label"],
        "paper_trading": os.getenv("TRADE_MODE", "paper").lower() != "live",
        "ts":            datetime.utcnow().isoformat(),
    }

@app.get("/votes")
def get_vote_log(limit: int = 20):
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT token, agent, decision, confidence, weight, timestamp "
                "FROM council_votes ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [
            {"token": r[0], "agent": r[1], "decision": r[2],
             "confidence": r[3], "weight": r[4], "ts": r[5]}
            for r in rows
        ]
    except:
        return []


class VoteRequest(BaseModel):
    agents: list
    user_id: str = "dashboard"
    token: Optional[str] = None

@app.post("/votes")
async def run_council_vote(req: VoteRequest):
    """
    Dashboard POSTs here to trigger a live council vote.
    Tries ai_engine / multi_model_router if available,
    falls back to a clean weighted simulation.
    """
    agents = req.agents
    if not agents:
        raise HTTPException(400, "no agents provided")

    # ── try real AI vote ───────────────────────────────────────────────────
    try:
        from multi_model_router import council_vote, tally_votes
        token = req.token or "SOL"
        raw_votes = await council_vote(agents, token)
        result    = tally_votes(raw_votes, agents)
        return result
    except Exception as e:
        print(f"[votes] real vote failed ({e}), using weighted sim")

    # ── weighted simulation fallback ───────────────────────────────────────
    thesis_bias = {
        "momentum":    0.65,
        "dip_buy":     0.60,
        "breakout":    0.70,
        "whale_follow":0.58,
        "ai":          0.62,
    }

    votes = []
    for a in agents:
        bias    = thesis_bias.get(a.get("thesis", "ai"), 0.60)
        rnd     = random.random()
        decision = "buy" if rnd < bias else ("hold" if rnd < bias + 0.25 else "sell")
        conf    = random.randint(52, 94)
        votes.append({
            "agent":      a.get("name", "agent"),
            "provider":   a.get("provider", "sim"),
            "decision":   decision,
            "confidence": conf,
            "weight":     a.get("weight", 1),
            "reasoning":  f"{decision.title()} signal — {conf}% confidence based on {a.get('thesis','ai')} thesis.",
        })

    total_w  = sum(v["weight"] for v in votes)
    buy_w    = sum(v["weight"] for v in votes if v["decision"] == "buy")
    buy_pct  = round(buy_w / max(total_w, 1) * 100)
    threshold = agents[0].get("threshold", 60) if agents else 60
    decision  = "BUY" if buy_pct >= threshold else "HOLD"

    return {
        "votes":     votes,
        "buy_pct":   buy_pct,
        "decision":  decision,
        "simulated": True,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WALLET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/wallet/{address}")
async def wallet_balance(address: str):
    import httpx
    helius_key = os.getenv("HELIUS_API_KEY", "")
    rpc = f"https://mainnet.helius-rpc.com/?api-key={helius_key}" if helius_key \
          else "https://api.mainnet-beta.solana.com"
    try:
        r = httpx.post(
            rpc,
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
            timeout=10,
        )
        bal = r.json()["result"]["value"] / 1e9
    except:
        bal = 0.0
    return {"address": address, "sol": round(bal, 6)}

@app.post("/wallet/create")
def wallet_create(_auth: bool = Depends(require_auth)):
    try:
        from solders.keypair import Keypair
        from base58 import b58encode
        kp = Keypair()
        return {
            "address":         str(kp.pubkey()),
            "private_key_b58": b58encode(bytes(kp)).decode(),
            "warning":         "Save your private key NOW — it is never shown again.",
        }
    except ImportError:
        raise HTTPException(503, "Run: pip install solders base58")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TRADE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SwapRequest(BaseModel):
    user_id:    str   = "dashboard"
    from_token: str   = "SOL"
    to_token:   str
    amount_sol: float

@app.post("/trade/swap")
async def trade_swap(req: SwapRequest, _auth: bool = Depends(require_auth)):
    try:
        from trading import jupiter_swap
        return await jupiter_swap(req.user_id, req.from_token, req.to_token, req.amount_sol)
    except ImportError:
        return {"ok": False, "error": "trading.py not available — is it in ~/BR0THER-H00D/?"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/trade/history")
def trade_history(user_id: str = "dashboard", limit: int = 20):
    try:
        import sqlite3, json
        brain_db = sqlite3.connect(str(BOT_DIR / "core" / "brain.db"))
        _live2 = os.getenv('TRADE_MODE','paper').lower() == 'live'
        _key2  = 'trader_live' if _live2 else 'trader_paper'
        row = brain_db.execute("SELECT data FROM state WHERE agent=?", (_key2,)).fetchone()
        brain_db.close()
        if not row:
            return {"history": []}
        data = json.loads(row[0])
        history = data.get("history", [])[-limit:][::-1]
        return {"history": [
            {
                "symbol": t.get("name", "?"),
                "action": "SELL",
                "amount": round(t.get("size_usd", 0), 2),
                "price":  round(t.get("exit", 0), 8),
                "pnl":    round(t.get("pnl_usd", 0), 4),
                "reason": t.get("reason", ""),
                "ts":     t.get("ts", "")
            }
            for t in history
        ]}
    except Exception as e:
        return {"history": [], "note": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TOKEN LOOKUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/token/{query}")
def token_lookup(query: str):
    import httpx, urllib.parse
    try:
        r = httpx.get(
            f"https://api.dexscreener.com/latest/dex/search/?q={urllib.parse.quote(query)}",
            timeout=10,
        )
        pairs = [p for p in r.json().get("pairs", []) if p.get("chainId") == "solana"]
        if not pairs:
            return {"ok": False, "error": "not found on Solana"}
        best = sorted(
            pairs,
            key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0),
            reverse=True,
        )[0]
        return {
            "ok":     True,
            "mint":   best["baseToken"]["address"],
            "symbol": best["baseToken"]["symbol"],
            "name":   best["baseToken"]["name"],
            "price":  float(best.get("priceUsd") or 0),
            "mcap":   float(best.get("fdv") or 0),
            "liq":    float(best.get("liquidity", {}).get("usd") or 0),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MARKET
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/market/{mtype}")
def market_data(mtype: str):
    import httpx
    try:
        if mtype == "sol":
            r = httpx.get(
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=solana,bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true",
                timeout=10,
            )
            d = r.json()
            return {"text": (
                f"SOL  ${d['solana']['usd']:.2f}  ({d['solana']['usd_24h_change']:+.1f}%)\n"
                f"BTC  ${d['bitcoin']['usd']:,.0f}  ({d['bitcoin']['usd_24h_change']:+.1f}%)\n"
                f"ETH  ${d['ethereum']['usd']:,.0f}  ({d['ethereum']['usd_24h_change']:+.1f}%)"
            )}

        elif mtype == "trending":
            r = httpx.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
            coins = r.json().get("coins", [])[:8]
            lines = ["# coingecko trending\n"]
            for i, c in enumerate(coins, 1):
                item = c["item"]
                lines.append(f"{i:2}.  {item['symbol']:<10} {item['name']}")
            return {"text": "\n".join(lines)}

        elif mtype == "pump":
            try:
                from market_data import get_pumpfun_new
                coins = get_pumpfun_new(10)
                lines = ["# pump.fun — latest\n"]
                for c in coins[:8]:
                    lines.append(
                        f"{'👑' if c.get('king_of_hill') else '•'} "
                        f"{c['symbol']:<10} ${c['mcap']:>10,.0f}"
                    )
                return {"text": "\n".join(lines)}
            except:
                return {"text": "market_data.py not available"}

        elif mtype == "grad":
            try:
                from market_data import get_pumpfun_graduating
                coins = get_pumpfun_graduating()
                lines = ["# near graduation → raydium\n"]
                for c in coins:
                    lines.append(
                        f"🚀 {c['symbol']:<10} {c['pct_to_grad']:.1f}% away  ${c['mcap']:,.0f}"
                    )
                return {"text": "\n".join(lines)}
            except:
                return {"text": "market_data.py not available"}

        else:
            return {"text": f"unknown type: {mtype}"}

    except Exception as e:
        return {"text": f"error: {e}"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  AGENTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class NewAgent(BaseModel):
    id:        str
    name:      str
    provider:  str  = "custom"
    model:     str
    thesis:    str  = "ai"
    size:      float = 0.05
    weight:    int  = 1
    threshold: int  = 60
    active:    bool = True

@app.get("/agents")
def get_agents():
    if not PERSONAS_OK:
        return {"agents": [], "config": {}}
    agents = []
    for key, persona in PERSONAS.items():
        if key == "orchestrator":
            continue
        agents.append({
            "id":     key,
            "name":   persona.get("name", key),
            "model":  persona.get("model", ""),
            "role":   persona.get("role", ""),
            "weight": COUNCIL_CONFIG.get("weights", {}).get(key, 1),
            "active": True,
        })
    return {"agents": agents, "config": COUNCIL_CONFIG}

@app.post("/agents")
def add_agent(body: NewAgent):
    if PERSONAS_OK:
        PERSONAS[body.id] = {
            "model":    body.model,
            "name":     body.name,
            "role":     body.thesis,
            "provider": body.provider,
            "system":   f"You are {body.name}, a trading council agent. Thesis: {body.thesis}. Be concise.",
        }
        COUNCIL_CONFIG.setdefault("weights", {})[body.id] = body.weight
    return {"ok": True, "agent": body.id}

@app.delete("/agents/{agent_id}")
def remove_agent(agent_id: str):
    if PERSONAS_OK:
        PERSONAS.pop(agent_id, None)
        COUNCIL_CONFIG.get("weights", {}).pop(agent_id, None)
    return {"ok": True}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  API KEYS  —  dashboard sends flat dict of ALL keys at once
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRACKED_KEYS = {
    # AI providers (dashboard key tab)
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    # "GROK_API_KEY",  # removed — typo, xAI key is XAI_API_KEY
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "CEREBRAS_API_KEY",
    # infra
    "HELIUS_API_KEY",
    "BIRDEYE_API_KEY",
    "SOLTRACKER_API_KEY",
    "TELEGRAM_TOKEN",
    # wallet (stored in .env only, never logged)
    "WALLET_PRIVATE_KEY_B58",
}

def get_all_keys():
    """Returns TRACKED_KEYS plus any custom keys saved in .env"""
    custom = set()
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key = line.split("=")[0].strip()
                    if key not in TRACKED_KEYS:
                        custom.add(key)
    except:
        pass
    return TRACKED_KEYS | custom

@app.get("/keys")
def get_keys():
    result = {}
    for k in sorted(TRACKED_KEYS):
        val = os.getenv(k, "")
        result[k] = {"set": bool(val), "preview": (val[:4] + "****") if val else ""}
    return result

@app.post("/keys")
def save_keys(body: dict, _auth: bool = Depends(require_auth)):
    """Accept flat dict  {KEY_NAME: value, ...}  — matches what dashboard sends."""
    updated = []
    for k, v in body.items():
        if not v:
            continue
        write_env_key(k, v)
        os.environ[k] = v
        updated.append(k)
    load_dotenv(ENV_PATH, override=True)
    return {"ok": True, "updated": updated}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ENV UPDATE  (legacy endpoint — dashboard tries /keys first, then this)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/env/update")
def env_update(body: dict, _auth: bool = Depends(require_auth)):
    """Same as POST /keys — kept for backward compat."""
    updated = []
    for k, v in body.items():
        if not v:
            continue
        write_env_key(k, v)
        os.environ[k] = v
        updated.append(k)
    load_dotenv(ENV_PATH, override=True)
    return {"ok": True, "updated": updated}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WHALE SCAN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/whale/scan")
def whale_scan():
    try:
        from trading import scan_whale_activity
        activity = scan_whale_activity()
        lines = ["# whale activity\n"]
        for w in activity:
            lines.append(
                f"{w['wallet'][:8]}…  "
                f"{w['sol_balance']:.2f} SOL  "
                f"{w['recent_txns']} recent txns"
            )
        return {"text": "\n".join(lines)}
    except Exception as e:
        return {"text": f"whale scanner unavailable: {e}"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ROBOT CONTROL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RobotRequest(BaseModel):
    user_id:  str = "dashboard"
    robot_id: str

@app.post("/robot/activate")
def robot_activate(req: RobotRequest, _auth: bool = Depends(require_auth)):
    try:
        from trading import activate_robot
        ok = activate_robot(req.user_id, req.robot_id)
        return {"ok": ok, "robot": req.robot_id, "action": "activated"}
    except ImportError:
        return {"ok": False, "error": "trading.py not available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/agents/custom")
def get_custom_agents():
    try:
        import sqlite3
        db = sqlite3.connect(str(BOT_DIR / "core" / "brain.db"))
        rows = db.execute("SELECT id, name, task, enabled, created_at FROM custom_agents ORDER BY id").fetchall()
        db.close()
        return {"agents": [{"id": r[0], "name": r[1], "task": r[2], "enabled": bool(r[3]), "created_at": r[4]} for r in rows]}
    except Exception as e:
        return {"agents": [], "error": str(e)}

@app.post("/agents/custom")
def save_custom_agent(body: dict):
    try:
        import sqlite3
        from datetime import datetime
        name = body.get("name", "").strip()
        task = body.get("task", "").strip()
        if not name or not task:
            raise HTTPException(status_code=400, detail="name and task required")
        db = sqlite3.connect(str(BOT_DIR / "core" / "brain.db"))
        db.execute("""
            INSERT INTO custom_agents (name, task, enabled, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(name) DO UPDATE SET task=excluded.task, updated_at=excluded.updated_at
        """, (name, task, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
        db.commit()
        db.close()
        return {"ok": True, "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/agents/custom/code")
def save_custom_agent_code(body: dict, _auth: bool = Depends(require_auth)):
    """Save custom Python agent code to agents/trading/custom_<name>.py"""
    import re as _re
    name = body.get("name", "").strip().replace(" ", "_").lower()
    name = _re.sub(r"[^a-z0-9_]", "", name)   # no path traversal / odd chars
    code = body.get("code", "").strip()
    if not name or not code:
        raise HTTPException(status_code=400, detail="name and code required")
    # Safety check — block the obvious shell/exec/file/network escapes. This is a
    # best-effort guard for an AUTHENTICATED single user; it is not a real sandbox.
    blocked = ["os.system", "subprocess", "shutil.rmtree", "__import__", "eval(",
               "exec(", "compile(", "importlib", "pty.", "socket.", "globals(",
               "popen", "os.remove", "os.unlink", "open("]
    low = code.lower()
    for b in blocked:
        if b in low:
            raise HTTPException(status_code=400, detail=f"blocked pattern: {b}")
    path = f"agents/trading/custom_{name}.py"
    try:
        with open(path, "w") as f:
            f.write(f"# Custom agent: {name}\n")
            f.write(f"# Added via dashboard\n\n")
            f.write(code)
        return {"ok": True, "path": path, "msg": f"saved — restart bot to activate"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/agents/custom/code/{name}")
def delete_custom_agent_code(name: str, _auth: bool = Depends(require_auth)):
    """Delete a custom agent file"""
    path = f"agents/trading/custom_{name}.py"
    try:
        if os.path.exists(path):
            os.remove(path)
            return {"ok": True, "msg": f"deleted {path}"}
        return {"ok": False, "msg": "file not found"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/agents/custom/code")
def list_custom_agent_code(_auth: bool = Depends(require_auth)):
    """List all custom agent files"""
    import glob
    files = glob.glob("agents/trading/custom_*.py")
    agents = []
    for f in files:
        name = os.path.basename(f).replace("custom_", "").replace(".py", "")
        with open(f) as fp:
            content = fp.read()
        agents.append({"name": name, "path": f, "code": content})
    return {"agents": agents}

@app.delete("/agents/custom/{name}")
def delete_custom_agent(name: str, _auth: bool = Depends(require_auth)):
    try:
        import sqlite3
        db = sqlite3.connect(str(BOT_DIR / "core" / "brain.db"))
        db.execute("DELETE FROM custom_agents WHERE name=?", (name,))
        db.commit()
        db.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/robot/deactivate")
def robot_deactivate(req: RobotRequest, _auth: bool = Depends(require_auth)):
    try:
        from trading import deactivate_robot
        deactivate_robot(req.user_id, req.robot_id)
        return {"ok": True, "robot": req.robot_id, "action": "deactivated"}
    except ImportError:
        return {"ok": False, "error": "trading.py not available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  BOT CONTROL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/bot/start")
def start_bot(_auth: bool = Depends(require_auth)):
    global _bot_process
    if bot_running():
        return {"ok": False, "msg": "already running"}
    start_path = BOT_DIR / "Start.py"
    if not start_path.exists():
        return {"ok": False, "msg": "Start.py not found"}
    _bot_process = subprocess.Popen(
        [sys.executable, str(start_path)],
        cwd=str(BOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "pid": _bot_process.pid}

@app.post("/bot/stop")
def stop_bot(_auth: bool = Depends(require_auth)):
    global _bot_process
    if _bot_process and _bot_process.poll() is None:
        _bot_process.terminate()
        _bot_process = None
        return {"ok": True, "msg": "bot stopped"}
    return {"ok": False, "msg": "bot not running via API"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PORTFOLIO / TRADES  (extra endpoints used by bot internally)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/portfolio")
def get_portfolio_data():
    try:
        cash = get_portfolio() if PAPER_OK else 1000.0
    except:
        cash = 1000.0
    positions, realized_pnl, wins, losses = [], 0.0, 0, 0
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT token, entry_price, size_usd, pnl_pct FROM positions WHERE status='OPEN'"
            ).fetchall()
            for r in rows:
                positions.append({
                    "token": r[0], "entry_price": r[1],
                    "size_usd": r[2], "pnl_pct": r[3],
                })
            closed = conn.execute(
                "SELECT SUM(pnl_usd), COUNT(*) FROM positions WHERE status='CLOSED'"
            ).fetchone()
            realized_pnl = round(closed[0] or 0, 2)
            wins   = conn.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED' AND pnl_usd > 0").fetchone()[0]
            losses = conn.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED' AND pnl_usd <= 0").fetchone()[0]
    except:
        pass
    total = wins + losses
    return {
        "cash": round(cash, 2),
        "realized_pnl": realized_pnl,
        "win_rate": round(wins / max(total, 1) * 100, 1),
        "wins": wins, "losses": losses,
        "positions": positions,
    }

@app.get("/trades")
def get_trades(limit: int = 20):
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT token, action, price, size_usd, pnl_usd, reason, timestamp "
                "FROM trade_log ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [
            {"token": r[0], "action": r[1], "price": r[2],
             "size": r[3], "pnl": r[4], "reason": r[5], "ts": r[6]}
            for r in rows
        ]
    except:
        return []

@app.get("/scans")
def get_scan_log(limit: int = 10):
    try:
        with db() as conn:
            rows = conn.execute(
                "SELECT tokens_scanned, tokens_approved, top_token, timestamp "
                "FROM scan_log ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"scanned": r[0], "approved": r[1], "top": r[2], "ts": r[3]} for r in rows]
    except:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATS  —  full trade history, thesis, council reasoning, PnL from brain.db
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_brain_trades():
    """Parse trade memories in core/brain.db into structured closed-trade records."""
    import sqlite3 as _sq, re as _re
    db = str(BOT_DIR / "core" / "brain.db")
    out = {"closed": [], "open_buys": [], "votes": [], "rejected": [], "learnings": []}
    try:
        c = _sq.connect(db)
        c.row_factory = _sq.Row
        rows = c.execute(
            "SELECT ts, content FROM memories WHERE type='trade' ORDER BY id ASC"
        ).fetchall()

        def _num(pat, text, cast=float, default=0):
            m = _re.search(pat, text)
            try:
                return cast(m.group(1)) if m else default
            except Exception:
                return default

        buys = {}
        for r in rows:
            content, ts = r["content"], r["ts"]
            try:
                if " BUY " in content and "SELLALL" not in content:
                    mode  = "LIVE" if content.startswith("LIVE") else "PAPER"
                    name  = content.split("BUY", 1)[1].split("@")[0].strip()
                    price = _num(r"@ \$?([0-9.]+)", content)
                    size  = _num(r"size=\$?([0-9.]+)", content)
                    score = _num(r"score=([0-9]+)", content, int, 0)
                    conf  = _num(r"conf=([0-9]+)", content, int, 0)
                    mm    = _re.search(r"mint=([1-9A-HJ-NP-Za-km-z]{32,44})", content)
                    mint  = mm.group(1) if mm else ""
                    # thesis = trailing free-text segments
                    th = [p.strip() for p in content.split("|")
                          if p.strip() and not any(k in p for k in
                          ("BUY","size=","TP=","SL=","score=","conf=","mint=","mcap="))]
                    thesis = ", ".join(th[:2])
                    buys[name] = {"ts": ts, "price": price, "size": round(size,2), "score": score,
                                  "conf": conf, "mint": mint, "thesis": thesis, "mode": mode}

                elif " SELL " in content and "SELLALL" not in content:
                    mode    = "LIVE" if content.startswith("LIVE") else "PAPER"
                    name    = content.split("SELL", 1)[1].split("@")[0].strip()
                    price   = _num(r"@ \$?([0-9.]+)", content)
                    pnl_usd = _num(r"PnL=\$?([+-]?[0-9.]+)", content)
                    pm      = _re.search(r"\(([+-]?[0-9.]+)%\)", content)
                    pnl_pct = float(pm.group(1)) if pm else 0.0
                    rm      = _re.search(r"reason=(.+)$", content)
                    reason  = rm.group(1).strip() if rm else ""
                    b       = buys.get(name, {})
                    out["closed"].append({
                        "name": name, "mode": mode,
                        "buy_ts": b.get("ts", ""), "sell_ts": ts,
                        "entry": b.get("price", 0), "exit": price,
                        "size": b.get("size", 0),
                        "pnl_usd": round(pnl_usd, 2), "pnl_pct": round(pnl_pct, 1),
                        "score": b.get("score", 0), "conf": b.get("conf", 0),
                        "thesis": b.get("thesis", ""), "mint": b.get("mint", ""),
                        "reason": reason,
                    })
                    buys.pop(name, None)
            except Exception:
                continue

        out["open_buys"] = [{"name": k, **v} for k, v in buys.items()]

        for r in c.execute("SELECT ts, content FROM memories WHERE type='council_vote' ORDER BY id DESC LIMIT 40").fetchall():
            out["votes"].append({"ts": r["ts"], "content": r["content"]})
        for r in c.execute("SELECT ts, content FROM memories WHERE type='rejected' ORDER BY id DESC LIMIT 20").fetchall():
            out["rejected"].append({"ts": r["ts"], "content": r["content"]})
        for r in c.execute("SELECT ts, agent, topic, insight FROM learnings ORDER BY id DESC LIMIT 30").fetchall():
            out["learnings"].append({"ts": r["ts"], "agent": r["agent"], "topic": r["topic"], "insight": r["insight"]})
        c.close()
    except Exception as e:
        out["error"] = str(e)
    return out


def _read_trader_state():
    """Read live trader state (balance, open positions, pnl) for both modes."""
    import sqlite3 as _sq, json as _json
    db = str(BOT_DIR / "core" / "brain.db")
    out = {"paper": None, "live": None}
    try:
        c = _sq.connect(db); c.row_factory = _sq.Row
        for mode, key in (("paper", "trader_paper"), ("live", "trader_live")):
            row = c.execute("SELECT data FROM state WHERE agent=?", (key,)).fetchone()
            if not row:
                continue
            d = _json.loads(row["data"])
            positions = d.get("positions", {})
            open_list = []
            for mint, p in positions.items():
                open_list.append({
                    "name": p.get("name", mint[:8]),
                    "mint": mint,
                    "entry": p.get("entry", 0),
                    "size_usd": round(p.get("size_usd", 0), 2),
                    "tier1_hit": p.get("tier1_hit", False),
                    "tier2_hit": p.get("tier2_hit", False),
                    "peak_pct": round(p.get("peak_pct", 0), 1) if "peak_pct" in p else None,
                    "score": p.get("score", 0),
                })
            out[mode] = {
                "balance":     round(d.get("balance", 0), 2),
                "total_pnl":   round(d.get("total_pnl", 0), 2),
                "trades":      d.get("trades", 0),
                "open_count":  len(positions),
                "open":        open_list,
                "day_start":   round(d.get("day_start_balance", d.get("balance", 0)), 2),
                "updated":     d.get("updated", ""),
            }
        c.close()
    except Exception as e:
        out["error"] = str(e)
    return out


@app.get("/stats")
def get_stats():
    """Full performance breakdown parsed from the shared brain."""
    data   = _parse_brain_trades()
    closed = data["closed"]
    wins   = [t for t in closed if t["pnl_usd"] > 0]
    losses = [t for t in closed if t["pnl_usd"] <= 0]
    n      = len(closed)

    total_pnl = round(sum(t["pnl_usd"] for t in closed), 2)
    win_rate  = round(len(wins) / n * 100) if n else 0
    avg_win   = round(sum(t["pnl_pct"] for t in wins) / len(wins), 1) if wins else 0.0
    avg_loss  = round(sum(t["pnl_pct"] for t in losses) / len(losses), 1) if losses else 0.0
    best      = max(closed, key=lambda t: t["pnl_pct"]) if closed else None
    worst     = min(closed, key=lambda t: t["pnl_pct"]) if closed else None
    live_n    = len([t for t in closed if t["mode"] == "LIVE"])
    paper_n   = n - live_n

    # profit factor = gross win / gross loss
    gross_win  = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss else (gross_win if gross_win else 0)

    live_state = _read_trader_state()
    return {
        "live_state": live_state,
        "summary": {
            "total_trades": n,
            "live_trades":  live_n,
            "paper_trades": paper_n,
            "win_rate":     win_rate,
            "wins":         len(wins),
            "losses":       len(losses),
            "total_pnl":    total_pnl,
            "avg_win_pct":  avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": pf,
            "best":  {"name": best["name"],  "pnl_pct": best["pnl_pct"]}  if best  else None,
            "worst": {"name": worst["name"], "pnl_pct": worst["pnl_pct"]} if worst else None,
        },
        "trades":    list(reversed(closed)),   # newest first
        "open":      data["open_buys"],
        "votes":     data["votes"],
        "rejected":  data["rejected"],
        "learnings": data["learnings"],
    }



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TOOLS  —  log tailing, file browser, safe file editor  (dashboard)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Files the editor is allowed to touch. Anything outside this is rejected,
# so the dashboard can't be used to read /etc/passwd or write outside the repo.
# .env removed — secrets must never be readable/writable through the API.
_EDIT_WHITELIST_EXT = {".py", ".json", ".txt", ".md", ".html", ".sh", ".cfg", ".ini", ".toml", ".yaml", ".yml"}
_EDIT_BLOCKED_NAMES = {"brain.db", "brotha.db", ".env", ".env.example", "id.json", "keypair.json"}

def _safe_repo_path(rel: str):
    """Resolve a path and confirm it stays inside BOT_DIR. Returns Path or None."""
    from pathlib import Path
    try:
        p = (BOT_DIR / rel).resolve()
        if BOT_DIR.resolve() not in p.parents and p != BOT_DIR.resolve():
            return None
        return p
    except Exception:
        return None


@app.get("/logs")
def get_logs(file: str = "bot.log", lines: int = 200, _auth: bool = Depends(require_auth)):
    """Tail the last N lines of a log file in the repo."""
    p = _safe_repo_path(file)
    if not p or not p.exists():
        return {"ok": False, "lines": [], "msg": f"{file} not found"}
    try:
        with open(p, "r", errors="replace") as f:
            data = f.readlines()
        tail = data[-max(1, min(lines, 2000)):]
        return {"ok": True, "file": file, "lines": [l.rstrip("\n") for l in tail], "total": len(data)}
    except Exception as e:
        return {"ok": False, "lines": [], "msg": str(e)}


@app.get("/logs/list")
def list_logs(_auth: bool = Depends(require_auth)):
    """List all .log files in the repo with sizes."""
    import os
    out = []
    try:
        for f in sorted(BOT_DIR.glob("*.log")):
            out.append({"name": f.name, "size": f.stat().st_size})
    except Exception:
        pass
    return {"ok": True, "logs": out}


@app.get("/files")
def list_files(dir: str = ".", _auth: bool = Depends(require_auth)):
    """Browse the repo directory tree (one level)."""
    p = _safe_repo_path(dir)
    if not p or not p.is_dir():
        return {"ok": False, "items": [], "msg": "not a directory"}
    items = []
    try:
        for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.name.startswith(".git") or entry.name == "__pycache__" or entry.name == "node_modules":
                continue
            rel = str(entry.relative_to(BOT_DIR.resolve())) if entry.resolve() != BOT_DIR.resolve() else entry.name
            items.append({
                "name": entry.name,
                "path": rel,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
                "editable": (entry.is_file()
                             and entry.suffix in _EDIT_WHITELIST_EXT
                             and entry.name not in _EDIT_BLOCKED_NAMES),
            })
    except Exception as e:
        return {"ok": False, "items": [], "msg": str(e)}
    parent = str((p / "..").resolve().relative_to(BOT_DIR.resolve())) if p.resolve() != BOT_DIR.resolve() else None
    return {"ok": True, "dir": dir, "parent": parent, "items": items}


@app.get("/file")
def read_file(path: str, _auth: bool = Depends(require_auth)):
    """Read a text file for editing. Whitelisted extensions only."""
    p = _safe_repo_path(path)
    if not p or not p.is_file():
        return {"ok": False, "content": "", "msg": "not found"}
    if p.suffix not in _EDIT_WHITELIST_EXT or p.name in _EDIT_BLOCKED_NAMES:
        return {"ok": False, "content": "", "msg": "file type not editable"}
    if p.stat().st_size > 1_000_000:
        return {"ok": False, "content": "", "msg": "file too large (>1MB)"}
    try:
        return {"ok": True, "path": path, "content": open(p, "r", errors="replace").read()}
    except Exception as e:
        return {"ok": False, "content": "", "msg": str(e)}


@app.post("/file")
def write_file(body: dict, _auth: bool = Depends(require_auth)):
    """Save edits back to a whitelisted file. Makes a .bak first."""
    import shutil
    path = body.get("path", "")
    content = body.get("content", "")
    p = _safe_repo_path(path)
    if not p:
        return {"ok": False, "msg": "invalid path"}
    if p.suffix not in _EDIT_WHITELIST_EXT or p.name in _EDIT_BLOCKED_NAMES:
        return {"ok": False, "msg": "file type not editable"}
    # python syntax check before saving .py files — refuse to save broken code
    if p.suffix == ".py":
        import ast
        try:
            ast.parse(content)
        except SyntaxError as e:
            return {"ok": False, "msg": f"syntax error line {e.lineno}: {e.msg} — not saved"}
    try:
        if p.exists():
            shutil.copy2(p, str(p) + ".bak")
        with open(p, "w") as f:
            f.write(content)
        return {"ok": True, "path": path, "bytes": len(content.encode())}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ── Helius Webhook ─────────────────────────────────────────────────────────────
@app.post("/webhook/helius")
async def helius_webhook(payload: dict):
    try:
        for txn in payload if isinstance(payload, list) else [payload]:
            txn_type = txn.get("type", "UNKNOWN")
            source   = txn.get("source", "?")
            sig      = txn.get("signature", "")[:12]
            accs     = txn.get("accountData", [])
            wallet   = accs[0].get("account", "?") if accs else "?"
            msg = f"{wallet[:6]}.. | {txn_type} via {source} | {sig}.."
            _wh_db_path = str(BOT_DIR / "core" / "brain.db")
            brain_db = sqlite3.connect(_wh_db_path)
            brain_db.execute(
                "INSERT INTO memories (ts, agent, content, type, tags) VALUES (?,?,?,?,?)",
                (__import__('datetime').datetime.now().isoformat(), "helius_webhook", msg, "whale_alert", "helius,webhook")
            )
            brain_db.commit()
            brain_db.close()
            print(f"  [Helius webhook] {msg}")
        return {"ok": True}
    except Exception as e:
        print(f"  [Helius webhook] error: {e}")
        return {"ok": False, "error": str(e)}

# ── $H00D Token Gate ───────────────────────────────────────────────────────────
from hood_gate import router as gate_router
app.include_router(gate_router)

# ── Serve terminal website ─────────────────────────────────────────────────────
@app.get("/terminal")
def terminal_ui():
    return FileResponse(str(BOT_DIR / "hood_web.html"))

# ── Chat endpoint ──────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    wallet: str = ""

@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        from ai_engine import ask
        reply = await ask(req.message)
        return {"reply": reply}
    except Exception as e:
        return {"reply": f"agent unavailable: {e}"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  XTERM WEBSOCKET TERMINAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import asyncio
import pty
import fcntl
import termios
import struct
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    # An interactive shell is too dangerous to expose on a public host: disabled
    # entirely when DASHBOARD_PUBLIC=1. Locally it's gated by the token below.
    if _PUBLIC:
        await websocket.close(code=1008)
        return
    # Auth gate: token passed as ?token=... query param. Reject before opening any shell.
    token = websocket.query_params.get("token", "")
    if not _token_ok(token):
        await websocket.close(code=1008)  # policy violation
        return
    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(BOT_DIR / "Start.py"),
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        cwd=str(BOT_DIR),
        env={**os.environ, "TERM": "xterm-256color", "COLUMNS": "120", "LINES": "40"},
    )
    os.close(slave_fd)

    async def read_output():
        loop = asyncio.get_event_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    asyncio.create_task(read_output())

    try:
        while True:
            msg = await websocket.receive()
            if "bytes" in msg:
                os.write(master_fd, msg["bytes"])
            elif "text" in msg:
                data = msg["text"]
                if data.startswith("resize:"):
                    _, cols, rows = data.split(":")
                    winsize = struct.pack("HHHH", int(rows), int(cols), 0, 0)
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                else:
                    os.write(master_fd, data.encode())
    except WebSocketDisconnect:
        pass
    finally:
        try:
            proc.kill()
            os.close(master_fd)
        except:
            pass

@app.get("/xterm")
def xterm_ui():
    return FileResponse(str(BOT_DIR / "terminal.html"))

"""
Start.py — BR0THERH00D Unified Entry Point

Merges:
  - Start.py  : launcher UI, mode menu, kill_orphans, color system
  - loop.py   : fast/full intelligence loop, social scanner, watchlist, council debate
  - trader.py : sophisticated execution engine (tiered exits, trailing stop,
                choppiness detection, profit lock, blacklist, brain feedback)

Modes:
  1  Solo Paper  — loop intelligence → Trader (paper, no council debate)
  2  Paper + Agents — loop intelligence → council debate → Trader (paper)
  3  Live Trading — loop intelligence → council debate → Trader (LIVE, wallet confirm)
  4  Dashboard   — launches brotha_api + uvicorn (unchanged)
  5  Assistant   — launches agents/assistant_launcher (unchanged)
"""

import asyncio, os, sqlite3, logging, time, requests, re, signal, subprocess, sys
from datetime import datetime
from xml.etree import ElementTree as ET
from dotenv import load_dotenv

# ── env ────────────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"), override=True)

os.makedirs("logs", exist_ok=True)
os.makedirs("data", exist_ok=True)

# ── colors (from Start.py) ─────────────────────────────────────────────────────
CY = "\033[96m"; GR = "\033[92m"; YL = "\033[93m"
RD = "\033[91m"; DM = "\033[2m";  RS = "\033[0m"
BD = "\033[1m";  MG = "\033[95m"

PYTHON = sys.executable

# ── logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/brotha.log"),
        logging.StreamHandler(),
    ],
)
logging.getLogger().handlers[1].setLevel(logging.WARNING)
log = logging.getLogger("start")

# ── kill orphans from previous crash (from Start.py) ──────────────────────────
def kill_orphans():
    try:
        import psutil
        current = os.getpid()
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if proc.pid == current:
                    continue
                cmd = " ".join(proc.info.get("cmdline") or [])
                if any(s in cmd for s in ["agents/trading/", "agents/intel/", "agents/assistant"]):
                    proc.terminate()
            except Exception:
                pass
    except Exception:
        pass

try:
    kill_orphans()
except Exception:
    pass

# ── graceful shutdown ──────────────────────────────────────────────────────────
RUNNING = True
_subprocess_procs = []   # for modes 4/5 that still use subprocesses

def shutdown(sig=None, frame=None):
    global RUNNING
    RUNNING = False
    if _subprocess_procs:
        print(CY + "\n  Shutting down subprocesses..." + RS)
        for p, script in _subprocess_procs:
            try:
                p.terminate(); p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
    print(GR + "  Stopped. See you next run.\n" + RS)
    sys.exit(0)

signal.signal(signal.SIGINT,  shutdown)
try:
    signal.signal(signal.SIGTERM, shutdown)
except (ValueError, AttributeError):
    pass

# ── runtime stats ──────────────────────────────────────────────────────────────
STATS = {
    "started": time.time(), "cycles": 0, "full_scans": 0,
    "social_signals": 0, "debates": 0, "trades": 0,
}

def _uptime():
    s = int(time.time() - STATS["started"])
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h{m:02d}m" if h else f"{m}m{s % 60:02d}s"

# ── CONFIG ─────────────────────────────────────────────────────────────────────
DB_PATH             = os.getenv("AGENT_DB",           "data/agent.db")
FAST_INTERVAL       = int(os.getenv("FAST_INTERVAL",   "60"))
FULL_INTERVAL       = int(os.getenv("FULL_INTERVAL",   "300"))
MIN_AGENTS_TRADE    = int(os.getenv("MIN_AGENTS_TRADE","4"))
MIN_TOKEN_AGE_HOURS = float(os.getenv("MIN_TOKEN_AGE_HOURS", "2.0"))

# Set by mode selection below — read by trader.py via os.getenv
PAPER_TRADE = True          # default; overridden by mode 3
USE_COUNCIL = True          # mode 1 skips council, modes 2/3 use it

# ── imports (deferred so mode menu shows before any import errors) ─────────────
def _import_engine():
    global build_market, get_agent_list, collective_debate
    global filter_market, fetch_token_data, enrich_token
    global open_position, check_positions, print_dashboard, init_paper_db
    global get_json, Trader

    from scanner       import build_market
    from agent_personas import get_agent_list
    from collective    import collective_debate
    from alpha_engine  import filter_market
    from market_data   import fetch_token_data, enrich_token
    from paper_trader  import open_position, check_positions, print_dashboard, init_paper_db
    from core.http     import get_json
    # The sophisticated trader from agents/trading/trader.py
    sys.path.insert(0, os.path.join(ROOT, "agents", "trading"))
    from trader import Trader

# ── menu helpers (from Start.py) ───────────────────────────────────────────────
W = 55

def box(text="", color="", width=W):
    pad = width - len(text)
    return CY + "  ║ " + color + text + RS + " " * pad + CY + "║" + RS

def show_menu():
    os.system("clear")
    print(CY + BD + r"""
██████╗ ██████╗  ██████╗ ████████╗██╗  ██╗███████╗██████╗ ██╗  ██╗ ██████╗  ██████╗ ██████╗
██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝██║  ██║██╔════╝██╔══██╗██║  ██║██╔═══██╗██╔═══██╗██╔══██╗
██████╔╝██████╔╝██║   ██║   ██║   ███████║█████╗  ██████╔╝███████║██║   ██║██║   ██║██║  ██║
██╔══██╗██╔══██╗██║   ██║   ██║   ██╔══██║██╔══╝  ██╔══██╗██╔══██║██║   ██║██║   ██║██║  ██║
██████╔╝██║  ██║╚██████╔╝   ██║   ██║  ██║███████╗██║  ██║██║  ██║╚██████╔╝╚██████╔╝██████╔╝
╚═════╝ ╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═════╝
""" + RS)
    print(CY + "        Solana Alpha Collective  —  Unified Intelligence Loop" + RS)
    print()

    # show brain summary if available
    try:
        from core import brain
        brain.init_db()
        brain.brain_summary()
    except Exception:
        pass
    print()

    print(CY + "  ╔" + "═" * W + "╗")
    print(box())
    print(box("SELECT MODE", BD + CY))
    print(box())
    print(CY + "  ╠" + "═" * W + "╣")
    print(box())
    print(box("[1]  Solo Paper Trade  — alpha engine only, no council", GR))
    print(box("[2]  Paper + Council   — full 8-agent debate (paper)",   CY))
    print(box("[3]  Live Trading      — real funds, full council",       MG))
    print(box("[4]  Dashboard         — browser agent editor + API",    YL))
    print(box("[5]  Assistant Mode    — personal AI assistant",         RD))
    print(box("[0]  Exit",                                              DM))
    print(box())
    print(CY + "  ╚" + "═" * W + "╝" + RS)
    print()

# ══════════════════════════════════════════════════════════════════════════════
#  INTELLIGENCE PIPELINE  (from loop.py)
# ══════════════════════════════════════════════════════════════════════════════

HEADERS     = {"User-Agent": "Mozilla/5.0"}
CA_PATTERN  = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')
SYM_PATTERN = re.compile(r'\$([A-Z]{2,10})\b')
ALPHA_WORDS = [
    "just launched","new token","early","gem","CA:","contract:",
    "stealth launch","fair launch","liquidity added","buying","accumulating"
]
IGNORE_SYMS = {"THE","AND","FOR","SOL","USD","BTC","ETH","NFT","API","SDK","RT"}

RSS_FEEDS = {
    "CoinDesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt":       "https://decrypt.co/feed",
    "TheBlock":      "https://www.theblock.co/rss.xml",
}
TITLE_BLACKLIST = [
    "what happened in crypto today","weekly roundup","market wrap","morning briefing",
]
NEWS_WEIGHT = 7

seen_tweets = set()
watchlist   = {}
debated     = set()

# ── DB ─────────────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            token          TEXT, decision TEXT, confidence REAL,
            agents_voted   INTEGER, price TEXT, volume REAL, score REAL,
            rug_score      REAL, momentum_score REAL, timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tokens_scanned INTEGER, tokens_approved INTEGER,
            top_token TEXT, timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS social_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account TEXT, symbol TEXT, ca TEXT,
            tweet TEXT, score INTEGER, timestamp TEXT
        );
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT, signal_ts TEXT, decision TEXT,
            entry_price TEXT, check_price TEXT, pnl_pct REAL, check_ts TEXT
        );
        """)

def log_social_signal(account, symbol, ca, tweet, score):
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO social_signals VALUES (NULL,?,?,?,?,?,?)",
            (account, symbol, ca, tweet[:300], score, datetime.utcnow().isoformat())
        )

# ── token age ──────────────────────────────────────────────────────────────────
def get_token_age_hours(mint: str) -> float:
    if not mint:
        return 999.0
    data  = get_json(f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
                     headers=HEADERS, timeout=8, default={})
    pairs = (data or {}).get("pairs") or []
    times = [p.get("pairCreatedAt", 0) for p in pairs if p.get("pairCreatedAt")]
    if not times:
        return 999.0
    return round((time.time() - min(times) / 1000) / 3600, 2)

# ── fear & greed ───────────────────────────────────────────────────────────────
_fg_cache = {"value": None, "label": None, "fetched_at": 0}

def get_fear_and_greed():
    if _fg_cache["value"] and time.time() - _fg_cache["fetched_at"] < 600:
        return _fg_cache.copy()
    data = get_json("https://api.alternative.me/fng/?limit=1", timeout=5, default={})
    try:
        d = (data or {}).get("data", [{}])[0]
        _fg_cache.update({"value": int(d["value"]), "label": d["value_classification"],
                          "fetched_at": time.time()})
    except Exception:
        _fg_cache.update({"value": 50, "label": "Neutral", "fetched_at": time.time()})
    return _fg_cache.copy()

# ── RSS social scanner ─────────────────────────────────────────────────────────
def fetch_feed():
    items = []
    for source, url in RSS_FEEDS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            for item in root.findall(".//item"):
                title = item.find("title")
                desc  = item.find("description")
                link  = item.find("link")
                t = title.text if title is not None else ""
                d = desc.text  if desc  is not None else ""
                l = link.text  if link  is not None else ""
                if any(bl in t.lower() for bl in TITLE_BLACKLIST):
                    continue
                items.append({"account": source, "text": (t + " " + d).strip(),
                              "title": t, "link": l})
        except Exception as e:
            print(f"  [RSS] {source} error: {e}")
    return items

def parse_tweet(tweet, weight):
    text    = tweet["text"]
    text_up = text.upper()
    score   = 0
    signals = []

    cas     = [c for c in CA_PATTERN.findall(text) if 32 <= len(c) <= 44]
    symbols = [s for s in SYM_PATTERN.findall(text_up) if s not in IGNORE_SYMS]
    keywords= [kw for kw in ALPHA_WORDS if kw in text.lower()]
    is_rt   = text.startswith("RT by")

    if cas:      score += 40 * weight; signals.append(f"CA: {cas[0][:8]}...")
    if symbols:  score += 20 * weight; signals.append(f"Symbols: {', '.join(['$'+s for s in symbols[:3]])}")
    if keywords: score += 15 * weight; signals.append(f"Keywords: {', '.join(keywords[:2])}")
    if not is_rt: score += 10 * weight

    if score < 30:
        return None

    return {
        "account": tweet["account"], "weight": weight, "score": score,
        "signals": signals, "cas": cas, "symbols": symbols,
        "text": tweet["title"][:200], "link": tweet["link"], "is_rt": is_rt,
    }

def run_social_scan():
    priority = []
    for tweet in fetch_feed():
        tid = tweet.get("link", "")
        if not tid or tid in seen_tweets:
            continue
        seen_tweets.add(tid)
        source = tweet.get("account", "news")
        sig = parse_tweet(tweet, NEWS_WEIGHT)
        if not sig:
            continue

        print(f"  [SOCIAL] {source} | {' | '.join(sig['signals'])}")
        print(f"           {sig['text'][:120]}")

        sym = sig["symbols"][0] if sig["symbols"] else ""
        ca  = sig["cas"][0]     if sig["cas"]     else ""
        log_social_signal(source, sym, ca, sig["text"], sig["score"])

        if ca:
            print(f"  [SOCIAL] ⚡ CA DETECTED: {ca}")
            priority.append({"token": sym or ca[:8], "mint": ca, "source": source,
                             "score": sig["score"], "weight": NEWS_WEIGHT, "social": sig})
        elif sym:
            priority.append({"token": sym, "mint": "", "source": source,
                             "score": sig["score"], "weight": NEWS_WEIGHT, "social": sig})

    if len(seen_tweets) > 3000:
        seen_tweets.clear()

    return sorted(priority, key=lambda x: x["score"], reverse=True)

# ── watchlist ──────────────────────────────────────────────────────────────────
def update_watchlist(tokens):
    for t in tokens:
        sym = t["token"]
        if sym not in watchlist:
            watchlist[sym] = {
                "price":      t.get("price", 0),
                "mint":       t.get("mint", ""),
                "first_seen": datetime.utcnow().isoformat(),
                "score":      t.get("score", 0),
                "rug_score":  t.get("rug_score", 0),
            }

def check_watchlist():
    alerts = []
    for sym, data in list(watchlist.items()):
        try:
            seen = datetime.fromisoformat(data.get("first_seen", ""))
            if (datetime.utcnow() - seen).total_seconds() > 6 * 3600:
                del watchlist[sym]; continue
        except Exception:
            pass
        try:
            mint = data.get("mint", "")
            live = enrich_token(sym, mint) if mint else fetch_token_data(sym)
            if live.get("error"):
                continue
            new_price = float(live.get("price") or 0)
            old_price = float(data.get("price") or 0)
            if old_price <= 0 or new_price <= 0:
                continue
            change_pct = ((new_price - old_price) / old_price) * 100
            watchlist[sym]["price"] = new_price
            if abs(change_pct) >= 15:
                alerts.append({"token": sym, "change_pct": change_pct,
                               "new_price": new_price, "live_data": live})
                direction = "🚀" if change_pct > 0 else "📉"
                print(f"  [WATCH] {direction} {sym} moved {change_pct:+.1f}% since first seen")
        except Exception:
            continue
    return alerts

# ── debate prompt builder ──────────────────────────────────────────────────────
def build_prompt(signal):
    token   = signal["token"]
    md      = signal.get("market_data", signal)
    thesis  = signal.get("thesis", {})
    stats   = thesis.get("key_stats", {})
    bull    = thesis.get("bull_case", [])
    bear    = thesis.get("bear_case", [])
    summary = thesis.get("summary", "")
    signals = signal.get("signals", [])
    plan    = thesis.get("trade_plan", "")
    social  = signal.get("social", {})

    security      = md.get("security", {})
    concentration = md.get("concentration", {})
    soltracker    = md.get("soltracker", {})

    social_block = ""
    if social:
        social_block = (f"\nSOCIAL ALPHA:\n"
                        f"  Source: @{social.get('account','')} (weight={social.get('weight',0)}/10)\n"
                        f"  Tweet: {social.get('text','')[:150]}\n"
                        f"  Signals: {', '.join(social.get('signals',[]))}\n")

    security_block = ""
    if security:
        security_block = (f"\nON-CHAIN SECURITY (Birdeye):\n"
                          f"  Mint Authority Disabled: {security.get('mint_authority_disabled','?')}\n"
                          f"  Freeze Authority Disabled: {security.get('freeze_authority_disabled','?')}\n"
                          f"  Top 10 Holders: {security.get('top10_holder_pct','?')}%\n"
                          f"  LP Locked: {security.get('lp_locked_pct','?')}%\n")

    concentration_block = ""
    if concentration:
        concentration_block = (f"\nHOLDER CONCENTRATION:\n"
                               f"  Top 10: {concentration.get('top10_pct','?')}%\n"
                               f"  Top 1:  {concentration.get('top1_pct','?')}%\n"
                               f"  Risk: {concentration.get('concentration_risk','?')}\n")

    soltracker_block = ""
    if soltracker:
        risks = soltracker.get("risks", [])
        risk_str = ", ".join([r.get("name","") if isinstance(r,dict) else str(r)
                              for r in risks[:3]]) or "none"
        soltracker_block = (f"\nSOLANA TRACKER:\n"
                            f"  Holders: {soltracker.get('holder_count','?')}\n"
                            f"  LP Burned: {soltracker.get('lp_burned','?')}%\n"
                            f"  Risk Flags: {risk_str}\n")

    fg = signal.get("fear_greed", {})
    fg_block = ""
    if fg.get("value") is not None:
        v = fg["value"]
        note = ("Extreme Fear — size down" if v <= 25 else
                "Fear — be cautious"       if v <= 45 else
                "Neutral — trade normally" if v <= 55 else
                "Greed — watch reversals"  if v <= 75 else
                "Extreme Greed — tighten SL")
        fg_block = f"\nMACRO: Fear & Greed {v}/100 ({fg.get('label','')}) — {note}\n"

    return f"""DEBATE: Should BR0THA trade {token}?
{social_block}{fg_block}
ALPHA ENGINE: {summary}

KEY STATS:
- Price:      {stats.get('price', md.get('price','?'))}
- 24h Change: {stats.get('change_24h', str(md.get('change_24h','?')) + '%')}
- Volume:     {stats.get('volume', '$' + str(md.get('volume',0)))}
- Liquidity:  {stats.get('liquidity', '$' + str(md.get('liquidity',0)))}
- Rug Score:  {stats.get('rug_score', str(signal.get('rug_score',0)) + '/100')}
- Momentum:   {stats.get('momentum', str(signal.get('momentum_score',0)) + '/100')}
- Holders:    {stats.get('holders','?')}
- Mint Safe:  {stats.get('mint_safe','?')}
- LP Burned:  {stats.get('lp_burned','?')}
{security_block}{concentration_block}{soltracker_block}
MOMENTUM SIGNALS:
{chr(10).join('  + ' + s for s in signals) if signals else '  none'}

BULL CASE:
{chr(10).join('  + ' + b for b in bull) if bull else '  none'}

BEAR CASE:
{chr(10).join('  - ' + b for b in bear) if bear else '  none'}

TRADE PLAN: {plan}

Vote TRADE or PASS. Reference specific numbers. No generic takes."""

# ── debate token ───────────────────────────────────────────────────────────────
async def debate_token(signal, trader_instance):
    """
    Run council debate (if USE_COUNCIL) then hand the signal to Trader.buy().
    trader_instance is the live Trader object so all position state is shared.
    """
    token = signal["token"]
    if token in debated:
        return
    debated.add(token)

    md   = signal.get("market_data", signal)
    fg   = get_fear_and_greed()
    signal["fear_greed"] = fg
    STATS["debates"] += 1

    if USE_COUNCIL:
        prompt = build_prompt(signal)
        cash   = float(trader_instance.balance)
        try:
            result = await collective_debate(
                task=prompt,
                token=token,
                token_data=md,
                portfolio_cash=cash
            )
        except Exception as e:
            log.error(f"Council failed for {token}: {e}")
            print(f"  [ERROR] Council failed: {e}")
            return

        verdict = result["verdict"]
        if not verdict["approved"]:
            print(f"  [PASS] {token} — {verdict['reason']}")
            return

        agents_voted = verdict["trade_count"]
        confidence   = verdict["avg_confidence"]
        print(f"\n  [COUNCIL] ✅ {token} approved — {agents_voted} agents, conf={confidence}%")
    else:
        # Solo mode: auto-approve anything that survived alpha + rug filter
        agents_voted = 1
        confidence   = signal.get("momentum_score", 70)
        print(f"\n  [SOLO] ✅ {token} auto-approved (no council)")

    STATS["trades"] += 1

    # Build coin dict compatible with Trader.buy()
    coin = {
        "name":       token,
        "mint":       md.get("mint", signal.get("mint", "")),
        "price":      md.get("price", 0),
        "mcap":       md.get("mcap", 0),
        "age_hrs":    get_token_age_hours(md.get("mint", signal.get("mint", ""))),
        "liquidity":  md.get("liquidity", 0),
        "volume_24h": md.get("volume", 0),
        "volume_1h":  md.get("volume_1h", 0),
        "change_1h":  md.get("change_24h", 0),
        "change_5m":  md.get("change_5m", 0),
        "buys_1h":    md.get("buys_1h", 0),
        "sells_1h":   md.get("sells_1h", 0),
        "sources":    [signal.get("source", "loop")],
    }

    score   = int(signal.get("score", confidence))
    reasons = signal.get("signals", [signal.get("thesis", {}).get("summary", "alpha engine approved")])

    # Hand off to the sophisticated Trader — it handles sizing, TP/SL tiers,
    # trailing stop, cooldowns, blacklist, brain.learn() feedback, Telegram alerts
    trader_instance.buy(coin, score, reasons[:5])

# ── enrichment helper ──────────────────────────────────────────────────────────
async def _enrich_and_filter(signal):
    """Enrich a token signal, run rug check, age filter. Returns enriched signal or None."""
    from alpha_engine import check_rug_risk, get_momentum_signal, build_thesis

    mint = signal.get("mint", "")
    token = signal["token"]

    if mint:
        enriched = enrich_token(token, mint)
    else:
        enriched = fetch_token_data(token)

    if enriched.get("error"):
        return None

    rug      = check_rug_risk(token, enriched)
    momentum = get_momentum_signal(enriched)
    thesis   = build_thesis(token, enriched, rug, momentum)

    age_hours = get_token_age_hours(mint) if mint else 999.0

    print(f"  [ENRICH] {token} | age={age_hours:.1f}h | rug={rug['risk_score']}/100 | "
          f"momentum={momentum['momentum_score']}/100 | "
          f"mint_safe={enriched.get('mint_authority_disabled','?')} | "
          f"holders={enriched.get('holder_count','?')}")

    if age_hours < MIN_TOKEN_AGE_HOURS:
        print(f"  [REJECT] {token} too new: {age_hours:.1f}h (min={MIN_TOKEN_AGE_HOURS}h)")
        return None

    if not rug["safe"]:
        print(f"  [REJECT] {token} failed rug check: {'; '.join(rug['reasons'][:2])}")
        return None

    signal.update({
        "market_data":    enriched,
        "rug_score":      rug["risk_score"],
        "momentum_score": momentum["momentum_score"],
        "signals":        momentum["signals"],
        "thesis":         thesis,
    })
    return signal

# ══════════════════════════════════════════════════════════════════════════════
#  FAST CYCLE
# ══════════════════════════════════════════════════════════════════════════════
async def fast_cycle(trader):
    now = datetime.utcnow().strftime("%H:%M:%S")
    print(f"\n[{now}] ⚡ FAST SCAN — social + watchlist")

    # ── social scanner ─────────────────────────────────────
    priority = run_social_scan()
    if priority:
        STATS["social_signals"] += len(priority)
        print(f"  [SOCIAL] {len(priority)} priority signals")
        for p in priority[:2]:
            print(f"\n  [SOCIAL DEBATE] {p['token']} from @{p['source']}")
            enriched = await _enrich_and_filter(p)
            if enriched:
                await debate_token(enriched, trader)

    # ── position management (sophisticated trader handles this) ────────────
    if not trader.is_profit_locked() and not trader.is_market_choppy():
        trader.check_positions()
    trader.print_status()

    # ── watchlist price alerts ──────────────────────────────
    alerts = check_watchlist()
    for alert in alerts:
        print(f"\n  [WATCHLIST ALERT] {alert['token']} {alert['change_pct']:+.1f}%")
        sig = {"token": alert["token"], "mint": alert["live_data"].get("mint",""),
               "market_data": alert["live_data"]}
        enriched = await _enrich_and_filter(sig)
        if enriched:
            enriched["signals"] = enriched.get("signals", []) + [f"Price moved {alert['change_pct']:+.1f}%"]
            await debate_token(enriched, trader)

# ══════════════════════════════════════════════════════════════════════════════
#  FULL CYCLE
# ══════════════════════════════════════════════════════════════════════════════
async def full_cycle(trader):
    now = datetime.utcnow().strftime("%H:%M:%S")
    print(f"\n{'='*60}")
    print(f"[{now}] 🔭 FULL SCAN — market wide")
    print(f"{'='*60}")

    try:
        market = build_market()
    except Exception as e:
        print(f"[SCAN ERROR] {e}"); return

    if not market:
        print("[SCAN] No tokens found."); return

    print(f"[SCAN] {len(market)} tokens — filtering...\n")

    # enrich everything
    enriched_market = []
    for token in market:
        mint = token.get("mint", "")
        if mint and len(mint) > 30:
            try:
                enriched = enrich_token(token["token"], mint)
                sym = token["token"]
                token.update({k: v for k, v in enriched.items() if v})
                token["token"] = sym
            except Exception:
                pass
        enriched_market.append(token)

    approved, watching, rejected = filter_market(enriched_market)

    # age filter
    age_filtered = []
    for t in approved:
        age = get_token_age_hours(t.get("mint", ""))
        if age < MIN_TOKEN_AGE_HOURS:
            print(f"  [REJECT] {t['token']} too new: {age:.1f}h")
        else:
            age_filtered.append(t)
    approved = age_filtered

    print(f"\n[ALPHA] {len(approved)} approved | {len(watching)} watching | {len(rejected)} rejected")
    update_watchlist(watching)

    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT INTO scan_log VALUES (NULL,?,?,?,?)",
            (len(market), len(approved),
             approved[0]["token"] if approved else "none",
             datetime.utcnow().isoformat()))

    if not approved:
        print("[ALPHA] Nothing passed filters. Watching the market...")
        return

    # safety gates from trader.py — don't bother debating if we can't trade
    if trader.is_profit_locked():
        print("[ALPHA] Profit locked or daily loss limit — skipping debates")
        return
    if trader.is_market_choppy():
        print("[ALPHA] Market choppy — skipping debates this cycle")
        return

    for signal in approved[:3]:
        print(f"\n[DEBATE] {'='*40}")
        print(f"[DEBATE] {signal['token']} | rug={signal['rug_score']}/100 | "
              f"momentum={signal['momentum_score']}/100")
        await debate_token(signal, trader)
        await asyncio.sleep(15)

# ── heartbeat ──────────────────────────────────────────────────────────────────
def _heartbeat(next_full_s):
    s = STATS
    print(
        f"\n[♥ {_uptime()}] cycles={s['cycles']} · full={s['full_scans']} · "
        f"social={s['social_signals']} · debates={s['debates']} · trades={s['trades']} "
        f"| next full in {max(0, int(next_full_s))}s"
    )

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ASYNC ENGINE
# ══════════════════════════════════════════════════════════════════════════════
async def run_engine():
    mode_label = "LIVE" if not PAPER_TRADE else ("PAPER·SOLO" if not USE_COUNCIL else "PAPER·COUNCIL")
    print()
    print(CY + BD + "╔══════════════════════════════════════════════╗" + RS)
    print(CY + BD + "║   BR0THERH00D — UNIFIED INTELLIGENCE LOOP   ║" + RS)
    print(CY + BD + "╚══════════════════════════════════════════════╝" + RS)
    print(f"  mode={mode_label} · fast={FAST_INTERVAL}s · full={FULL_INTERVAL}s · "
          f"quorum={MIN_AGENTS_TRADE} · min_age={MIN_TOKEN_AGE_HOURS}h")

    init_db()
    init_paper_db()

    fg = get_fear_and_greed()
    print(f"  [MACRO] Fear & Greed: {fg.get('value','?')}/100 ({fg.get('label','?')})")

    # init the sophisticated Trader (handles its own banner + brain state load)
    trader = Trader()

    print("\n  Ctrl+C for a clean shutdown.\n")
    log.info("engine started mode=%s", mode_label)

    last_full = 0.0

    while RUNNING:
        STATS["cycles"] += 1
        now = time.time()

        try:
            await fast_cycle(trader)
        except Exception as e:
            log.error("Fast cycle error: %s", e)
            print(f"[FAST ERROR] {e}")

        if RUNNING and now - last_full >= FULL_INTERVAL:
            try:
                await full_cycle(trader)
                STATS["full_scans"] += 1
                last_full = time.time()
            except Exception as e:
                log.error("Full cycle error: %s", e)
                print(f"[FULL ERROR] {e}")

        # clear debated cache every 2hrs so tokens get re-evaluated
        if STATS["cycles"] % 120 == 0:
            debated.clear()
            print("[SYSTEM] Debated cache cleared — tokens eligible for re-evaluation")

        if not RUNNING:
            break

        _heartbeat(FULL_INTERVAL - (time.time() - last_full))

        # sleep in 1s slices so Ctrl+C is responsive
        for _ in range(FAST_INTERVAL):
            if not RUNNING:
                break
            await asyncio.sleep(1)

    print(f"\n[SYSTEM] stopped after {_uptime()} — "
          f"{STATS['cycles']} cycles · {STATS['debates']} debates · {STATS['trades']} trades.")
    log.info("engine stopped: %s", STATS)

# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    global PAPER_TRADE, USE_COUNCIL

    show_menu()

    try:
        choice = input(CY + "  Select (0-5): " + RS).strip()
    except (EOFError, KeyboardInterrupt):
        shutdown()
    print()

    if choice == "0":
        print(DM + "  Exited.\n" + RS); sys.exit(0)

    # ── Mode 1: Solo Paper — alpha engine, no council ──────────────────────
    elif choice == "1":
        os.environ["TRADE_MODE"] = "paper"
        PAPER_TRADE = True
        USE_COUNCIL = False
        print(GR + BD + "  MODE 1 — Solo Paper Trade (alpha engine only)\n" + RS)
        _import_engine()
        try:
            asyncio.run(run_engine())
        except KeyboardInterrupt:
            print("\n[SYSTEM] interrupted — bye.")

    # ── Mode 2: Paper + Full Council ──────────────────────────────────────
    elif choice == "2":
        os.environ["TRADE_MODE"] = "paper"
        PAPER_TRADE = True
        USE_COUNCIL = True
        print(CY + BD + "  MODE 2 — Paper + 8-Agent Council\n" + RS)
        _import_engine()
        try:
            asyncio.run(run_engine())
        except KeyboardInterrupt:
            print("\n[SYSTEM] interrupted — bye.")

    # ── Mode 3: Live Trading ───────────────────────────────────────────────
    elif choice == "3":
        print(RD + BD + "  ⚠  LIVE MODE — real money will be traded!" + RS)
        print()
        wallet = os.environ.get("WALLET_ADDRESS", "")
        if not wallet:
            print(RD + "  No WALLET_ADDRESS in .env — add it first.\n" + RS)
            sys.exit(1)
        print(DM + f"  Wallet: {wallet[:6]}...{wallet[-4:]}" + RS)
        print()
        try:
            confirm = input(YL + "  Type YES to confirm live trading: " + RS).strip()
        except (EOFError, KeyboardInterrupt):
            shutdown()
        if confirm != "YES":
            print(DM + "\n  Cancelled.\n" + RS); sys.exit(0)

        os.environ["TRADE_MODE"] = "live"
        PAPER_TRADE = False
        USE_COUNCIL = True
        print()
        print(MG + BD + "  MODE 3 — LIVE Trading + Full Council\n" + RS)
        _import_engine()
        try:
            asyncio.run(run_engine())
        except KeyboardInterrupt:
            print("\n[SYSTEM] interrupted — bye.")

    # ── Mode 4: Dashboard (unchanged from Start.py) ────────────────────────
    elif choice == "4":
        os.environ["TRADE_MODE"] = "paper"
        print(YL + BD + "  MODE 4 — Dashboard\n" + RS)
        if not os.path.exists(os.path.join(ROOT, "brotha_api.py")):
            print(RD + "  brotha_api.py not found.\n" + RS); sys.exit(1)
        print(DM + "  Starting API server + dashboard..." + RS)
        api_proc = subprocess.Popen(
            [PYTHON, "-m", "uvicorn", "brotha_api:app",
             "--host", "0.0.0.0", "--port", "8000", "--reload"],
            cwd=ROOT
        )
        _subprocess_procs.append((api_proc, "brotha_api"))
        time.sleep(2)
        print(GR + "  ✅ Dashboard at: " + BD + "http://localhost:8000" + RS)
        print(DM + "  Ctrl+C to stop" + RS)
        try:
            api_proc.wait()
        except KeyboardInterrupt:
            api_proc.terminate()
            print(CY + "\n  Dashboard stopped.\n" + RS)
        sys.exit(0)

    # ── Mode 5: Assistant (unchanged from Start.py) ────────────────────────
    elif choice == "5":
        print(MG + BD + "  MODE 5 — Assistant\n" + RS)
        try:
            import agents.assistant_launcher as launcher
            launcher.run()
        except ImportError:
            print(RD + "  agents/assistant_launcher not found.\n" + RS)
        sys.exit(0)

    else:
        print(DM + "  Unknown option — exited.\n" + RS); sys.exit(0)


if __name__ == "__main__":
    main()

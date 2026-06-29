"""
CONSENSUS ENGINE — The Brotherhood Vote
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every trade goes through a council vote before execution.
Each agent has a role, a weight, and a vote.
Risk manager has veto power.
Memory keeper weighs in from past trades.
Weighted vote: VOTES_NEEDED (below) total weight required to buy, and the Risk
Manager can veto regardless of the tally.
"""
import json, time, os
from datetime import datetime
from core import brain

CY='\033[96m'; GR='\033[92m'; YL='\033[93m'; RD='\033[91m'; BD='\033[1m'; DM='\033[2m'; RS='\033[0m'

# ── Council members & their weights ──────────────
COUNCIL = [
    {"name": "Analyst",       "weight": 3, "role": "AI reasoning"},
    {"name": "Risk Manager",  "weight": 3, "role": "safety guard", "veto": True},
    {"name": "Whale Tracker", "weight": 2, "role": "smart money"},
    {"name": "Pump Hunter",   "weight": 2, "role": "early gems"},
    {"name": "Memory Keeper", "weight": 2, "role": "past lessons"},
    {"name": "News Scout",    "weight": 1, "role": "sentiment"},
    {"name": "Scanner",       "weight": 1, "role": "signal source"},
    {"name": "Venue",         "weight": 2, "role": "pool/DEX venue risk"},
    {"name": "Sizer",         "weight": 2, "role": "price-impact of our exact size"},
]

VOTES_NEEDED = 7  # weighted votes needed to pass

def _vote_analyst(coin: dict, score: int, reasons: list) -> dict:
    """Analyst votes based on score + LLM reasoning."""
    from core.analyst import should_buy
    result = should_buy(coin, score, reasons)
    vote = result.get("buy", False)
    conf = result.get("confidence", 50)
    return {
        "vote":   vote,
        "conf":   conf,
        "reason": result.get("thesis", "")[:80],
        "mode":   result.get("mode", "rules"),
    }

def _vote_risk_manager(coin: dict, score: int) -> dict:
    """Risk manager vetoes if any red flags."""
    name  = coin.get("name", "?")
    mcap  = coin.get("mcap", 0)
    age   = coin.get("age_hrs", 0)
    liq   = coin.get("liquidity", 0)
    ch1h  = coin.get("change_1h", 0)
    vol   = coin.get("volume_24h", 0)

    flags = []
    # age_hrs comes back as 9999 when the data source has no pairCreatedAt
    # timestamp (common for established tokens like JUP, not just missing
    # data on junk) — that's "unknown," not "ancient." Treating it as
    # ancient was vetoing legitimate established tokens. Only flag a real,
    # known age over the threshold.
    if 0 < age <= 999 and age > 48:
        flags.append(f"too old ({age:.0f}h)")
    if liq < 6_000:       flags.append(f"thin liq (${liq:,.0f})")
    if ch1h > 900:         flags.append(f"already pumped {ch1h:.0f}%")
    if mcap > 50_000_000: flags.append(f"mcap too large (${mcap:,.0f})")
    if vol < 8_000:       flags.append(f"low vol (${vol:,.0f})")

    # Bearish market sentiment used to be a hard veto trigger at 5/5 signals
    # regardless of how good the trade otherwise looked. That's too blunt —
    # crypto fear/greed swings hard and a bot that won't trade in "Extreme
    # Fear" misses real setups, not just bad ones. Now it only adds a flag
    # at the most extreme reading (5/5) AND only if the token's own score is
    # mediocre — a genuinely strong setup (score>=70) can clear a fearful
    # market on its own merits instead of being blocked by macro mood alone.
    sent_mems = brain.recall(type="sentiment", limit=5)
    bearish_count = 0
    for m in sent_mems:
        c = m["content"].lower()
        if "bearish" in c or "fear" in c or "dumping" in c:
            bearish_count += 1
    if bearish_count >= 5 and score < 50:
        flags.append(f"bearish market ({bearish_count}/5 signals bearish)")

    # Check recent risk alerts from brain
    risk_mems = brain.recall(agent="risk_manager", limit=5)
    for m in risk_mems:
        if name.lower() in m["content"].lower() and "ALERT" in m["content"]:
            flags.append("prior risk alert")
            break

    vote = len(flags) == 0
    reason = f"flags: {', '.join(flags)}" if flags else "all checks passed"
    return {"vote": vote, "conf": 90 if vote else 10, "reason": reason}

def _vote_whale_tracker(coin: dict) -> dict:
    """Votes YES if whales recently bought this coin."""
    name = coin.get("name", "").lower()
    mint = coin.get("mint", "")
    mems = brain.recall(type="whale_alert", limit=30)
    for m in mems:
        c = m["content"].lower()
        if name in c or (mint and mint[:8].lower() in c):
            return {"vote": True, "conf": 80,
                    "reason": f"whale activity detected"}
    return {"vote": False, "conf": 40,
            "reason": "no whale activity found"}

def _vote_pump_hunter(coin: dict, score: int) -> dict:
    """Votes YES if pump hunter flagged this as a gem."""
    name = coin.get("name", "").lower()
    mint = coin.get("mint", "")
    mems = brain.recall(type="pump_gem", limit=30)
    for m in mems:
        c = m["content"].lower()
        if name in c or (mint and mint[:8].lower() in c):
            return {"vote": True, "conf": 75,
                    "reason": "pump hunter flagged as gem"}
    # Fall back to score
    vote = score >= 55
    return {"vote": vote, "conf": score,
            "reason": f"score={score}/100"}

def _vote_memory_keeper(coin: dict) -> dict:
    """Votes based on past trade outcomes for similar coins."""
    name = coin.get("name", "").lower()
    past = brain.get_learnings(topic=name, limit=5)

    wins = losses = 0
    notes = []
    for l in past:
        insight = l["insight"].lower()
        if "win" in insight or "profit" in insight or "+%" in insight:
            wins += 1
        elif "loss" in insight or "stop" in insight or "-%" in insight:
            losses += 1
        notes.append(l["insight"][:50])

    if wins > losses:
        return {"vote": True,  "conf": 70,
                "reason": f"past record: {wins}W/{losses}L"}
    elif losses > wins:
        return {"vote": False, "conf": 65,
                "reason": f"past losses: {wins}W/{losses}L"}
    else:
        # No track record / tie is NOT a reason to buy — abstain (vote False).
        # (Was vote:True, which biased the council toward buying unknown coins.)
        return {"vote": False, "conf": 50,
                "reason": "no past data — neutral, not a buy signal"}

def _vote_news_scout(coin: dict) -> dict:
    """Votes based on recent sentiment."""
    mems = brain.recall(type="sentiment", limit=10)
    bullish = bearish = 0
    for m in mems:
        c = m["content"].lower()
        if any(w in c for w in ["bullish","pump","moon","buy","surge"]):
            bullish += 1
        elif any(w in c for w in ["bearish","dump","sell","crash","rug"]):
            bearish += 1
    if bearish > bullish:
        return {"vote": False, "conf": 60,
                "reason": f"bearish sentiment ({bearish} signals)"}
    return {"vote": True, "conf": 55,
            "reason": f"neutral/bullish sentiment"}

def _vote_venue(coin: dict) -> dict:
    """Votes based on which DEX/pool this token trades on. An established
    venue (Raydium, a real AMM with a track record) carries less structural
    risk than a brand-new or unrecognized pool — separate from whether the
    TOKEN itself looks like a rug (that's REAPER/Risk Manager's job); this
    is specifically about the trading venue's own track record.
    """
    dex = (coin.get("dex") or "?").lower()

    TRUSTED = {"raydium", "orca", "meteora", "lifinity"}
    KNOWN_RISKY = {"pumpfun_new", "gecko_new", "new_listing"}

    if dex in TRUSTED:
        return {"vote": True, "conf": 80,
                "reason": f"established venue ({dex})"}
    if dex in KNOWN_RISKY or dex == "?":
        return {"vote": False, "conf": 55,
                "reason": f"unverified/new venue ({dex}) — no track record"}
    # Anything else (pumpfun, birdeye, gecko, etc.) — real venues, just not
    # in the "most established" tier. Mild positive, not a red flag.
    return {"vote": True, "conf": 60,
            "reason": f"known venue ({dex}), not top-tier but tracked"}


def _vote_sizer(coin: dict, portfolio_cash: float) -> dict:
    """Checks REAL price impact for the position size we'd actually commit,
    via a live Jupiter quote — not an absolute liquidity threshold like
    other voters use, but the specific question: would OUR trade, at OUR
    size, move the price before it even finishes filling?

    Uses the worst-case size estimate (MAX_TRADE_PCT of portfolio) since the
    actual chosen size only ever scales down from there based on confidence
    — if the worst case is fine, the real (smaller-or-equal) trade is too.
    This is the gap nothing else checks: liquidity floors are absolute
    dollar thresholds, this is relative to what we're actually about to do.
    """
    mint = coin.get("mint", "")
    if not mint or portfolio_cash <= 0:
        return {"vote": True, "conf": 50, "reason": "no mint/cash to check — skipping"}

    try:
        from core import jupiter
        max_size_usd = portfolio_cash * 0.15  # MAX_TRADE_PCT ceiling from trader.py
        quote, err = jupiter.get_quote(jupiter.SOL_MINT, mint, max_size_usd)
        if err or not quote:
            return {"vote": False, "conf": 45,
                    "reason": f"no route at our size (${max_size_usd:.0f}): {err}"}
        impact = float(quote.get("priceImpactPct", 0) or 0)
        if impact > 0.05:
            return {"vote": False, "conf": 70,
                    "reason": f"would move price {impact:.1%} at our size — too thin for us specifically"}
        if impact > 0.03:
            return {"vote": True, "conf": 50,
                    "reason": f"moderate impact {impact:.1%} at our size — workable but tight"}
        return {"vote": True, "conf": 75,
                "reason": f"clean fill, {impact:.1%} impact at our size"}
    except Exception as e:
        return {"vote": True, "conf": 40,
                "reason": f"sizer check unavailable ({e}) — not blocking on it alone"}


def _vote_scanner(coin: dict, score: int) -> dict:
    """Scanner always votes — it found the signal."""
    return {"vote": score >= 62, "conf": score,
            "reason": f"scanner score {score}/100"}


# ── Rule-based fallbacks for AI seats ────────────────────────────────────
# These mirror the exact thresholds already written into each persona's
# system prompt in agent_personas.py (QUANT, EXEC, CHAIN, GUARDIAN). They
# exist so a debate doesn't lose a seat entirely when AI is rate-limited
# or out of credits — instead of "ERROR" defaulting to a block (or silently
# skipping), the seat falls back to the same numeric logic a human already
# decided was the right call. If a real model answers, ITS judgment is
# still used — these only fire when AI genuinely can't be reached.

def _vote_quant_rules(coin: dict) -> dict:
    """Mirrors QUANT's prompt: vol/liq ratio >300% = wash trading risk,
    buy pressure >65% = real accumulation, FDV >$500M on a meme = dump risk."""
    liq = coin.get("liquidity", 0) or 0
    vol = coin.get("volume_24h", 0) or 0
    buys = coin.get("buys_1h", 0) or 0
    sells = coin.get("sells_1h", 0) or 0
    fdv = coin.get("mcap", 0) or 0

    vol_liq_pct = (vol / liq * 100) if liq > 0 else 9999
    total_txns = buys + sells
    buy_pressure_pct = (buys / total_txns * 100) if total_txns > 0 else 50

    flags = []
    if vol_liq_pct > 300:
        flags.append(f"vol/liq {vol_liq_pct:.0f}% — wash trading risk")
    if fdv > 500_000_000:
        flags.append(f"FDV ${fdv:,.0f} too large for a meme")

    if flags:
        return {"vote": False, "conf": 60, "reason": "rule-fallback: " + "; ".join(flags)}
    if buy_pressure_pct > 65:
        return {"vote": True, "conf": 65,
                "reason": f"rule-fallback: buy pressure {buy_pressure_pct:.0f}% — real accumulation"}
    return {"vote": True, "conf": 45,
            "reason": f"rule-fallback: vol/liq {vol_liq_pct:.0f}%, no major flags"}


def _vote_exec_rules(coin: dict) -> dict:
    """Mirrors EXEC's prompt: only trade if a clean entry with defined risk
    can be specced — needs real liquidity and not already wildly extended."""
    liq = coin.get("liquidity", 0) or 0
    ch1h = coin.get("change_1h", 0) or 0

    if liq < 6_000:
        return {"vote": False, "conf": 55,
                "reason": f"rule-fallback: liq ${liq:,.0f} too thin for a clean entry"}
    if ch1h > 900:
        return {"vote": False, "conf": 55,
                "reason": f"rule-fallback: already extended {ch1h:.0f}% — bad entry timing"}
    return {"vote": True, "conf": 55,
            "reason": "rule-fallback: clean entry specable — size 3-13%, TP/SL per config"}


def _vote_chain_rules(coin: dict) -> dict:
    """Mirrors CHAIN's prompt: top 10 holders >60% = rug risk, buy/sell txn
    count diverging hard from volume = wash trading."""
    concentration = coin.get("top10_pct")
    buys = coin.get("buys_1h", 0) or 0
    sells = coin.get("sells_1h", 0) or 0

    if concentration is not None and concentration > 60:
        return {"vote": False, "conf": 65,
                "reason": f"rule-fallback: top10 holders {concentration:.0f}% — rug risk"}

    total_txns = buys + sells
    if total_txns > 0:
        sell_pct = sells / total_txns * 100
        if sell_pct > 70:
            return {"vote": False, "conf": 55,
                    "reason": f"rule-fallback: sells {sell_pct:.0f}% of txns — distribution, not accumulation"}

    return {"vote": True, "conf": 40,
            "reason": "rule-fallback: no concentration red flags in available data"}


def _vote_guardian_ai_rules(coin: dict) -> dict:
    """Mirrors GUARDIAN's hard rules directly — this is the AI-judgment
    half of the fused Queen seat; RiskManager (_vote_risk_manager) already
    covers the same rules independently, so this fallback is intentionally
    conservative-but-not-redundant: it re-checks the same hard limits so
    the fused vote still requires two independent passes even when AI
    is down, rather than silently collapsing to a single check."""
    liq = coin.get("liquidity", 0) or 0
    sells = coin.get("sells_1h", 0) or 0
    buys = coin.get("buys_1h", 0) or 0
    ch24h = coin.get("change_24h", 0) or 0

    if liq < 6_000:
        return {"vote": False, "conf": 70, "reason": f"rule-fallback: liq ${liq:,.0f} < $6K floor"}
    if buys > 0 and sells > buys * 2:
        return {"vote": False, "conf": 65, "reason": "rule-fallback: sells >2x buys"}
    if ch24h > 2000:
        return {"vote": False, "conf": 60, "reason": f"rule-fallback: up {ch24h:.0f}% in 24h — too extended"}
    return {"vote": True, "conf": 55, "reason": "rule-fallback: hard rules clear"}

# ── Main vote function ────────────────────────────
def council_vote(coin: dict, score: int, reasons: list, portfolio_cash: float = 0) -> dict:
    """
    Run the full brotherhood vote.
    Returns {
        "approved": bool,
        "votes_for": int,
        "votes_against": int,
        "vetoed": bool,
        "results": [...],
        "summary": str
    }
    """
    name = coin.get("name", "?")
    now  = datetime.now().strftime("%H:%M:%S")

    print(f"\n{CY}{BD}╔══════════════════════════════════════════════╗{RS}")
    print(f"{CY}{BD}║  🗳️  BROTHERHOOD VOTE — {name:<20} ║{RS}")
    print(f"{CY}{BD}╠══════════════════════════════════════════════╣{RS}")

    # Collect all votes
    raw_votes = {
        "Analyst":       _vote_analyst(coin, score, reasons),
        "Risk Manager":  _vote_risk_manager(coin, score),
        "Whale Tracker": _vote_whale_tracker(coin),
        "Pump Hunter":   _vote_pump_hunter(coin, score),
        "Memory Keeper": _vote_memory_keeper(coin),
        "News Scout":    _vote_news_scout(coin),
        "Scanner":       _vote_scanner(coin, score),
        "Venue":         _vote_venue(coin),
        "Sizer":         _vote_sizer(coin, portfolio_cash),
    }

    results   = []
    total_for = 0
    total_ag  = 0
    vetoed    = False

    for member in COUNCIL:
        mname  = member["name"]
        weight = member["weight"]
        is_veto= member.get("veto", False)
        v      = raw_votes[mname]

        vote   = v["vote"]
        conf   = v["conf"]
        reason = v["reason"]

        weighted = weight if vote else 0
        if vote:
            total_for += weight
        else:
            total_ag  += weight

        # Veto check
        if is_veto and not vote:
            vetoed = True

        emoji = f"{GR}✅{RS}" if vote else f"{RD}❌{RS}"
        veto_tag = f" {RD}[VETO]{RS}" if (is_veto and not vote) else ""
        print(f"  {emoji} {BD}{mname:<14}{RS} {DM}w={weight}{RS}  {reason[:45]}{veto_tag}")

        results.append({
            "agent":   mname,
            "vote":    vote,
            "weight":  weight,
            "conf":    conf,
            "reason":  reason,
            "veto":    is_veto and not vote,
        })

    # Final decision
    approved = (total_for >= VOTES_NEEDED) and not vetoed

    status_color = GR if approved else RD
    status_text  = "APPROVED" if approved else ("VETOED" if vetoed else "REJECTED")

    print(f"{CY}{BD}╠══════════════════════════════════════════════╣{RS}")
    print(f"  {BD}Votes FOR :{RS} {GR}{total_for}{RS}  |  "
          f"{BD}Against:{RS} {RD}{total_ag}{RS}  |  "
          f"{BD}Needed:{RS} {VOTES_NEEDED}")
    print(f"  {status_color}{BD}VERDICT: {status_text}{RS}")
    print(f"{CY}{BD}╚══════════════════════════════════════════════╝{RS}")

    summary = (f"VOTE {status_text} {name} | "
               f"for={total_for} against={total_ag} | "
               f"vetoed={vetoed}")

    # Log to brain
    brain.remember("consensus",
        summary,
        type="council_vote",
        tags=f"{name.lower()},vote,{'approved' if approved else 'rejected'}")

    return {
        "approved":      approved,
        "votes_for":     total_for,
        "votes_against": total_ag,
        "vetoed":        vetoed,
        "results":       results,
        "summary":       summary,
        "status":        status_text,
    }

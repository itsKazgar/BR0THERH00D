"""
UNIFIED COUNCIL — one combined vote, organized like a chessboard
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Previously a trade had to clear TWO completely separate councils:
  1. collective.py's 7 AI personas (SEER, QUANT, EXEC, GUARDIAN, YIELD,
     CHAIN, REAPER) — runs in Start.py's debate_token()
  2. core/consensus.py's 9 rule+memory voters (Analyst, Risk Manager,
     Whale Tracker, Pump Hunter, Memory Keeper, News Scout, Scanner,
     Venue, Sizer) — runs again inside Trader.buy()

This module merges them into ONE vote, run once, with these changes from
the original two-council design (each discussed and confirmed before
building):
  - YIELD dropped. Its job (staking/yield potential) doesn't apply to
    20-30 minute memecoin scalps — it was voting on a question this bot's
    actual trades never have a real answer to.
  - GUARDIAN (AI risk judgment) and Risk Manager (numeric/memory risk
    rules) are kept as two distinct voices feeding ONE seat on the board
    — "the Queen" — rather than two separate votes duplicating the same
    underlying question ("is this trade risky").
  - SIZER added, filling the seat YIELD vacated: checks REAL price impact
    of our actual position size via a live Jupiter quote — a genuine gap
    nothing else checked (every other liquidity check is an absolute
    dollar floor, not "would OUR specific trade move the price").
  - VENUE added: pool/DEX venue risk, using data that was already being
    captured upstream and silently discarded before any vote saw it.

Board layout (13 seats, mapped to what each piece's movement metaphor
fits — not arbitrary, each tier maps to real weight in the final tally):
  KING    (REAPER)                — veto, rug/honeypot/wash-trade detection
  QUEEN   (GUARDIAN + RiskManager)— veto, fused risk judgment + hard rules
  BISHOPS (CHAIN, WhaleTracker)   — diagonal vision: on-chain reads
  KNIGHTS (Sizer, PumpHunter)     — lateral jumps: non-obvious signals
  ROOKS   (QUANT, Analyst)        — straight-line power: pure scoring
  PAWNS   (SEER, EXEC, NewsScout, MemoryKeeper, Scanner, Venue) — the
          many small signals that together read the board's mood
"""
import asyncio
from datetime import datetime
from core import brain
from core.consensus import (
    _vote_analyst, _vote_risk_manager, _vote_whale_tracker, _vote_pump_hunter,
    _vote_memory_keeper, _vote_news_scout, _vote_scanner, _vote_venue, _vote_sizer,
)
from agent_personas import get_persona, COUNCIL_CONFIG
from collective import run_agent

CY='\033[96m'; GR='\033[92m'; YL='\033[93m'; RD='\033[91m'; MG='\033[95m'; BD='\033[1m'; DM='\033[2m'; RS='\033[0m'

# ── Board layout — name -> (tier, weight, veto?) ────────────────────────────
# Weight is the number that actually drives the tally below. Tier is just
# the display grouping; changing tier alone never changes voting power —
# weight is what matters, tier is for readability when you're scanning the
# council's output and want to know at a glance how seriously to take a line.
BOARD = {
    "REAPER":        {"tier": "KING",   "weight": 5, "veto": True},
    "GUARDIAN_FUSED": {"tier": "QUEEN", "weight": 5, "veto": True},
    "CHAIN":         {"tier": "BISHOP", "weight": 2, "veto": False},
    "Whale Tracker": {"tier": "BISHOP", "weight": 2, "veto": False},
    "Sizer":         {"tier": "KNIGHT", "weight": 2, "veto": False},
    "Pump Hunter":   {"tier": "KNIGHT", "weight": 2, "veto": False},
    "QUANT":         {"tier": "ROOK",   "weight": 3, "veto": False},
    "Analyst":       {"tier": "ROOK",   "weight": 3, "veto": False},
    "SEER":          {"tier": "PAWN",   "weight": 1, "veto": False},
    "EXEC":          {"tier": "PAWN",   "weight": 1, "veto": False},
    "News Scout":    {"tier": "PAWN",   "weight": 1, "veto": False},
    "Memory Keeper": {"tier": "PAWN",   "weight": 1, "veto": False},
    "Scanner":       {"tier": "PAWN",   "weight": 1, "veto": False},
    "Venue":         {"tier": "PAWN",   "weight": 1, "veto": False},
}

TOTAL_WEIGHT = sum(v["weight"] for v in BOARD.values())
# Same threshold philosophy as the original two councils (~45-48% needed) —
# kept here rather than re-derived, since that calibration came from the
# original systems' design, not from this merge.
VOTE_THRESHOLD_PCT = 46
MIN_VOTERS_FOR = 5  # at least this many of 13 seats must say yes


async def _run_ai_personas(prompt: str, ai_personas: list) -> dict:
    """Runs the AI-backed personas (SEER, QUANT, EXEC, GUARDIAN, CHAIN,
    REAPER) in parallel, same mechanism collective.py already used and
    tested — not rewritten, just reused so we don't risk regressing
    something that already works."""
    async def _run(agent, i):
        await asyncio.sleep(i * 0.3)
        result = await run_agent(agent, prompt)
        return agent, result

    pairs = await asyncio.gather(*[_run(a, i) for i, a in enumerate(ai_personas)])
    return dict(pairs)


def _fuse_guardian_risk(ai_results: dict, coin: dict, score: int) -> dict:
    """The Queen seat: GUARDIAN's AI judgment and Risk Manager's numeric
    rules both run, and BOTH have to actually pass for this seat to vote
    yes — neither overrides the other; either one raising a flag is a real
    flag. This is stricter than either alone, which is correct for the
    single highest-weighted non-veto-adjacent risk seat on the board.
    """
    guardian = ai_results.get("risk", {})
    g_decision = str(guardian.get("decision", "PASS")).upper()
    g_vote = g_decision == "TRADE"
    g_reason = guardian.get("thesis", "") or guardian.get("reasoning", "")

    rm = _vote_risk_manager(coin, score)
    rm_vote = rm["vote"]
    rm_reason = rm["reason"]

    fused_vote = g_vote and rm_vote
    fused_conf = round((guardian.get("confidence", 50) + rm["conf"]) / 2)

    if not fused_vote:
        bad = []
        if not g_vote: bad.append(f"GUARDIAN: {g_reason[:60]}")
        if not rm_vote: bad.append(f"RiskManager: {rm_reason[:60]}")
        reason = " | ".join(bad)
    else:
        reason = f"both clear — GUARDIAN ok, RiskManager: {rm_reason[:50]}"

    return {"vote": fused_vote, "conf": fused_conf, "reason": reason}


async def unified_vote(coin: dict, score: int, reasons: list, prompt: str,
                        portfolio_cash: float = 0) -> dict:
    """
    Runs the full unified council ONCE and returns a single verdict.
    Replaces calling collective_debate() and then council_vote()
    separately — a trade now clears one board, not two stacked gates.

    Returns: {"approved": bool, "reason": str, "votes_for": int,
              "total_weight": int, "weighted_pct": float,
              "veto_fired": bool, "veto_by": str, "results": [...]}
    """
    name = coin.get("name", "?")
    now = datetime.now().strftime("%H:%M:%S")

    # AI-backed seats run in parallel (real model calls) — same agents as
    # before, minus "income" (YIELD), which is deliberately excluded.
    ai_personas = ["intel", "analyst", "trader", "risk", "onchain", "security"]
    ai_results = await _run_ai_personas(prompt, ai_personas)

    name_map = {"intel": "SEER", "analyst": "QUANT", "trader": "EXEC",
                "risk": "GUARDIAN", "onchain": "CHAIN", "security": "REAPER"}

    votes = {}
    for key, display_name in name_map.items():
        if display_name == "GUARDIAN":
            continue  # handled by the fused Queen seat below, not standalone
        r = ai_results.get(key, {})
        decision = str(r.get("decision", "PASS")).upper()
        votes[display_name] = {
            "vote": decision == "TRADE",
            "conf": r.get("confidence", 50),
            "reason": (r.get("thesis", "") or r.get("reasoning", ""))[:80],
        }

    votes["GUARDIAN_FUSED"] = _fuse_guardian_risk(ai_results, coin, score)
    votes["Whale Tracker"]  = _vote_whale_tracker(coin)
    votes["Pump Hunter"]    = _vote_pump_hunter(coin, score)
    votes["Memory Keeper"]  = _vote_memory_keeper(coin)
    votes["News Scout"]     = _vote_news_scout(coin)
    votes["Scanner"]        = _vote_scanner(coin, score)
    votes["Venue"]          = _vote_venue(coin)
    votes["Sizer"]          = _vote_sizer(coin, portfolio_cash)
    votes["Analyst"]        = _vote_analyst(coin, score, reasons)

    print(f"\n{MG}{BD}╔══════════════════════════════════════════════╗{RS}")
    print(f"{MG}{BD}║  ♟️  UNIFIED COUNCIL — {name:<22}║{RS}")
    print(f"{MG}{BD}╠══════════════════════════════════════════════╣{RS}")

    total_for, total_against, votes_for_count = 0, 0, 0
    veto_fired, veto_by = False, None
    results = []
    standings = brain.get_standings(list(BOARD.keys()), min_votes=5)
    trust_by_seat = {s["seat"]: s["trust"] for s in standings}

    for seat_name, meta in BOARD.items():
        lookup_name = {"GUARDIAN_FUSED": "GUARDIAN_FUSED", "CHAIN": "CHAIN"}.get(seat_name, seat_name)
        v = votes.get(lookup_name) or votes.get(seat_name)
        if v is None:
            continue
        base_weight = meta["weight"]
        is_veto = meta["veto"]

        # Trust earned from this seat's own track record scales its
        # effective weight — never the displayed base weight (that stays
        # fixed so the board layout is always legible), but the number
        # that actually goes into the tally below. A veto seat keeps its
        # veto power regardless of trust — being occasionally wrong about
        # WHEN to veto doesn't strip a safety mechanism, it just affects
        # how much its non-veto votes count when it doesn't veto.
        trust = trust_by_seat.get(seat_name, 1.0)
        weight = round(base_weight * trust, 2)

        if v["vote"]:
            total_for += weight
            votes_for_count += 1
        else:
            total_against += weight
            if is_veto:
                veto_fired = True
                veto_by = seat_name

        # Log this vote now so it can be resolved once the trade closes —
        # this is what builds the seat's track record for NEXT time.
        try:
            vote_context = {
                "mcap": coin.get("mcap", 0),
                "age_hrs": coin.get("age_hrs", 0),
                "liquidity": coin.get("liquidity", 0),
                "dex": coin.get("dex", "?"),
            }
            brain.log_seat_vote(seat_name, name, v["vote"], v.get("conf", 50), v["reason"], vote_context)
        except Exception:
            pass  # logging failure should never block a vote from counting

        emoji = f"{GR}✅{RS}" if v["vote"] else f"{RD}❌{RS}"
        veto_tag = f" {RD}[VETO]{RS}" if (is_veto and not v["vote"]) else ""
        trust_tag = f" {DM}(trust={trust}x){RS}" if trust != 1.0 else ""
        display = "GUARDIAN+RiskMgr" if seat_name == "GUARDIAN_FUSED" else seat_name
        print(f"  {emoji} {BD}{meta['tier']:7}{RS} {display:<17} w={weight}{trust_tag}  {v['reason'][:38]}{veto_tag}")

        results.append({
            "agent": display, "tier": meta["tier"], "vote": v["vote"],
            "weight": weight, "conf": v.get("conf", 50), "reason": v["reason"],
            "veto": is_veto and not v["vote"],
        })

    actual_total_weight = total_for + total_against
    weighted_pct = round((total_for / actual_total_weight) * 100) if actual_total_weight else 0

    if veto_fired:
        approved, reason = False, f"VETO by {veto_by}"
    elif votes_for_count < MIN_VOTERS_FOR:
        approved, reason = False, f"only {votes_for_count}/{MIN_VOTERS_FOR} minimum seats voted yes"
    elif weighted_pct < VOTE_THRESHOLD_PCT:
        approved, reason = False, f"weighted {weighted_pct}% below {VOTE_THRESHOLD_PCT}% threshold"
    else:
        approved, reason = True, f"council approved — {weighted_pct}% weighted yes"

    print(f"{MG}{BD}╠══════════════════════════════════════════════╣{RS}")
    print(f"  Weighted: {weighted_pct}%  |  Seats for: {votes_for_count}/13  |  Veto: {veto_fired}")
    status = f"{GR}APPROVED{RS}" if approved else f"{RD}{'VETOED' if veto_fired else 'REJECTED'}{RS}"
    print(f"  VERDICT: {status} — {reason}")
    print(f"{MG}{BD}╚══════════════════════════════════════════════╝{RS}")

    brain.remember("unified_council",
        f"{name} {('APPROVED' if approved else 'REJECTED')} | {reason} | weighted={weighted_pct}%",
        type="council_vote", tags=f"{name.lower()},unified")

    return {
        "approved": approved, "reason": reason,
        "votes_for": votes_for_count, "total_weight": actual_total_weight,
        "weighted_pct": weighted_pct, "veto_fired": veto_fired,
        "veto_by": veto_by, "results": results,
        "avg_confidence": round(sum(r["conf"] for r in results) / len(results)) if results else 0,
    }

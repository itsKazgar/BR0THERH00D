"""
EXIT CONSENSUS — should we still be holding this position?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entries get a full council vote (core/consensus.py). Exits, until now, got
none — Trader.check_positions() runs pure hardcoded math (fixed trailing-stop
percentages, fixed tier thresholds) with zero input from anything the
council learned at entry time or has learned since.

This module is NOT a replacement for that math — the hardcoded tiers and
trailing stop stay as the safety floor (manual mode always works, even if
this council is offline or returns nothing useful). This is an ADVISORY
layer: it can tell Trader.check_positions() to (a) tighten the stop faster
than the hardcoded schedule would, (b) hold a little past a tier trigger
because the original thesis still looks strong, or (c) do nothing — in
which case the existing hardcoded behavior is unchanged.

Reward/punishment: every closed trade's outcome (win or loss) gets written
back into brain as a `trade_outcome` memory, tagged with which exit-council
signals were active at the time. Over time, _adjust_confidence() reads that
history back and down-weights signals that have been wrong more often than
right for THIS specific bot's actual results — not a fixed assumption, the
bot's own track record. This is the "rewarded for winning, punished for
losing" mechanism, applied to the council's own voice, not just the wallet.
"""
import time
from datetime import datetime
from core import brain

CY='\033[96m'; GR='\033[92m'; YL='\033[93m'; RD='\033[91m'; BD='\033[1m'; DM='\033[2m'; RS='\033[0m'

# How much an exit-council recommendation can adjust the hardcoded trailing
# stop, in percentage points of price. Kept deliberately small — this is
# advisory, not a replacement for the safety floor.
MAX_HOLD_EXTENSION_PCT  = 1.5   # can loosen the stop by at most this much
MAX_CUT_ACCELERATION_PCT = 2.0  # can tighten the stop by at most this much


def _vote_thesis_intact(pos: dict) -> dict:
    """Is the reason we entered still true? Re-reads the entry thesis/sources
    stored on the position and checks whether brain has any NEW negative
    signal (rug flag, bearish narrative) about this exact token since entry."""
    name = pos.get("name", "?")
    mems = brain.recall_relevant(name, limit=15)
    bad_since_entry = [
        m for m in mems
        if m.get("type") in ("rug_alert", "risk_alert")
        and m.get("ts", "") > pos.get("opened_at", "")
    ]
    if bad_since_entry:
        return {"vote": False, "conf": 75,
                "reason": f"new red flag since entry: {bad_since_entry[0]['content'][:60]}"}
    return {"vote": True, "conf": 55,
            "reason": "no new red flags — original thesis still holds"}


def _vote_whale_still_in(pos: dict) -> dict:
    """Are known smart wallets still active around this token, or did they
    already leave? A whale-driven runner that the whales have quietly exited
    is a different risk than one they're still accumulating into."""
    name = pos.get("name", "?")
    mems = brain.recall(type="whale_alert", limit=20)
    recent_hits = [m for m in mems if name.lower() in m.get("content", "").lower()]
    if recent_hits:
        return {"vote": True, "conf": 65,
                "reason": f"whale activity still showing ({len(recent_hits)} recent alert(s))"}
    return {"vote": False, "conf": 40,
            "reason": "no recent whale activity — original smart-money signal may be stale"}


def _vote_narrative_strength(pos: dict) -> dict:
    """Is the narrative that drove this trade still active in the news/social
    feed, or has attention already moved on? A coin riding a fading
    narrative is more likely to bleed than one still getting fresh coverage."""
    name = pos.get("name", "?")
    mems = brain.recall(type="narrative", limit=20)
    hits = [m for m in mems if name.lower() in m.get("content", "").lower()]
    if hits:
        return {"vote": True, "conf": 60,
                "reason": f"narrative still active ({len(hits)} recent mention(s))"}
    return {"vote": False, "conf": 35,
            "reason": "no recent narrative mentions — may be old news already"}


def _vote_momentum_quality(pos: dict, market_data: dict) -> dict:
    """Is the CURRENT move backed by real volume/buy-pressure, or is it
    drifting on thin activity? Distinct from the hardcoded trailing-stop
    math, which only looks at price — this looks at whether the move is
    well-supported or fragile."""
    buys  = market_data.get("buys", 0)
    sells = market_data.get("sells", 0)
    vol   = market_data.get("vol_1h", 0)
    ratio = buys / max(1, buys + sells)
    if ratio >= 0.6 and vol > pos.get("entry_vol", 0) * 0.7:
        return {"vote": True, "conf": 70,
                "reason": f"well-supported move (buys {ratio:.0%}, vol holding)"}
    if ratio < 0.45:
        return {"vote": False, "conf": 60,
                "reason": f"sellers taking over ({ratio:.0%} buys) — move looks fragile"}
    return {"vote": True, "conf": 45,
            "reason": "momentum mixed, nothing decisive either way"}


EXIT_VOTERS = [
    {"name": "Thesis Check",  "weight": 3, "fn": "_vote_thesis_intact"},
    {"name": "Whale Watch",   "weight": 2, "fn": "_vote_whale_still_in"},
    {"name": "Narrative Watch","weight": 2, "fn": "_vote_narrative_strength"},
    {"name": "Momentum Quality","weight": 3, "fn": "_vote_momentum_quality"},
]


def exit_vote(pos: dict, market_data: dict) -> dict:
    """
    Runs the exit council on an open position. Returns an ADVISORY
    adjustment, never a hard override of the hardcoded safety floor:

      {"action": "hold_longer" | "cut_sooner" | "no_change",
       "stop_adjust_pct": float,   # applied on top of the existing stop calc
       "reason": str,
       "votes_for": int, "votes_against": int}

    Trader.check_positions() decides whether/how to apply this — this
    function never touches self.balance or self.positions directly.
    """
    name = pos.get("name", "?")
    votes = {
        "Thesis Check":     _vote_thesis_intact(pos),
        "Whale Watch":      _vote_whale_still_in(pos),
        "Narrative Watch":  _vote_narrative_strength(pos),
        "Momentum Quality": _vote_momentum_quality(pos, market_data),
    }

    total_for = sum(v["weight"] for v in EXIT_VOTERS if votes[v["name"]]["vote"])
    total_ag  = sum(v["weight"] for v in EXIT_VOTERS if not votes[v["name"]]["vote"])
    total_weight = total_for + total_ag

    weighted_for_pct = (total_for / total_weight * 100) if total_weight else 50

    reasons_for = [votes[v["name"]]["reason"] for v in EXIT_VOTERS if votes[v["name"]]["vote"]]
    reasons_against = [votes[v["name"]]["reason"] for v in EXIT_VOTERS if not votes[v["name"]]["vote"]]

    # Apply the bot's own track record to how much weight this verdict gets —
    # the reward/punishment mechanism. A council that's been wrong more than
    # right recently gets less leverage to override the hardcoded floor.
    trust = _signal_trust_multiplier()

    if weighted_for_pct >= 70:
        action = "hold_longer"
        adjust = -MAX_HOLD_EXTENSION_PCT * trust   # loosen stop (more room)
        reason = f"strong case to hold: {'; '.join(reasons_for[:2])}"
    elif weighted_for_pct <= 35:
        action = "cut_sooner"
        adjust = MAX_CUT_ACCELERATION_PCT * trust  # tighten stop
        reason = f"weakening case: {'; '.join(reasons_against[:2])}"
    else:
        action = "no_change"
        adjust = 0.0
        reason = "mixed signals — deferring to the standard trailing stop"

    return {
        "action": action,
        "stop_adjust_pct": round(adjust, 3),
        "reason": reason,
        "votes_for": total_for,
        "votes_against": total_ag,
        "weighted_for_pct": round(weighted_for_pct, 1),
        "trust_multiplier": round(trust, 2),
    }


def _signal_trust_multiplier() -> float:
    """Reward/punishment mechanism: looks at the bot's last N closed trades
    where an exit-council recommendation was active, and scales how much
    influence future recommendations get based on whether following them
    actually helped. Starts at 1.0 (full trust) with no history — earns or
    loses trust only from real outcomes, never from assumption."""
    outcomes = brain.recall(type="trade_outcome", limit=30)
    relevant = [o for o in outcomes if "exit_council_action" in o.get("tags", "")]
    if len(relevant) < 5:
        return 1.0  # not enough history yet — neutral trust

    wins = sum(1 for o in relevant if "WIN" in o.get("content", ""))
    win_rate = wins / len(relevant)

    # Scale smoothly: 50% win rate -> 1.0x (neutral), 80%+ -> up to 1.3x,
    # below 30% -> down to 0.5x. Never goes to zero — even a struggling
    # signal still gets some voice, just less of one.
    if win_rate >= 0.5:
        return min(1.3, 1.0 + (win_rate - 0.5) * 1.0)
    else:
        return max(0.5, 1.0 - (0.5 - win_rate) * 1.0)


def record_outcome(pos: dict, pnl_pct: float, exit_action_taken: str):
    """Call this when a position closes. Writes the outcome back to brain
    so _signal_trust_multiplier() can learn from it next time. This is the
    other half of reward/punishment: every closed trade teaches the exit
    council something about its own track record."""
    result = "WIN" if pnl_pct > 0 else "LOSS"
    msg = f"{pos.get('name','?')} closed {result} {pnl_pct:+.1f}% | exit_action={exit_action_taken}"
    brain.remember("exit_council", msg,
        type="trade_outcome",
        tags=f"exit_council_action,{exit_action_taken},{result.lower()}")

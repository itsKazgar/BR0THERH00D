"""
LEARNING — the outcome ledger. Brothers log PREDICTIONS about the future.
Later, a grader checks what actually happened. Being RIGHT earns standing,
not just being active. This is how a brother actually gets better over time.
"""
import os, sys, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import brain

def _init():
    with brain._conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                brother     TEXT    NOT NULL,
                subject     TEXT    NOT NULL,
                claim       TEXT    NOT NULL,
                metric      TEXT    DEFAULT '',
                baseline    REAL    DEFAULT 0,
                check_after TEXT    NOT NULL,
                status      TEXT    DEFAULT 'pending',
                outcome     REAL    DEFAULT 0,
                correct     INTEGER DEFAULT NULL,
                graded_ts   TEXT    DEFAULT ''
            );
        """)

def predict(brother: str, subject: str, claim: str,
            metric: str = "", baseline: float = 0,
            check_after_hours: float = 24) -> int:
    """
    A brother logs a prediction about the future.
      subject  — what it's about (e.g. a token mint, a topic)
      claim    — plain-language prediction ("will still be alive", "mc will rise")
      metric   — what to measure later ("market_cap", "price", "alive")
      baseline — the value now, to compare against later
      check_after_hours — when this becomes gradeable
    Returns the prediction id.
    """
    _init()
    from datetime import timedelta
    now = datetime.now()
    check_at = (now + timedelta(hours=check_after_hours)).isoformat()
    with brain._conn() as c:
        cur = c.execute(
            "INSERT INTO predictions (ts, brother, subject, claim, metric, baseline, check_after) "
            "VALUES (?,?,?,?,?,?,?)",
            (now.isoformat(), brother, subject, claim, metric, baseline, check_at)
        )
        return cur.lastrowid

def due_for_grading() -> list:
    """Predictions whose check-time has passed and aren't graded yet."""
    _init()
    now = datetime.now().isoformat()
    with brain._conn() as c:
        rows = c.execute(
            "SELECT * FROM predictions WHERE status='pending' AND check_after <= ? ORDER BY id",
            (now,)
        ).fetchall()
    return [dict(r) for r in rows]

def grade(prediction_id: int, outcome_value: float, correct: bool) -> str:
    """Record what actually happened for a prediction."""
    _init()
    with brain._conn() as c:
        c.execute(
            "UPDATE predictions SET status='graded', outcome=?, correct=?, graded_ts=? WHERE id=?",
            (outcome_value, 1 if correct else 0, datetime.now().isoformat(), prediction_id)
        )
    return f"{'✓ RIGHT' if correct else '✗ WRONG'}: prediction #{prediction_id}"

def scorecard(brother: str = None) -> str:
    """How accurate has a brother been? Or the whole brotherhood."""
    _init()
    with brain._conn() as c:
        if brother:
            rows = c.execute(
                "SELECT correct FROM predictions WHERE brother=? AND status='graded'",
                (brother,)
            ).fetchall()
            who = brother
        else:
            rows = c.execute(
                "SELECT correct FROM predictions WHERE status='graded'"
            ).fetchall()
            who = "the brotherhood"
    graded = [r["correct"] for r in rows]
    if not graded:
        return f"No graded predictions yet for {who}. Reps take time to prove out."
    right = sum(graded)
    total = len(graded)
    pct = 100 * right / total
    return f"📊 {who}: {right}/{total} correct ({pct:.0f}% accuracy over graded predictions)"

def accuracy(brother: str) -> float:
    """Raw accuracy 0.0-1.0 for a brother, or 0 if none graded. For rank logic later."""
    _init()
    with brain._conn() as c:
        rows = c.execute(
            "SELECT correct FROM predictions WHERE brother=? AND status='graded'",
            (brother,)
        ).fetchall()
    graded = [r["correct"] for r in rows]
    return (sum(graded) / len(graded)) if graded else 0.0

def grade_crypto_predictions() -> str:
    """
    The grader. Re-checks due crypto predictions against live price.
    Bullish call right if price rose; bearish right if it fell.
    This is the moment a brother actually learns.
    """
    import requests
    due = [p for p in due_for_grading() if p["brother"] == "crypto"]
    if not due:
        return "No crypto predictions are due for grading yet."

    results = []
    for p in due:
        sym = p["subject"]
        baseline = p["baseline"]
        # fetch current price (free)
        now_price = None
        try:
            if sym == "SOL":
                r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=6)
                now_price = float(r.json()["solana"]["usd"])
            else:
                r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={sym}", timeout=8)
                pairs = [x for x in r.json().get("pairs", [])
                         if x.get("chainId") == "solana"
                         and x.get("baseToken", {}).get("symbol", "").upper() == sym]
                if pairs:
                    best = sorted(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
                    now_price = float(best.get("priceUsd", 0) or 0)
        except Exception as e:
            results.append(f"  #{p['id']} {sym}: couldn't fetch price to grade ({e})")
            continue

        if not now_price:
            results.append(f"  #{p['id']} {sym}: no price, skipped")
            continue

        rose = now_price > baseline
        bullish = "higher" in p["claim"]
        correct = (rose and bullish) or (not rose and not bullish)
        grade(p["id"], outcome_value=now_price, correct=correct)
        move = (now_price - baseline) / baseline * 100 if baseline else 0
        results.append(f"  #{p['id']} {sym}: ${baseline:.2f} -> ${now_price:.2f} ({move:+.1f}%) "
                       f"{'✓ RIGHT' if correct else '✗ WRONG'}")

    return "📊 GRADED:\n" + "\n".join(results)

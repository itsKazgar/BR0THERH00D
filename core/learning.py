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

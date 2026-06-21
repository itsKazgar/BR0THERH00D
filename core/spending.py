"""
SPENDING — brothers can REQUEST a spend. Only Kazgar approves.
No brother can move money on its own. Rank gates how much they can even ask for.
Funding and custody always stay with Kazgar.
"""
import os, sys, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import brain, council

# Rank-gated request ceilings (USD). A brother can't ask beyond its station.
RANK_CEILING = {
    "Initiate":     0,      # must earn the right to spend at all
    "Apprentice":   5,
    "Fellow":       20,
    "Master":       50,
    "Grand Master": 100,
}

def _init():
    with brain._conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS spend_requests (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                brother   TEXT    NOT NULL,
                item      TEXT    NOT NULL,
                cost_usd  REAL    NOT NULL,
                reason    TEXT    DEFAULT '',
                status    TEXT    DEFAULT 'pending',
                decided   TEXT    DEFAULT ''
            );
        """)

def request_spend(brother_id: str, item: str, cost_usd: float, reason: str = "") -> str:
    """A brother asks to spend. Returns a human-readable result. Never spends."""
    _init()
    _, rank_title, _ = council.get_rank(brother_id)
    ceiling = RANK_CEILING.get(rank_title, 0)

    if ceiling == 0:
        return (f"🚫 {brother_id} is an {rank_title} — not yet trusted to spend. "
                f"Earn more reps first.")
    if cost_usd > ceiling:
        return (f"🚫 {brother_id} ({rank_title}) can request up to ${ceiling}. "
                f"${cost_usd:.2f} is above their station. Denied automatically.")

    with brain._conn() as c:
        c.execute(
            "INSERT INTO spend_requests (ts, brother, item, cost_usd, reason, status) "
            "VALUES (?,?,?,?,?, 'pending')",
            (datetime.now().isoformat(), brother_id, item, cost_usd, reason)
        )
    return (f"📨 {brother_id} requests ${cost_usd:.2f} for '{item}'. "
            f"Awaiting Kazgar's approval. (Within {rank_title} limit of ${ceiling}.)")

def pending() -> list:
    """All requests awaiting your decision."""
    _init()
    with brain._conn() as c:
        rows = c.execute(
            "SELECT * FROM spend_requests WHERE status='pending' ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]

def decide(request_id: int, approve: bool) -> str:
    """Kazgar approves or denies. This records the decision — it does NOT move money."""
    _init()
    status = "approved" if approve else "denied"
    with brain._conn() as c:
        row = c.execute("SELECT * FROM spend_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            return f"No request #{request_id}."
        c.execute("UPDATE spend_requests SET status=?, decided=? WHERE id=?",
                  (status, datetime.now().isoformat(), request_id))
    verb = "✅ APPROVED" if approve else "❌ DENIED"
    return f"{verb}: #{request_id} — {row['brother']} → {row['item']} (${row['cost_usd']:.2f})"

def show() -> str:
    """Readable summary of all pending requests."""
    reqs = pending()
    if not reqs:
        return "No pending spend requests."
    lines = ["💳 PENDING SPEND REQUESTS\n"]
    for r in reqs:
        lines.append(f"  #{r['id']}  {r['brother']:12} ${r['cost_usd']:>6.2f}  {r['item']}")
        if r['reason']:
            lines.append(f"        reason: {r['reason']}")
    lines.append("\nApprove: spending.decide(<id>, True)  |  Deny: spending.decide(<id>, False)")
    return "\n".join(lines)


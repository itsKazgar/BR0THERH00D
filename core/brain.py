"""
BRAIN — Shared memory layer for BR0THERH00D collective.
SQLite-backed. All agents read/write through here.
"""
import sqlite3, json, os, time
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "brain.db")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                agent     TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                type      TEXT    DEFAULT 'general',
                tags      TEXT    DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS learnings (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT    NOT NULL,
                agent     TEXT    NOT NULL,
                topic     TEXT    NOT NULL,
                insight   TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (
                agent     TEXT    PRIMARY KEY,
                data      TEXT    NOT NULL,
                updated   TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seat_votes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                seat        TEXT    NOT NULL,
                token       TEXT    NOT NULL,
                vote        TEXT    NOT NULL,
                confidence  INTEGER DEFAULT 50,
                reason      TEXT    DEFAULT '',
                context     TEXT    DEFAULT '{}',
                outcome     TEXT    DEFAULT NULL,
                pnl_pct     REAL    DEFAULT NULL,
                resolved_ts TEXT    DEFAULT NULL
            );
        """)

def remember(agent: str, content: str, type: str = "general", tags: str = ""):
    with _conn() as c:
        c.execute(
            "INSERT INTO memories (ts, agent, content, type, tags) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), agent, content, type, tags)
        )

def recall(agent: str = None, type: str = None, limit: int = 20) -> list:
    query  = "SELECT * FROM memories WHERE 1=1"
    params = []
    if agent:
        query += " AND agent = ?"; params.append(agent)
    if type:
        query  += " AND type = ?";  params.append(type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def recall_relevant(query: str, agent: str = None, limit: int = 12) -> list:
    """
    Smarter recall for the assistant: returns memories RELEVANT to `query`
    (by keyword overlap), blended with recent ones. Existing recall() is
    unchanged — this is purely additive and safe.
    """
    import re
    rows = recall(agent=agent, limit=300)   # wide recent window to search
    if not rows:
        return []

    words = set(w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 3)
    if not words:
        return rows[:limit]                 # no keywords -> just most recent

    scored = []
    n = len(rows)
    for i, m in enumerate(rows):
        text = (m.get("content", "") + " " + m.get("tags", "")).lower()
        overlap = sum(1 for w in words if w in text)
        recency = (n - i) / n               # 1.0 newest -> ~0 oldest
        score = overlap * 2 + recency       # relevance weighted above recency
        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:limit]]


def learn(agent: str, topic: str, insight: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO learnings (ts, agent, topic, insight) VALUES (?,?,?,?)",
            (datetime.now().isoformat(), agent, topic, insight)
        )

def get_learnings(topic: str = None, limit: int = 10) -> list:
    query  = "SELECT * FROM learnings WHERE 1=1"
    params = []
    if topic:
        query += " AND topic LIKE ?"; params.append(f"%{topic}%")
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]

def load_state(agent: str) -> dict:
    with _conn() as c:
        row = c.execute("SELECT data FROM state WHERE agent=?", (agent,)).fetchone()
    return json.loads(row["data"]) if row else {}

def save_state(agent: str, data: dict):
    with _conn() as c:
        c.execute(
            "INSERT INTO state (agent, data, updated) VALUES (?,?,?) "
            "ON CONFLICT(agent) DO UPDATE SET data=excluded.data, updated=excluded.updated",
            (agent, json.dumps(data), datetime.now().isoformat())
        )

def brain_summary():
    with _conn() as c:
        mem_count = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        lea_count = c.execute("SELECT COUNT(*) FROM learnings").fetchone()[0]
    print(f"  🧠 Brain: {mem_count} memories | {lea_count} learnings | db={DB_PATH}\n")

# ── PER-SEAT TRACK RECORD ─────────────────────────────────────────────────
# Every council seat (REAPER, SEER, GUARDIAN, etc) logs its own vote here
# at decision time. When a trade closes, resolve_seat_votes() fills in
# whether that vote turned out right. This is what lets each seat build an
# individual, honest track record instead of all voices being treated as
# equally reliable forever, and lets every seat see how every OTHER seat is
# actually doing — for calibration, not for copying the leader.

def log_seat_vote(seat: str, token: str, vote: bool, confidence: int, reason: str, context: dict = None):
    """Called once per seat, per trade, at vote time. `context` should hold
    the key facts about the coin at vote time (mcap, age_hrs, dex, liquidity)
    — without this, a later pattern-derivation step would have nothing real
    to point to and would have to invent a plausible-sounding reason instead
    of an actually-observed one."""
    with _conn() as c:
        c.execute(
            "INSERT INTO seat_votes (ts, seat, token, vote, confidence, reason, context) "
            "VALUES (?,?,?,?,?,?,?)",
            (datetime.now().isoformat(), seat, token,
             "TRADE" if vote else "PASS", confidence, reason[:200],
             json.dumps(context or {}))
        )

def resolve_seat_votes(token: str, pnl_pct: float, window_minutes: int = 120):
    """Called when a trade closes. Finds this token's most recent unresolved
    votes (within window_minutes, so an old unrelated vote on the same
    symbol months ago doesn't get the wrong outcome attached) and marks:
      - A seat that voted TRADE and the trade WON -> correct
      - A seat that voted TRADE and the trade LOST -> wrong
      - A seat that voted PASS and the trade LOST -> correct (good catch)
      - A seat that voted PASS and the trade WON  -> wrong (missed it)
    This is the fairness rule: a PASS vote can be just as right or wrong as
    a TRADE vote. A seat doesn't get punished for caution that paid off, or
    rewarded for caution that cost a real gain.
    """
    won = pnl_pct > 0
    cutoff = (datetime.now() - timedelta(minutes=window_minutes)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT id, vote FROM seat_votes WHERE token=? AND resolved_ts IS NULL "
            "AND ts >= ? ORDER BY id DESC",
            (token, cutoff)
        ).fetchall()
        now = datetime.now().isoformat()
        for r in rows:
            voted_trade = r["vote"] == "TRADE"
            correct = (voted_trade and won) or (not voted_trade and not won)
            c.execute(
                "UPDATE seat_votes SET outcome=?, pnl_pct=?, resolved_ts=? WHERE id=?",
                ("correct" if correct else "wrong", pnl_pct, now, r["id"])
            )

def get_seat_trust(seat: str, min_votes: int = 5) -> dict:
    """Returns this seat's own track record: win rate on resolved votes and
    a trust multiplier (0.5x-1.3x) the same way the exit council already
    proved out. Below min_votes, returns neutral 1.0x — a seat earns trust
    only from real history, never from assumption."""
    with _conn() as c:
        rows = c.execute(
            "SELECT outcome FROM seat_votes WHERE seat=? AND outcome IS NOT NULL",
            (seat,)
        ).fetchall()
    total = len(rows)
    if total < min_votes:
        return {"trust": 1.0, "accuracy": None, "total_resolved": total}
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    accuracy = correct / total
    if accuracy >= 0.5:
        trust = min(1.3, 1.0 + (accuracy - 0.5) * 1.0)
    else:
        trust = max(0.5, 1.0 - (0.5 - accuracy) * 1.0)
    return {"trust": round(trust, 3), "accuracy": round(accuracy, 3), "total_resolved": total}

def get_standings(seats: list, min_votes: int = 5) -> list:
    """Every seat's trust/accuracy in one place — this is what lets seats
    see how everyone else is doing, sorted best to worst. Used to give
    AI personas real, current context about the whole team's performance,
    not just their own."""
    standings = []
    for seat in seats:
        t = get_seat_trust(seat, min_votes)
        standings.append({"seat": seat, **t})
    standings.sort(key=lambda x: (x["accuracy"] is not None, x["accuracy"] or 0), reverse=True)
    return standings

def share_idea(agent: str, content: str, type: str = "idea", tags: str = "", **kwargs):
    """Alias used by scanner — stores a signal/idea to shared memory."""
    remember(agent, content, type=type, tags=tags)

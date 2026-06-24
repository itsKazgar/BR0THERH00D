"""
outcomes.py - BR0THA Paper Trade Scorer
Runs as a background job. Every hour:
  1. Finds paper trades older than 1h with no outcome yet
  2. Fetches current price via Jupiter
  3. Calculates PnL
  4. Writes to outcomes table
  5. Injects per-agent performance into council_votes for memory
"""
import sqlite3, time, requests, os
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

DB = "data/agent.db"
JUPITER_URL = "https://price.jup.ag/v6/price"
HEADERS = {"User-Agent": "BR0THA/1.0"}
CHECK_AFTER_HOURS = 1

def get_price_jupiter(mint):
    if not mint:
        return None
    try:
        r = requests.get(JUPITER_URL, params={"ids": mint}, headers=HEADERS, timeout=10)
        data = r.json().get("data", {})
        entry = data.get(mint) or next(iter(data.values()), None)
        return float(entry["price"]) if entry else None
    except:
        return None

def score_outcomes():
    db = sqlite3.connect(DB)
    now = datetime.now(timezone.utc)

    # Find paper trades not yet in outcomes, older than CHECK_AFTER_HOURS
    rows = db.execute("""
        SELECT pt.id, pt.token, pt.decision, pt.price, pt.timestamp,
               cv.agent, cv.decision as agent_decision
        FROM paper_trades pt
        LEFT JOIN council_votes cv ON cv.token = pt.token
        WHERE pt.token NOT IN (SELECT token FROM outcomes)
        AND (julianday('now') - julianday(pt.timestamp)) * 24 >= ?
    """, (CHECK_AFTER_HOURS,)).fetchall()

    if not rows:
        print(f"[{now.strftime('%H:%M:%S')}] No paper trades ready to score")
        return

    # Group by trade
    trades = {}
    for row in rows:
        tid, token, decision, entry_price, ts, agent, agent_decision = row
        if token not in trades:
            trades[token] = {
                "id": tid, "token": token, "decision": decision,
                "entry_price": entry_price, "timestamp": ts, "agents": {}
            }
        if agent:
            trades[token]["agents"][agent] = agent_decision

    for token, trade in trades.items():
        entry_price = float(trade["entry_price"]) if trade["entry_price"] else None
        if not entry_price:
            print(f"  [SKIP] {token} — no entry price")
            continue

        # Need mint to fetch price — look up from council_votes or skip
        mint_row = db.execute(
            "SELECT ca FROM social_signals WHERE symbol=? LIMIT 1", (token,)
        ).fetchone()
        mint = mint_row[0] if mint_row else None

        current_price = get_price_jupiter(mint) if mint else None
        if not current_price:
            print(f"  [SKIP] {token} — can't fetch current price")
            continue

        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        result = "WIN" if pnl_pct > 0 else "LOSS"
        emoji = "✅" if pnl_pct > 0 else "❌"

        print(f"  {emoji} {token}: entry=${entry_price:.6f} now=${current_price:.6f} PnL={pnl_pct:+.1f}% [{result}]")

        db.execute("""
            INSERT OR IGNORE INTO outcomes (token, signal_ts, decision, entry_price, check_price, pnl_pct, check_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            token, trade["timestamp"], trade["decision"],
            str(entry_price), str(current_price),
            round(pnl_pct, 2),
            now.isoformat()
        ))

    db.commit()
    db.close()
    print_leaderboard()

def print_leaderboard():
    db = sqlite3.connect(DB)
    print("\n  === AGENT LEADERBOARD ===")
    rows = db.execute("""
        SELECT cv.agent,
               COUNT(*) as votes,
               SUM(CASE WHEN cv.decision='TRADE' AND o.pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN cv.decision='TRADE' AND o.pnl_pct <= 0 THEN 1 ELSE 0 END) as losses,
               ROUND(AVG(CASE WHEN cv.decision='TRADE' THEN o.pnl_pct END), 1) as avg_pnl
        FROM council_votes cv
        JOIN outcomes o ON o.token = cv.token
        GROUP BY cv.agent
        ORDER BY avg_pnl DESC
    """).fetchall()
    for r in rows:
        agent, votes, wins, losses, avg_pnl = r
        avg_pnl = avg_pnl or 0
        print(f"  {agent:<12} votes={votes} wins={wins} losses={losses} avg_pnl={avg_pnl:+.1f}%")
    db.close()

def get_agent_memory(agent_key, limit=10):
    """Call this from collective.py to inject memory into agent prompts."""
    db = sqlite3.connect(DB)
    rows = db.execute("""
        SELECT cv.token, cv.decision, o.pnl_pct, o.check_ts
        FROM council_votes cv
        JOIN outcomes o ON o.token = cv.token
        WHERE cv.agent = ?
        ORDER BY o.check_ts DESC
        LIMIT ?
    """, (agent_key, limit)).fetchall()
    db.close()
    if not rows:
        return ""
    lines = [f"Your last {len(rows)} scored trades:"]
    wins = sum(1 for r in rows if r[1] == "TRADE" and r[2] and r[2] > 0)
    for token, decision, pnl, ts in rows:
        pnl_str = f"{pnl:+.1f}%" if pnl is not None else "pending"
        lines.append(f"  {token}: you voted {decision} → {pnl_str}")
    lines.append(f"Win rate on TRADE votes: {wins}/{len([r for r in rows if r[1]=='TRADE'])}")
    return "\n".join(lines)

if __name__ == "__main__":
    print("BR0THA Outcomes Scorer — running every 60min")
    while True:
        score_outcomes()
        time.sleep(3600)

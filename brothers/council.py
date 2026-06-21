import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import council as C
from core import spending as S

NAME        = "Council Brother"
DESCRIPTION = "The council — status, ranks, tome, convene all brothers"
ENABLED     = True
COMMANDS    = ["council", "convene", "brotherhood", "status", "ranks", "tome", "spend", "approve <id>", "deny <id>"]

TRIGGERS    = ["council", "convene", "brotherhood", "the council",
               "ranks", "who are we", "tome", "show the brothers",
               "brotherhood status", "all brothers"]

def run(user_input: str):
    lower = user_input.lower().strip()

    # ── Spending review — Kazgar only decides here ──
    if lower.startswith("spend") or lower.startswith("pending") or lower.startswith("requests"):
        return S.show()
    if lower.startswith("approve "):
        try:
            rid = int(lower.split()[1])
            return S.decide(rid, True)
        except (IndexError, ValueError):
            return "Usage: approve <request-id>"
    if lower.startswith("deny ") or lower.startswith("reject "):
        try:
            rid = int(lower.split()[1])
            return S.decide(rid, False)
        except (IndexError, ValueError):
            return "Usage: deny <request-id>"

    if not any(lower.startswith(t) for t in TRIGGERS):
        return None

    if any(x in lower for x in ["convene", "meeting", "gather"]):
        return C.convene(task=user_input)

    if any(x in lower for x in ["tome", "ledger", "signals"]):
        entries = C.read_tome(limit=10)
        if not entries:
            return "📜 The Tome is empty. Brothers must inscribe their findings."
        lines = ["📜 THE TOME — Recent Inscriptions\n"]
        for e in entries:
            lines.append(f"  [{e['agent']}] {e['content'][:100]}")
        return "\n".join(lines)

    # Default — full brotherhood status
    return C.brotherhood_status()

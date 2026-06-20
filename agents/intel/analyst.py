"""
analyst.py — AI reasoning agent, analyzes signals from brain and writes conclusions
Runs every 3 minutes, reads recent memories, thinks about them, writes back insights
"""
import time, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from core import brain, analyst as llm

INTERVAL = 180  # every 3 mins
CY='\033[96m'; GR='\033[92m'; RS='\033[0m'; BD='\033[1m'

def analyze():
    mems = brain.recall(type="trade_signal", limit=10) + brain.recall(type="sentiment", limit=5)
    if not mems:
        print(f"{CY}[analyst]{RS} No memories yet, waiting...")
        return
    # brain.recall returns dicts — use the text, not the dict repr
    context = "\n".join(f"- {m.get('content', '')}" for m in mems[:15])
    prompt = (
        "You are a Solana alpha trading analyst. Based on these recent signals:\n"
        f"{context}\n\n"
        "Give a 1-sentence market insight and whether to be bullish, bearish, or neutral right now."
    )
    insight = llm.think(prompt, fast=True)
    # don't store LLM-failure sentinels ("[no_llm]", "[groq unavailable: ...]")
    # as if they were real analysis
    if insight and not insight.strip().startswith("["):
        brain.remember("analyst", insight, type="analyst_insight", tags="analyst,insight")
        print(f"{GR}[analyst]{RS} {insight}")
    else:
        print(f"{CY}[analyst]{RS} No usable LLM response, skipping")

def run():
    print(f"{BD}{CY}[analyst]{RS} Analyst agent started")
    while True:
        try:
            analyze()
        except Exception as e:
            print(f"[analyst] error: {e}")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    run()

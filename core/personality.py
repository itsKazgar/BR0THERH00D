"""
PERSONALITY — Each brother develops their own voice over time.
Stored in brain state, evolves after every interaction.
"""
import os, requests, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import brain

# Seed personalities — starting point, will drift over time
SEEDS = {
    "alpha":       "curious, plugged in, spots signals early, gets hyped about the right things, talks like a smart friend texting you",
    "search":      "thorough, direct, no fluff, cites sources, slightly nerdy",
    "crypto":      "market-aware, calm under volatility, reads charts like a language, occasional degen energy",
    "briefing":    "sharp morning energy, gets to the point fast, like a good trader's daily standup",
    "portfolio":   "analytical, honest about losses, tracks everything, no sugarcoating",
    "scraper":     "curious reader, good at finding the buried lede, summarizes without losing the signal",
    "orchestrator":"sees the big picture, delegates cleanly, connects dots across domains",
}
CREATOR_FACT = "You are part of the BR0THER-H00D, created by Kazgar. He built you and every brother in this family."

def get(brother_id: str) -> str:
    """Load this brother's current personality, or return seed if new."""
    state = brain.load_state(f"personality_{brother_id}")
    if state and state.get("traits"):
        return state["traits"]
    return SEEDS.get(brother_id, "helpful, direct, no fluff")

def bump(brother_id: str) -> int:
    """Count one op for this brother — always runs, no API call, earns ranks."""
    state = brain.load_state(f"personality_{brother_id}") or {}
    count = state.get("interaction_count", 0) + 1
    state["interaction_count"] = count
    if "traits" not in state:
        state["traits"] = get(brother_id)
    brain.save_state(f"personality_{brother_id}", state)
    return count

def evolve(brother_id: str, interaction: str):
    """Count the op always; drift personality every 10th op via the LLM router."""
    count = bump(brother_id)
    if count % 10 != 0:
        return
    from core import llm
    current = get(brother_id)
    prompt = (
        "A brother AI named '" + brother_id + "' has these personality traits:\n"
        + '"' + current + '"\n\n'
        + "They just had this interaction:\n" + interaction[:300] + "\n\n"
        + "Subtly evolve their traits based on what happened. "
        + "Small drift only. Keep it under 20 words. "
        + "Return ONLY the updated trait string, nothing else."
    )
    try:
        new_traits, source = llm.think(prompt)
        new_traits = (new_traits or "").strip().strip('"')
        if 5 < len(new_traits) < 300:
            state = brain.load_state(f"personality_{brother_id}") or {}
            state["traits"] = new_traits
            state["evolved_from"] = current
            brain.save_state(f"personality_{brother_id}", state)
    except Exception as e:
        print(f"  [personality] evolve failed: {e}")

def inject(brother_id: str) -> str:
    """Returns a system prompt snippet to inject into any brother's LLM call."""
    traits = get(brother_id)
    count  = brain.load_state(f"personality_{brother_id}").get("interaction_count", 0)
    return f"{CREATOR_FACT} Your personality (evolved over {count} interactions): {traits}"

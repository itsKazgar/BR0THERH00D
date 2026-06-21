import os, requests, sys, threading
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import personality

NAME        = "Alpha Brother"
DESCRIPTION = "Studies AI, crypto, Solana ecosystem from free RSS + search. Any-LLM digest."
ENABLED     = True
COMMANDS    = ["alpha", "tech", "ai news", "crypto news", "solana news", "study <topic>"]

TRIGGERS = ["what launched", "what shipped", "show me alpha", "alpha", "tech news",
            "ai news", "what's new in ai", "yc", "startups", "builders",
            "what dropped", "new tools", "new ai", "crypto news", "solana news",
            "study ", "what's happening in", "catch me up"]

# Free RSS feeds — no keys, no cost. Real publications.
RSS = {
    "ai": [
        "https://huggingface.co/blog/feed.xml",
        "https://www.artificialintelligence-news.com/feed/",
    ],
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
        "https://cointelegraph.com/rss",
    ],
    "solana": [
        "https://solana.com/news/rss.xml",
        "https://cointelegraph.com/rss/tag/solana",
    ],
    "tech": [
        "https://hnrss.org/frontpage",
        "https://techcrunch.com/feed/",
    ],
}

# Search fallback queries if RSS comes up dry
SEARCH = {
    "ai":     "latest AI tools models released",
    "crypto": "crypto market news today",
    "solana": "Solana ecosystem news updates",
    "tech":   "tech startups product launches this week",
}

def _read_rss(urls, limit=6):
    import feedparser, socket
    socket.setdefaulttimeout(6)  # never hang on a slow feed
    items = []
    for u in urls:
        try:
            feed = feedparser.parse(u)
            for e in feed.entries[:limit]:
                items.append({
                    "title": e.get("title", ""),
                    "body":  (e.get("summary", "") or "")[:220],
                    "url":   e.get("link", ""),
                })
        except Exception as ex:
            print(f"  [alpha] rss {u} failed: {ex}")
    return items

def _search(query, limit=6):
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return [{"title": r.get("title",""), "body": r.get("body","")[:220],
                     "url": r.get("url","")} for r in d.news(query, max_results=limit)]
    except Exception as e:
        print(f"  [alpha] search failed: {e}")
        return []

def _format(topic, items):
    if not items:
        return "No fresh items found."
    lines = [f"\u26a1 ALPHA \u2014 {topic.upper()}\n"]
    for r in items[:6]:
        body = r["body"].strip()
        lines.append(f"\u2022 {r['title']}\n  {body}\n  {r['url']}")
    return "\n\n".join(lines)

def _digest(topic, items):
    """Any-LLM synthesis on top — bonus layer, not required."""
    from core import llm
    context = ""
    for r in items[:8]:
        context += f"- {r['title']}: {r['body'][:180]} ({r['url']})\n"
    prompt = (
        "You brief a reader who follows tech/crypto closely and hates the obvious. "
        "Topic: " + topic + ".\n\n"
        "SOURCE MATERIAL (only facts you may use):\n" + context + "\n"
        "Lead with the single most important item + why it matters. Then 3-4 more, "
        "one line each: what happened + the so-what. Skip pure price moves and "
        "headlines everyone saw. Only facts from the source. Never invent numbers, "
        "dates, or quotes. End each item with its URL. No preamble."
    )
    try:
        resp, source = llm.think(prompt)
        if resp and resp.strip():
            return f"\u26a1 ALPHA \u2014 {topic.upper()}\n\n" + resp.strip()
    except Exception as e:
        print(f"  [alpha] digest failed: {e}")
    return None

def _pick_topic(lower):
    if any(x in lower for x in ["solana", "sol ", "anatoly", "jupiter", "jito"]):
        return "solana"
    if any(x in lower for x in ["crypto", "bitcoin", "ethereum", "btc", "defi", "token"]):
        return "crypto"
    if any(x in lower for x in ["ai", "model", "llm", "openai", "anthropic", "tool"]):
        return "ai"
    return "tech"

def run(user_input):
    lower = user_input.lower().strip()
    if not any(lower.startswith(t) or t in lower for t in TRIGGERS):
        return None

    topic = _pick_topic(lower)

    # Layer 1: real RSS first
    items = _read_rss(RSS.get(topic, RSS["tech"]))
    # Layer 1b: search fallback if RSS dry
    if len(items) < 3:
        items += _search(SEARCH.get(topic, SEARCH["tech"]))
    if not items:
        return "Couldn't gather alpha right now."

    # Layer 2/3: LLM digest if available, else clean formatted feed
    output = _digest(topic, items) or _format(topic, items)

    from core import council
    council.inscribe("alpha", f"{topic}: {output[:200]}", signal_type="intel")
    threading.Thread(target=personality.evolve, args=("alpha", f"{user_input} -> {output[:150]}"), daemon=True).start()
    return output

import os, requests, sys, threading, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import personality
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

NAME        = "Search Brother"
DESCRIPTION = "Multi-source free web/news search, smart ranking, any-LLM summary"
ENABLED     = True
COMMANDS    = ["search <query>", "find <query>", "news <topic>", "what is <topic>"]

TRIGGERS = ["search ", "google ", "find ", "news ", "what is ", "who is ",
            "how to ", "explain ", "tell me about ", "research "]

STOPWORDS = {"the","a","an","of","to","in","on","for","and","or","is","are",
             "what","who","how","why","when","where","tell","me","about","explain"}

def _ddg(query, mode, n=8):
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return list(d.news(query, max_results=n)) if mode=="news" else list(d.text(query, max_results=n))
    except Exception as e:
        print(f"  [search] {mode} failed: {e}")
        return []

def _norm(r):
    return {
        "title": r.get("title",""),
        "body":  r.get("body", r.get("snippet","")),
        "url":   r.get("url", r.get("href","")),
        "date":  r.get("date",""),
    }

def _gather(query):
    """Layer 1 — multi-source, deduped by URL."""
    seen, out = set(), []
    for mode in ("news","text"):
        for r in _ddg(query, mode):
            nr = _norm(r)
            if nr["url"] and nr["url"] not in seen and nr["title"]:
                seen.add(nr["url"]); out.append(nr)
    return out

def _score(query, r):
    """Layer 2 — relevance scoring, no AI. More query words present = higher."""
    terms = [w for w in re.findall(r"\w+", query.lower()) if w not in STOPWORDS]
    text = (r["title"] + " " + r["body"]).lower()
    hits = sum(text.count(t) for t in terms)
    title_hits = sum(r["title"].lower().count(t) for t in terms) * 2  # title matches worth more
    recent = 1 if r["date"] else 0
    return hits + title_hits + recent

def _format(query, results):
    """Layer 2 output — readable, useful with ZERO llm."""
    if not results:
        return "No results found."
    lines = [f"🔎 {query}\n"]
    for r in results[:5]:
        body = r["body"][:180].strip()
        lines.append(f"• {r['title']}\n  {body}\n  {r['url']}")
    return "\n\n".join(lines)

def _summarize(query, results):
    """Layer 3 — any-LLM synthesis on top, via router. Bonus, not required."""
    from core import llm
    context = ""
    for r in results[:6]:
        context += f"- {r['title']}: {r['body'][:200]} ({r['url']})\n"
    prompt = (
        "User asked: " + query + "\n\n"
        "SOURCE RESULTS (the only facts you may use):\n" + context + "\n"
        "Answer directly using only these results. Lead with the answer. "
        "If they don't fully answer it, say what's known and what isn't. "
        "Never invent numbers, dates, or quotes. Cite source URLs. Keep it tight."
    )
    try:
        resp, source = llm.think(prompt)
        if resp and resp.strip():
            return resp.strip() + "\n\n\u2500\u2500 sources above \u2500\u2500"
    except Exception as e:
        print(f"  [search] summary failed: {e}")
    return None

def run(user_input):
    lower = user_input.lower().strip()
    if not any(lower.startswith(t) for t in TRIGGERS):
        return None

    results = _gather(user_input)
    if not results:
        return "No results found."

    # Layer 2: rank without AI
    results.sort(key=lambda r: _score(user_input, r), reverse=True)

    # Layer 3: try LLM summary; fall back to smart-formatted raw if no LLM
    summary = _summarize(user_input, results)
    output = summary if summary else _format(user_input, results)

    from core import council
    council.inscribe("search", f"searched: {user_input} | {output[:150]}", signal_type="intel")
    threading.Thread(target=personality.evolve, args=("search", f"{user_input} -> {output[:150]}"), daemon=True).start()
    return output

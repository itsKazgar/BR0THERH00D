"""
SMART ROUTER — reads natural language, fires the right brother. No LLM needed.
Scores intent by keyword signals, picks the strongest, rewrites to a command.
"""
import re

# Each intent: signal words, the brother, and how to rewrite the input into its command.
INTENTS = [
    {
        "brother": "alpha",
        "signals": ["news", "alpha", "what's happening", "whats happening",
                    "catch me up", "what's new", "whats new", "latest in",
                    "study", "tech news", "ai news", "crypto news", "solana news"],
        "rewrite": lambda t: t,  # alpha reads its own phrasing
    },
    {
        "brother": "crypto",
        "signals": ["price", "worth", "how much", "cost", "sol", "solana", "btc",
                    "bitcoin", "eth", "ethereum", "fear", "greed", "$"],
        "rewrite": lambda t: _crypto_cmd(t),
    },
    {
        "brother": "stocks",
        "signals": ["stock", "stocks", "ticker", "aapl", "tsla", "nvda", "shares",
                    "nasdaq", "s&p", "spy"],
        "rewrite": lambda t: "stock " + _last_word(t),
    },
    {
        "brother": "weather",
        "signals": ["weather", "forecast", "temperature", "raining", "rain", "hot",
                    "cold", "sunny", "snow"],
        "rewrite": lambda t: "weather " + _weather_place(t),
    },
    {
        "brother": "tasks",
        "signals": ["todo", "remind", "remember", "note", "task", "don't forget",
                    "save this", "my tasks", "my todos"],
        "rewrite": lambda t: _task_cmd(t),
    },
    {
        "brother": "portfolio",
        "signals": ["portfolio", "positions", "pnl", "my bag", "holdings", "my stats"],
        "rewrite": lambda t: "portfolio",
    },
    {
        "brother": "reddit",
        "signals": ["reddit", "r/", "subreddit", "wallstreetbets", "wsb"],
        "rewrite": lambda t: "reddit " + _after(t, ["reddit","on","about","r/"]),
    },
    {
        "brother": "hn",
        "signals": ["hacker news", "hackernews", "hn", "show hn", "ask hn", "yc"],
        "rewrite": lambda t: "hn",
    },
    {
        "brother": "scraper",
        "signals": ["scrape", "read this", "read url", "http://", "https://", "this link"],
        "rewrite": lambda t: "scrape " + _find_url(t),
    },
    {
        "brother": "council",
        "signals": ["council", "brotherhood", "the brothers", "ranks", "who are we",
                    "convene", "tome", "status", "spend", "approve", "deny"],
        "rewrite": lambda t: t,  # council handles its own phrasing
    },
    {
        "brother": "search",
        "signals": ["search", "find", "look up", "lookup", "what is", "who is",
                    "news", "latest", "tell me about", "explain", "how to", "research",
                    "what's happening", "google"],
        "rewrite": lambda t: _search_cmd(t),
    },
]

def _last_word(t):
    words = re.findall(r"[A-Za-z]+", t)
    return words[-1].upper() if words else t

def _after(t, markers):
    low = t.lower()
    for m in markers:
        i = low.find(m)
        if i != -1:
            return t[i+len(m):].strip(" ?.:,") or t
    return t

def _find_url(t):
    m = re.search(r"https?://\S+", t)
    return m.group(0) if m else t

def _crypto_cmd(t):
    low = t.lower()
    if "fear" in low or "greed" in low:
        return "fear"
    # map common names to symbols
    names = {"bitcoin":"BTC","btc":"BTC","ethereum":"ETH","eth":"ETH",
             "solana":"SOL","sol":"SOL"}
    for name, sym in names.items():
        if name in low:
            return f"price {sym}"
    return "price " + _last_word(t)

def _task_cmd(t):
    low = t.lower().strip()
    if any(x in low for x in ["my task","my todo","show task","list task","show todo","todos","show my"]):
        return "todos"
    body = _after(t, ["remind me to","remind me","don't forget to","todo","note",
                      "remember to","remember","save this","task"])
    return "todo " + body

def _search_cmd(t):
    body = _after(t, ["search for","search","find me","find","look up","lookup",
                      "tell me about","what is","who is","news about","news on","news",
                      "latest on","latest","research","explain","how to","google"])
    return "search " + body

def _weather_place(t):
    low = t.lower()
    i = low.rfind(" in ")
    if i != -1:
        return t[i+4:].strip(" ?.:,")
    # else last word
    import re as _re
    w = _re.findall(r"[A-Za-z]+", t)
    return w[-1] if w else t

def route(user_input: str):
    """Return (brother_id, rewritten_command) or (None, None) if it's just chat."""
    low = user_input.lower()
    # Explicit search/news verbs override topic-name matches (news on X, find X)
    news_words = ["news", "what's happening", "whats happening", "catch me up", "study ", "latest in"]
    force_alpha = any(w in low for w in news_words)
    search_verbs = ["find me", "find ", "search",
                    "look up", "lookup", "what is", "who is", "latest on",
                    "tell me about", "research", "explain", "how to"]
    force_search = any(v in low for v in search_verbs)

    best, best_score = None, 0
    for intent in INTENTS:
        score = 0
        for sig in intent["signals"]:
            if sig in low:
                score += 2 if " " in sig else 1
        if intent["brother"] == "search" and force_search:
            score += 5
        if intent["brother"] == "alpha" and force_alpha:
            score += 8  # news/study intent beats price
        if score > best_score:
            best, best_score = intent, score
    if not best or best_score == 0:
        return None, None
    try:
        cmd = best["rewrite"](user_input)
    except Exception:
        cmd = user_input
    return best["brother"], cmd

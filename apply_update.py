#!/usr/bin/env python3
def patch(path, replacements, label):
    s = open(path, encoding="utf-8").read()
    for old, new in replacements:
        if old not in s:
            print(f"  [SKIP] {label}: pattern not found, may already be applied:\n    {old[:80]!r}")
            continue
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)
    print(f"[OK] {label} patched")

patch("brotha_api.py", [
    (
        "        row = brain_db.execute(\"SELECT data FROM state WHERE agent='trader'\").fetchone()",
        "        _live2 = os.getenv('TRADE_MODE','paper').lower() == 'live'\n"
        "        _key2  = 'trader_live' if _live2 else 'trader_paper'\n"
        "        row = brain_db.execute(\"SELECT data FROM state WHERE agent=?\", (_key2,)).fetchone()"
    ),
], "brotha_api.py")

with open("paper_trader.py", encoding="utf-8") as f:
    content = f.read()
if content.endswith("\n\n"):
    content = content[:-1]
    with open("paper_trader.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] paper_trader.py patched (removed trailing blank line)")
else:
    print("[SKIP] paper_trader.py: already clean")

patch("agents/trading/scanner.py", [
    ('SCAN_INTERVAL = 45   # seconds', 'SCAN_INTERVAL = 30   # seconds'),
    ('MIN_LIQ       = 25_000', 'MIN_LIQ       = 15_000'),
    ('MIN_VOL_24H   = 50_000', 'MIN_VOL_24H   = 20_000'),
    ('MIN_TXNS_1H   = 50', 'MIN_TXNS_1H   = 30'),
    ('if d["age_hrs"] < 0.5:  return "too fresh — under 30mins"',
     'if d["age_hrs"] < 0.25: return "too fresh — under 15mins"'),
    ('if accel > 5:    s += 12; r.append(f"⚡ vol x{accel:.0f} spike")',
     'if accel > 5:    s += 18; r.append(f"⚡ vol x{accel:.0f} spike")'),
    ('if 3 <= c5 <= 20:    s += 20; r.append(f"🟢 {c5:+.1f}% 5m surge")',
     'if 3 <= c5 <= 30:    s += 25; r.append(f"🟢 {c5:+.1f}% 5m surge")'),
    ('elif 25 < c <= 40:   s -=  5; r.append(f"⚠️ {c:+.1f}% late entry")',
     'elif 25 < c <= 40:   s -= 15; r.append(f"⚠️ {c:+.1f}% late entry")'),
    ('uptrend_1h     = d["change_1h"] >= 5    # meaningful positive 1h',
     'uptrend_1h     = d["change_1h"] >= 3    # meaningful positive 1h'),
    ('buyers_winning = buy_ratio > 0.62       # clear majority buying',
     'buyers_winning = buy_ratio > 0.60       # clear majority buying'),
    ('if s >= 75 and uptrend_1h and buyers_winning and uptrend_24h:',
     'if s >= 80 and uptrend_1h and buyers_winning and uptrend_24h:'),
    ('buys   = [x for x in results if x["score"] >= 75]',
     'buys   = [x for x in results if x["score"] >= 80]'),
    ('watches= [x for x in results if 60 <= x["score"] < 75]',
     'watches= [x for x in results if 65 <= x["score"] < 80]'),
], "agents/trading/scanner.py")

patch("agents/trading/trader.py", [
    ('# score 75-84  → 6% of balance', '# score 80-84  → 6% of balance'),
    ('MAX_POSITIONS    = 3', 'MAX_POSITIONS    = 4'),
    ('MIN_SCORE        = 75', 'MIN_SCORE        = 80'),
    ('STOP_LOSS_PCT    = 0.06       # base SL -6%', 'STOP_LOSS_PCT    = 0.08       # base SL -8%'),
    ('MAX_HOLD_MINS    = 45', 'MAX_HOLD_MINS    = 30'),
    ('acted_on   = {}  # mint -> expiry timestamp\n',
     'acted_on   = {}  # mint -> expiry timestamp (1h TTL)\n'),
    ('if len(self.positions) == 2 and score < 85:',
     'if len(self.positions) == 3 and score < 85:'),
    ('3rd slot reserved for 85+ score, skipping {name} ({score})',
     '4th slot reserved for 85+ score, skipping {name} ({score})'),
    ('"tokens":     tokens,\n',
     '"tokens":     tokens,\n            "tokens_orig": tokens,\n            "size_usd_orig": size_usd,\n'),
    ('pnl_usd = (price - pos["entry"]) / pos["entry"] * pos["size_usd"]',
     '_t = pos.get("tokens", pos["size_usd"] / max(pos["entry"], 1e-12))\n'
     '        pnl_usd = (price - pos["entry"]) * _t'),
    ('if change_5m < -4:', 'if change_5m < -3:'),
    ('if buy_ratio < 0.45:', 'if buy_ratio < 0.48:'),
    ('pos["tokens"]    = round(tokens * 0.67, 10)',
     'pos["tokens"]    = round(pos["tokens_orig"] * 0.67, 10)\n'
     '                pos["size_usd"]  = round(pos["size_usd"] * 0.67, 4)'),
    ('sell_tokens = tokens * 0.33',
     'sell_tokens = pos.get("tokens_orig", tokens) * 0.33'),
    ('pos["tokens"]    = round(tokens * 0.34, 10)',
     'pos["tokens"]    = round(pos["tokens_orig"] * 0.34, 10)\n'
     '                pos["size_usd"]  = round(pos.get("size_usd_orig", pos["size_usd"] / 0.67) * 0.34, 4)'),
    ('if mint in self.positions or mint in acted_on:',
     'if mint in self.positions or acted_on.get(mint, 0) > time.time():'),
], "agents/trading/trader.py")

print("\nDone patching.")

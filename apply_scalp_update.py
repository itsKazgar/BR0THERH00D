#!/usr/bin/env python3
def patch(path, replacements, label):
    s = open(path, encoding="utf-8").read()
    for old, new in replacements:
        if old not in s:
            print(f"  [SKIP] {label}: pattern not found, may already be applied")
            continue
        s = s.replace(old, new)
    open(path, "w", encoding="utf-8").write(s)
    print(f"[OK] {label} patched")

patch("agents/trading/trader.py", [
    ('''        age = coin.get("age_hrs", 99)
        if age < 4:
            tp       = round(price * 1.15, 10)
            sl       = round(price * 0.90, 10)
            hold_cap = 20
            mode_tag = "⚡ SCALP"''',
     '''        age = coin.get("age_hrs", 99)
        liq = coin.get("liquidity", 0)
        if age < 4:
            if liq < 25_000:
                print(f"  [trader] ⚠️  {name} too thin for scalp (liq=${liq:,.0f}) — skipping")
                acted_on[mint] = time.time() + 3600
                return
            tp       = round(price * 1.15, 10)
            sl       = round(price * 0.94, 10)
            hold_cap = 20
            mode_tag = "⚡ SCALP"'''),

    ('''            buy_ratio = buys / max(1, buys + sells)

            # Track peak for trailing stop''',
     '''            buy_ratio = buys / max(1, buys + sells)

            # ── Early-loss cutoff — cut fast-fading scalps before SL ──
            if held_mins <= 3 and pnl_pct <= -4 and change_5m < -3:
                cooldown[mint] = {"ts": time.time(), "mins": COOLDOWN_STOP}
                self.sell(mint, f"early cut {pnl_pct:+.1f}% [5m red {change_5m:+.1f}%]")
                continue

            # Track peak for trailing stop'''),
], "agents/trading/trader.py")

print("\nDone patching.")

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
    ('''            if pnl_pct >= 10:
                new_sl = price * 0.97        # trail 3% below current at +10%
            elif pnl_pct >= 6:
                new_sl = price * 0.955       # trail 4.5% below current at +6%
            elif pnl_pct >= 3:
                new_sl = pos["entry"] * 1.01 # lock breakeven+1% at +3%
            elif pnl_pct >= 2:
                new_sl = pos["entry"] * 1.005 # tiny lock at +2%
            else:
                new_sl = pos["sl"]''',
     '''            if pnl_pct >= 8:
                new_sl = price * 0.98        # trail 2% below current at +8%
            elif pnl_pct >= 5:
                new_sl = price * 0.965       # trail 3.5% below current at +5%
            elif pnl_pct >= 3:
                new_sl = pos["entry"] * 1.01 # lock breakeven+1% at +3%
            elif pnl_pct >= 1.5:
                new_sl = pos["entry"] * 1.005 # tiny lock at +1.5%
            else:
                new_sl = pos["sl"]'''),

    ('''            t1_price = round(entry * 1.10, 10)   # sell 33% at +10%
            t2_price = round(entry * 1.22, 10)   # sell 33% at +22%''',
     '''            t1_price = round(entry * 1.05, 10)   # sell 40% at +5%
            t2_price = round(entry * 1.12, 10)   # sell 40% at +12%'''),

    ('''            if not pos.get("tier1_hit") and price >= t1_price:
                sell_tokens = tokens * 0.33
                sell_value  = sell_tokens * price
                pnl_slice   = sell_value - (sell_tokens * entry)
                self.balance    += sell_value
                self.total_pnl  += pnl_slice
                pos["tier1_hit"] = True
                pos["tokens"]    = round(pos["tokens_orig"] * 0.67, 10)
                pos["size_usd"]  = round(pos["size_usd"] * 0.67, 4)
                pos["sl"]        = round(entry * 1.01, 10)
                self._save()
                print(f"  [trader] 💰 T1 {pos['name']} sold 33% @ ${price:.8f} (+10%) "
                      f"| +${pnl_slice:.2f} | stop → breakeven+1%")
                continue''',
     '''            if not pos.get("tier1_hit") and price >= t1_price:
                sell_tokens = tokens * 0.40
                sell_value  = sell_tokens * price
                pnl_slice   = sell_value - (sell_tokens * entry)
                self.balance    += sell_value
                self.total_pnl  += pnl_slice
                pos["tier1_hit"] = True
                pos["tokens"]    = round(pos["tokens_orig"] * 0.60, 10)
                pos["size_usd"]  = round(pos["size_usd"] * 0.60, 4)
                pos["sl"]        = round(entry * 1.01, 10)
                self._save()
                print(f"  [trader] 💰 T1 {pos['name']} sold 40% @ ${price:.8f} (+5%) "
                      f"| +${pnl_slice:.2f} | stop → breakeven+1%")
                continue'''),

    ('''            if pos.get("tier1_hit") and not pos.get("tier2_hit") and price >= t2_price:
                sell_tokens = pos.get("tokens_orig", tokens) * 0.33
                sell_value  = sell_tokens * price
                pnl_slice   = sell_value - (sell_tokens * entry)
                self.balance    += sell_value
                self.total_pnl  += pnl_slice
                pos["tier2_hit"] = True
                pos["tokens"]    = round(pos["tokens_orig"] * 0.34, 10)
                pos["size_usd"]  = round(pos.get("size_usd_orig", pos["size_usd"] / 0.67) * 0.34, 4)
                pos["sl"]        = round(price * 0.94, 10)
                self._save()
                print(f"  [trader] 💰 T2 {pos['name']} sold 33% @ ${price:.8f} (+22%) "
                      f"| +${pnl_slice:.2f} | trailing last 33%")
                continue''',
     '''            if pos.get("tier1_hit") and not pos.get("tier2_hit") and price >= t2_price:
                sell_tokens = pos.get("tokens_orig", tokens) * 0.40
                sell_value  = sell_tokens * price
                pnl_slice   = sell_value - (sell_tokens * entry)
                self.balance    += sell_value
                self.total_pnl  += pnl_slice
                pos["tier2_hit"] = True
                pos["tokens"]    = round(pos["tokens_orig"] * 0.20, 10)
                pos["size_usd"]  = round(pos.get("size_usd_orig", pos["size_usd"] / 0.60) * 0.20, 4)
                pos["sl"]        = round(price * 0.97, 10)
                self._save()
                print(f"  [trader] 💰 T2 {pos['name']} sold 40% @ ${price:.8f} (+12%) "
                      f"| +${pnl_slice:.2f} | trailing last 20% tight")
                continue'''),
], "agents/trading/trader.py")

print("\nDone patching.")

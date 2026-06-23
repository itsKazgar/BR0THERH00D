#!/usr/bin/env python3
"""
Emergency sell all open positions
Usage: python sellall.py
"""
import os, sys, requests
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
from core import brain

GR='\033[92m'; RD='\033[91m'; YL='\033[93m'; CY='\033[96m'; BD='\033[1m'; RS='\033[0m'

def get_price(mint):
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=8)
        pairs = [p for p in r.json().get("pairs", []) if p.get("chainId") == "solana"]
        if not pairs:
            return None
        best = sorted(pairs, key=lambda x: float(x.get("liquidity",{}).get("usd",0) or 0), reverse=True)[0]
        return float(best.get("priceUsd", 0) or 0) or None
    except:
        return None

brain.init_db()
state    = brain.load_state("trader_paper" if os.getenv("TRADE_MODE","paper").lower() != "live" else "trader_live")
positions = state.get("positions", {})
balance   = state.get("balance", 0)
mode      = "LIVE" if os.getenv("TRADE_MODE","paper").lower() == "live" else "PAPER"

print(f"""
{CY}{BD}╔══════════════════════════════════════════════════════╗
║   🚨  BR0THERH00D — Sell All Positions              ║
╚══════════════════════════════════════════════════════╝{RS}

  Mode     : {f"{RD}{BD}LIVE{RS}" if mode == "LIVE" else f"{GR}PAPER{RS}"}
  Balance  : ${balance:.2f}
  Positions: {len(positions)}
""")

if not positions:
    print(f"  {GR}No open positions.{RS}\n")
    sys.exit(0)

total_pnl = 0
for mint, pos in positions.items():
    price = get_price(mint)
    if price:
        pnl_pct = (price - pos["entry"]) / pos["entry"] * 100
        pnl_usd = (price - pos["entry"]) / pos["entry"] * pos["size_usd"]
        color   = GR if pnl_usd >= 0 else RD
        print(f"  {color}{pos['name']:<12}{RS} entry=${pos['entry']:.8f}  now=${price:.8f}  {color}{pnl_pct:+.1f}%  ${pnl_usd:+.2f}{RS}")
        total_pnl += pnl_usd
    else:
        print(f"  {YL}{pos['name']:<12}{RS} entry=${pos['entry']:.8f}  price unavailable")

pnl_color = GR if total_pnl >= 0 else RD
print(f"\n  Total PnL if sold now: {pnl_color}{BD}${total_pnl:+.2f}{RS}")
print(f"\n  {RD}This will close ALL {len(positions)} position(s).{RS}")

confirm = input("  Confirm sell all? (yes/n): ").strip().lower()
if confirm != "yes":
    print(f"  {YL}Cancelled.{RS}\n")
    sys.exit(0)

# LIVE mode — actually sell every position on-chain (token -> SOL), sign +
# confirm each, and only remove a position from the tracker once its sale is
# confirmed. Real money moves here.
if mode == "LIVE":
    from core import jupiter
    kp = jupiter.load_keypair()
    if not kp:
        print(f"  {RD}No WALLET_PRIVATE_KEY in .env — cannot sell live.{RS}\n")
        sys.exit(1)
    sold = 0
    for mint, pos in list(positions.items()):
        name = pos.get("name", mint[:8])
        print(f"  {YL}selling {name}…{RS}")
        r = jupiter.sell_token(kp, mint, fraction=1.0)   # sell the full on-chain balance
        if r["success"]:
            sold += 1
            del positions[mint]
            brain.remember("trader",
                f"LIVE SELLALL {name} | got {r['sol_received']:.4f} SOL | tx={r['tx']}",
                type="trade", tags=f"{name.lower()},sell,live")
            print(f"  {GR}✅ sold {name}{RS} — +{r['sol_received']:.4f} SOL  "
                  f"https://solscan.io/tx/{r['tx']}")
        else:
            print(f"  {RD}❌ {name} NOT sold — {r['error']} (kept open){RS}")
    state["positions"] = positions   # keep any that failed
    brain.save_state("trader_live", state)
    print(f"\n  {GR}{BD}✅ {sold}/{len(positions)+sold} live position(s) sold.{RS}\n")
    sys.exit(0)

# PAPER mode only — simulated close against the local tracker.
new_balance = balance
closed = 0
for mint, pos in list(positions.items()):
    price = get_price(mint)
    if not price:
        print(f"  {RD}❌ {pos['name']} — could not get price, skipping (kept open){RS}")
        continue
    entry = pos.get("entry", 0) or 0
    pnl_usd = ((price - entry) / entry * pos.get("size_usd", 0)) if entry else 0.0
    new_balance += pos.get("size_usd", 0) + pnl_usd
    brain.remember("trader",
        f"PAPER SELLALL {pos.get('name','?')} @ ${price:.8f} | PnL=${pnl_usd:+.2f}",
        type="trade", tags=f"{pos.get('name','').lower()},sell,paper")
    print(f"  {GR}✅ Closed (paper) {pos.get('name','?')}{RS}  PnL=${pnl_usd:+.2f}")
    del positions[mint]   # only remove the ones actually closed
    closed += 1

state["positions"] = positions   # keep any that were skipped
state["balance"]   = round(new_balance, 4)
state["total_pnl"] = round(state.get("total_pnl", 0) + total_pnl, 4)
brain.save_state("trader_paper", state)

print(f"""
  {GR}{BD}✅ {closed} paper position(s) closed{RS}
  New paper balance: ${new_balance:.2f}
""")

"""
PUMP BROTHER — live pump.fun launches via PumpPortal free WebSocket stream.
Connects, listens a few seconds, catches tokens launching RIGHT NOW, disconnects.
HONEST: this is a firehose of brand-new tokens. Most are noise or rugs.
Shows what's LAUNCHING, never what's worth buying. Not financial advice.
"""
import os, sys, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import personality

NAME        = "Pump Brother"
DESCRIPTION = "Live pump.fun launches via free PumpPortal stream. Raw activity, not buy signals."
ENABLED     = True
COMMANDS    = ["pump", "pump new", "whats launching", "new launches"]

TRIGGERS = ["pump", "whats launching", "what's launching", "new launches",
            "launching on solana", "new tokens", "pumpfun", "pump fun"]

WS_URL = "wss://pumpportal.fun/api/data"

def _listen(seconds=8, max_tokens=10):
    """Connect, subscribe to new tokens, collect for N seconds, return them."""
    import websocket
    caught = []
    done = threading.Event()

    def on_open(ws):
        ws.send(json.dumps({"method": "subscribeNewToken"}))

    def on_message(ws, message):
        try:
            data = json.loads(message)
            # token creation events carry name/symbol/mint
            mint = data.get("mint", "")
            if (data.get("mint") or data.get("symbol") or data.get("name")) and \
               mint not in [c.get("mint") for c in caught]:
                caught.append({
                    "symbol": (data.get("symbol") or "?").upper(),
                    "name":   (data.get("name") or "")[:30],
                    "mint":   data.get("mint", ""),
                    "mc":     data.get("marketCapSol", 0),
                })
                if len(caught) >= max_tokens:
                    done.set()
                    ws.close()
        except Exception:
            pass

    def on_error(ws, err):
        done.set()

    try:
        ws = websocket.WebSocketApp(WS_URL,
            on_open=on_open, on_message=on_message, on_error=on_error)
        t = threading.Thread(target=ws.run_forever, daemon=True)
        t.start()
        done.wait(timeout=seconds)   # listen window
        try:
            ws.close()
        except Exception:
            pass
    except Exception as e:
        print(f"  [pump] stream failed: {e}")
    return caught

def _format(coins):
    if not coins:
        return None
    lines = ["\U0001F680 PUMP.FUN \u2014 LAUNCHING RIGHT NOW\n"]
    for c in coins[:10]:
        sym  = c.get("symbol", "?") or "?"
        name = c.get("name", "") or ""
        mc   = c.get("mc", 0)
        mc_s = f"{mc:.1f} SOL" if mc else "new"
        lines.append(f"\u2022 {sym:10} {name:30} {mc_s}")
    lines.append("\n\u26a0\ufe0f  Raw live launches \u2014 mostly noise/risky. NOT buy signals. DYOR.")
    return "\n".join(lines)

def run(user_input):
    lower = user_input.lower().strip()
    if not any(lower.startswith(t) or t in lower for t in TRIGGERS):
        return None

    coins = _listen(seconds=8)
    out = _format(coins)
    if not out:
        return "No launches caught in the listen window (or stream unreachable). Try again."

    from core import council
    council.inscribe("pump", f"live launches: {out[:150]}", signal_type="intel")
    threading.Thread(target=personality.evolve, args=("pump", f"{user_input}"), daemon=True).start()
    return out

import os, requests, sys
from dotenv import load_dotenv
load_dotenv()

WALLET = os.getenv("WALLET_ADDRESS")
RPC = "https://api.mainnet-beta.solana.com"

if not WALLET:
    print("❌ WALLET_ADDRESS not set in .env — nothing to look up.")
    print("   Run setup.py to generate or import a wallet first.")
    sys.exit(1)

# Real SOL balance
try:
    r = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":"getBalance","params":[WALLET]}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "result" not in data:
        print(f"❌ Solana RPC error: {data.get('error', data)}")
        sys.exit(1)
    sol = data["result"]["value"] / 1e9
except requests.exceptions.RequestException as e:
    print(f"❌ Couldn't reach Solana RPC: {e}")
    sys.exit(1)
except (ValueError, KeyError) as e:
    print(f"❌ Unexpected response from Solana RPC: {e}")
    sys.exit(1)

try:
    price_r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5)
    price_r.raise_for_status()
    sol_price = float(price_r.json()["solana"]["usd"])
except Exception as e:
    print(f"⚠️  Couldn't fetch SOL price ({e}) — showing balance only")
    sol_price = 0

print(f"\n💰 REAL WALLET: {WALLET}")
print(f"   SOL: {sol:.4f} (${sol * sol_price:.2f})")

# All tokens
try:
    r2 = requests.post(RPC, json={"jsonrpc":"2.0","id":1,"method":"getTokenAccountsByOwner","params":[WALLET,{"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},{"encoding":"jsonParsed"}]}, timeout=10)
    r2.raise_for_status()
    data2 = r2.json()
    tokens = data2.get("result", {}).get("value", [])
except requests.exceptions.RequestException as e:
    print(f"⚠️  Couldn't fetch token accounts: {e}")
    tokens = []

if tokens:
    print(f"\n🪙 TOKENS:")
    for t in tokens:
        info = t["account"]["data"]["parsed"]["info"]
        amt = info["tokenAmount"]["uiAmount"]
        if amt and float(amt) > 0:
            print(f"   Mint: {info['mint']}  Amount: {amt}")
else:
    print("   No tokens found")

import os, signal, atexit, logging
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logger = logging.getLogger(__name__)

_positions_registry = {}

def register_position(mint: str, amount: float, wallet: str = None):
    _positions_registry[mint] = {
        "amount": amount,
        "wallet": wallet or os.getenv("WALLET_ADDRESS", "")
    }

def deregister_position(mint: str):
    _positions_registry.pop(mint, None)

def emergency_sell_all():
    if not _positions_registry:
        logger.info("[EMERGENCY] No open positions to sell.")
        return

    logger.critical(f"[EMERGENCY] Selling {len(_positions_registry)} open positions before shutdown!")

    # Real kill switch: sign + confirm an on-chain token->SOL sell for every
    # registered position. Only deregister once the sale confirms, so a failed
    # sell stays flagged instead of being silently "lost".
    try:
        from core import jupiter
        kp = jupiter.load_keypair()
        if not kp:
            logger.critical("[EMERGENCY] No WALLET_PRIVATE_KEY — cannot sell. Exit positions manually NOW.")
            return
        for mint, pos in list(_positions_registry.items()):
            try:
                r = jupiter.sell_token(kp, mint, fraction=1.0)  # dump the full balance
                if r["success"]:
                    deregister_position(mint)
                    logger.critical(f"[EMERGENCY] SOLD {mint} — +{r['sol_received']:.4f} SOL tx={r['tx']}")
                else:
                    logger.critical(f"[EMERGENCY] ⚠ {mint} NOT sold: {r['error']} — sell manually NOW.")
            except Exception as e:
                logger.error(f"[EMERGENCY] Failed selling {mint}: {e}")
    except Exception as e:
        logger.critical(f"[EMERGENCY] Sell-all failed: {e}")

def _handle_signal(sig, frame):
    logger.critical(f"[EMERGENCY] Signal {sig} — triggering sell-all")
    emergency_sell_all()
    os._exit(0)

def install_emergency_handler():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)
    atexit.register(emergency_sell_all)
    logger.info("[EMERGENCY] Kill switch armed ✅")

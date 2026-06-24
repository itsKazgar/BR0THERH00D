import os, requests, time, logging, re
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)

logger = logging.getLogger(__name__)

def _ram():
    try:
        with open("/proc/meminfo") as f:
            for l in f:
                if l.startswith("MemTotal"):
                    return int(l.split()[1]) / 1024 / 1024
    except: pass
    return 2.0

RAM_GB = _ram()

def _key_env(name):
    mapping = {
        "groq":        "GROQ_API_KEY",
        "cerebras":    "CEREBRAS_API_KEY",
        "openrouter":  "OPENROUTER_API_KEY",
        "openai":      "OPENAI_API_KEY",
        "anthropic":   "ANTHROPIC_API_KEY",
        "grok":        "XAI_API_KEY",
        "gemini":      "GEMINI_API_KEY",
        "mistral":     "MISTRAL_API_KEY",
        "deepseek":    "DEEPSEEK_API_KEY",
        "perplexity":  "PERPLEXITY_API_KEY",
        "cohere":      "COHERE_API_KEY",
        "fireworks":   "FIREWORKS_API_KEY",
        "together":    "TOGETHER_API_KEY",
        "cloudflare":  "CF_API_TOKEN + CF_ACCOUNT_ID",
        "hf":          "HF_API_KEY",
        "ollama":      "(none — local)",
    }
    for prefix, env in mapping.items():
        if name.startswith(prefix):
            return env
    return "API_KEY"

# =============================================================================
# PROVIDER REGISTRY
# Only GROQ + CEREBRAS are required. Everything else is optional.
# Add a key to .env to unlock that provider. Missing keys = silently skipped.
# =============================================================================

PROVIDERS = {

    # ── GROQ (free, required) ─────────────────────────────────────────────────
    "groq_llama70b": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "llama-3.3-70b-versatile",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_llama8b": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "llama-3.1-8b-instant",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_llama4": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "meta-llama/llama-4-scout-17b-16e-instruct",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_qwen32b": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "qwen/qwen3-32b",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_compound": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "compound-beta",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_compound_mini": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "compound-beta-mini",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_gpt120b": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "openai/gpt-oss-120b",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "groq_gpt20b": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "key":    os.getenv("GROQ_API_KEY", ""),
        "model":  "openai/gpt-oss-20b",
        "format": "openai", "free": True, "min_ram": 0,
    },

    # ── CEREBRAS (free, required) ─────────────────────────────────────────────
    "cerebras_large": {
        "url":    "https://api.cerebras.ai/v1/chat/completions",
        "key":    os.getenv("CEREBRAS_API_KEY", ""),
        "model":  "gpt-oss-120b",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "cerebras_small": {
        "url":    "https://api.cerebras.ai/v1/chat/completions",
        "key":    os.getenv("CEREBRAS_API_KEY", ""),
        "model":  "zai-glm-4.7",
        "format": "openai", "free": True, "min_ram": 0,
    },

    # ── OPTIONAL — OpenRouter ─────────────────────────────────────────────────
    "openrouter_llama": {
        "url":    "https://openrouter.ai/api/v1/chat/completions",
        "key":    os.getenv("OPENROUTER_API_KEY", ""),
        "model":  "meta-llama/llama-3.1-8b-instruct:free",
        "format": "openai", "free": True, "min_ram": 0,
        "headers": {"HTTP-Referer": "https://t.me/BR0THERH00D", "X-Title": "BR0THERH00D"},
    },
    "openrouter_deepseek": {
        "url":    "https://openrouter.ai/api/v1/chat/completions",
        "key":    os.getenv("OPENROUTER_API_KEY", ""),
        "model":  "deepseek/deepseek-r1:free",
        "format": "openai", "free": True, "min_ram": 0,
        "headers": {"HTTP-Referer": "https://t.me/BR0THERH00D", "X-Title": "BR0THERH00D"},
    },
    "openrouter_gemma": {
        "url":    "https://openrouter.ai/api/v1/chat/completions",
        "key":    os.getenv("OPENROUTER_API_KEY", ""),
        "model":  "google/gemma-3-12b-it:free",
        "format": "openai", "free": True, "min_ram": 0,
        "headers": {"HTTP-Referer": "https://t.me/BR0THERH00D", "X-Title": "BR0THERH00D"},
    },
    "openrouter_qwen": {
        "url":    "https://openrouter.ai/api/v1/chat/completions",
        "key":    os.getenv("OPENROUTER_API_KEY", ""),
        "model":  "qwen/qwen3-8b:free",
        "format": "openai", "free": True, "min_ram": 0,
        "headers": {"HTTP-Referer": "https://t.me/BR0THERH00D", "X-Title": "BR0THERH00D"},
    },

    # ── OPTIONAL — Together AI ────────────────────────────────────────────────
    "together_llama": {
        "url":    "https://api.together.xyz/v1/chat/completions",
        "key":    os.getenv("TOGETHER_API_KEY", ""),
        "model":  "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
        "format": "openai", "free": True, "min_ram": 0,
    },

    # ── OPTIONAL — Mistral ────────────────────────────────────────────────────
    "mistral_free": {
        "url":    "https://api.mistral.ai/v1/chat/completions",
        "key":    os.getenv("MISTRAL_API_KEY", ""),
        "model":  "mistral-small-latest",
        "format": "openai", "free": True, "min_ram": 0,
    },
    "mistral_large": {
        "url":    "https://api.mistral.ai/v1/chat/completions",
        "key":    os.getenv("MISTRAL_API_KEY", ""),
        "model":  "mistral-large-latest",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — Cohere ─────────────────────────────────────────────────────
    "cohere_free": {
        "url":    "https://api.cohere.ai/v2/chat",
        "key":    os.getenv("COHERE_API_KEY", ""),
        "model":  "command-r-plus-08-2024",
        "format": "cohere", "free": True, "min_ram": 0,
    },

    # ── OPTIONAL — Hugging Face ───────────────────────────────────────────────
    "hf_llama": {
        "url":    "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct/v1/chat/completions",
        "key":    os.getenv("HF_API_KEY", ""),
        "model":  "meta-llama/Meta-Llama-3-8B-Instruct",
        "format": "openai", "free": True, "min_ram": 0,
    },

    # ── OPTIONAL — Cloudflare Workers AI ─────────────────────────────────────
    "cloudflare_llama": {
        "url":    f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CF_ACCOUNT_ID','UNSET')}/ai/v1/chat/completions",
        "key":    os.getenv("CF_API_TOKEN", ""),
        "model":  "@cf/meta/llama-3.1-8b-instruct",
        "format": "openai", "free": True, "min_ram": 0,
    },

    # ── OPTIONAL — Anthropic Claude ───────────────────────────────────────────
    "anthropic_sonnet": {
        "url":    "https://api.anthropic.com/v1/messages",
        "key":    os.getenv("ANTHROPIC_API_KEY", ""),
        "model":  "claude-sonnet-4-5-20250514",
        "format": "anthropic", "free": False, "min_ram": 0,
    },
    "anthropic_haiku": {
        "url":    "https://api.anthropic.com/v1/messages",
        "key":    os.getenv("ANTHROPIC_API_KEY", ""),
        "model":  "claude-haiku-4-5-20251001",
        "format": "anthropic", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — OpenAI ─────────────────────────────────────────────────────
    "openai_gpt4o": {
        "url":    "https://api.openai.com/v1/chat/completions",
        "key":    os.getenv("OPENAI_API_KEY", ""),
        "model":  "gpt-4o",
        "format": "openai", "free": False, "min_ram": 0,
    },
    "openai_gpt4o_mini": {
        "url":    "https://api.openai.com/v1/chat/completions",
        "key":    os.getenv("OPENAI_API_KEY", ""),
        "model":  "gpt-4o-mini",
        "format": "openai", "free": False, "min_ram": 0,
    },
    "openai_o3": {
        "url":    "https://api.openai.com/v1/chat/completions",
        "key":    os.getenv("OPENAI_API_KEY", ""),
        "model":  "o3",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — xAI Grok ───────────────────────────────────────────────────
    "grok_2": {
        "url":    "https://api.x.ai/v1/chat/completions",
        "key":    os.getenv("XAI_API_KEY", ""),
        "model":  "grok-2-latest",
        "format": "openai", "free": False, "min_ram": 0,
    },
    "grok_3_mini": {
        "url":    "https://api.x.ai/v1/chat/completions",
        "key":    os.getenv("XAI_API_KEY", ""),
        "model":  "grok-3-mini-latest",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — Google Gemini ──────────────────────────────────────────────
    "gemini_flash": {
        "url":    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key":    os.getenv("GEMINI_API_KEY", ""),
        "model":  "gemini-2.0-flash",
        "format": "openai", "free": False, "min_ram": 0,
    },
    "gemini_pro": {
        "url":    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key":    os.getenv("GEMINI_API_KEY", ""),
        "model":  "gemini-2.5-pro-preview-05-06",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — DeepSeek direct ────────────────────────────────────────────
    "deepseek_chat": {
        "url":    "https://api.deepseek.com/v1/chat/completions",
        "key":    os.getenv("DEEPSEEK_API_KEY", ""),
        "model":  "deepseek-chat",
        "format": "openai", "free": False, "min_ram": 0,
    },
    "deepseek_r1": {
        "url":    "https://api.deepseek.com/v1/chat/completions",
        "key":    os.getenv("DEEPSEEK_API_KEY", ""),
        "model":  "deepseek-reasoner",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — Perplexity ─────────────────────────────────────────────────
    "perplexity_online": {
        "url":    "https://api.perplexity.ai/chat/completions",
        "key":    os.getenv("PERPLEXITY_API_KEY", ""),
        "model":  "sonar-pro",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — Fireworks AI ───────────────────────────────────────────────
    "fireworks_llama": {
        "url":    "https://api.fireworks.ai/inference/v1/chat/completions",
        "key":    os.getenv("FIREWORKS_API_KEY", ""),
        "model":  "accounts/fireworks/models/llama-v3p1-70b-instruct",
        "format": "openai", "free": False, "min_ram": 0,
    },

    # ── OPTIONAL — Local Ollama (auto-unlocks with RAM) ───────────────────────
    "ollama_llama3_70b":  {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "llama3:70b",       "format": "openai", "free": True, "min_ram": 48},
    "ollama_llama3_8b":   {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "llama3.1:8b",      "format": "openai", "free": True, "min_ram": 10},
    "ollama_deepseek_7b": {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "deepseek-r1:7b",   "format": "openai", "free": True, "min_ram": 10},
    "ollama_mistral_7b":  {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "mistral:7b",       "format": "openai", "free": True, "min_ram": 10},
    "ollama_qwen_7b":     {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "qwen2.5:7b",       "format": "openai", "free": True, "min_ram": 10},
    "ollama_llama3_3b":   {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "llama3.2:3b",      "format": "openai", "free": True, "min_ram": 6},
    "ollama_deepseek_1b": {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "deepseek-r1:1.5b", "format": "openai", "free": True, "min_ram": 4},
    "ollama_phi3_mini":   {"url": "http://localhost:11434/v1/chat/completions", "key": "ollama", "model": "phi3:mini",        "format": "openai", "free": True, "min_ram": 4},
}

# =============================================================================
# AGENT → PROVIDER PRIORITY LISTS
# Groq + Cerebras first (always available). Optional providers slot in after.
# Missing keys are skipped silently — no crashes, no required extras.
# =============================================================================

AGENT_PROVIDERS = {
    "default":      ["groq_llama70b",    "groq_llama4",       "cerebras_large",    "groq_qwen32b",      "groq_compound",     "openrouter_deepseek","anthropic_sonnet",  "openai_gpt4o",      "mistral_large",     "ollama_llama3_8b"],
    "orchestrator": ["cerebras_large",   "groq_llama70b",     "groq_llama4",       "groq_qwen32b",      "groq_compound",     "anthropic_sonnet",   "openai_gpt4o",      "mistral_large",     "openrouter_deepseek","ollama_llama3_8b"],
    "analyst":      ["groq_qwen32b",     "groq_gpt120b",      "cerebras_large",    "groq_llama70b",     "deepseek_r1",       "openrouter_deepseek","openai_gpt4o",      "anthropic_sonnet",  "groq_compound",     "ollama_deepseek_7b"],
    "intel":        ["groq_llama8b",     "groq_compound_mini","cerebras_small",    "groq_llama4",       "grok_3_mini",       "perplexity_online",  "gemini_flash",      "openrouter_llama",  "groq_gpt20b",       "ollama_llama3_3b"],
    "trader":       ["cerebras_small",   "groq_llama8b",      "groq_compound_mini","groq_gpt20b",       "openrouter_llama",  "mistral_free",       "cohere_free",       "together_llama",    "hf_llama",          "ollama_phi3_mini"],
    "risk":         ["cerebras_large",   "groq_llama70b",     "groq_qwen32b",      "groq_gpt120b",      "deepseek_r1",       "openai_o3",          "anthropic_sonnet",  "openrouter_deepseek","groq_compound",    "ollama_deepseek_7b"],
    "coder":        ["groq_qwen32b",     "groq_gpt120b",      "cerebras_large",    "groq_llama4",       "deepseek_r1",       "deepseek_chat",      "openai_gpt4o",      "anthropic_sonnet",  "openrouter_deepseek","ollama_deepseek_7b"],
    "research":     ["groq_llama70b",    "groq_compound",     "cerebras_large",    "groq_llama4",       "groq_qwen32b",      "anthropic_sonnet",   "openai_gpt4o",      "openrouter_gemma",  "mistral_large",     "ollama_llama3_8b"],
    "security":     ["cerebras_large",   "groq_qwen32b",      "groq_gpt120b",      "groq_llama70b",     "deepseek_r1",       "openai_gpt4o",       "openrouter_deepseek","anthropic_sonnet", "groq_compound",     "ollama_llama3_8b"],
    "onchain":      ["groq_llama8b",     "cerebras_small",    "groq_compound_mini","openrouter_llama",  "grok_2",            "openrouter_qwen",    "mistral_free",      "groq_gpt20b",       "hf_llama",          "ollama_llama3_3b"],
    "income":       ["groq_llama8b",     "cerebras_small",    "groq_compound_mini","groq_llama4",       "openrouter_gemma",  "cohere_free",        "mistral_free",      "together_llama",    "groq_gpt20b",       "ollama_llama3_3b"],
}

# =============================================================================
# LIVE PROVIDER DISCOVERY (additive, never replaces the manual chains above)
# ─────────────────────────────────────────────────────────────────────────────
# At startup, probes every company in _DISCOVERY_REGISTRY that has a key set
# in .env, fetches its live /models list, scores each model, and INSERTS the
# best 1-2 discovered models at the FRONT of each role's AGENT_PROVIDERS chain.
#
# Guarantees:
#   - Discovery NEVER removes or replaces a manual/static entry. Worst case
#     (no keys, no network, every provider down) AGENT_PROVIDERS is identical
#     to the hand-written list above and the bot runs exactly as before.
#   - Adding a brand-new AI company later = one line in _DISCOVERY_REGISTRY.
#     No other code changes needed; existing manual chains are untouched.
#   - This block can be deleted entirely and ai_engine.py still works, because
#     nothing below depends on it — ask_ai() only ever reads AGENT_PROVIDERS.
# =============================================================================

import threading as _threading

# name -> (api_base_url, env_var_for_key, auth_style)
# auth_style: "bearer" (Authorization: Bearer <key>), "anthropic" (x-api-key
# header), "param" (?key=<key> in query string), or "none" (no key needed).
_DISCOVERY_REGISTRY = {
    "groq":        ("https://api.groq.com/openai/v1",                "GROQ_API_KEY",       "bearer"),
    "openrouter":  ("https://openrouter.ai/api/v1",                   "OPENROUTER_API_KEY", "bearer"),
    "openai":      ("https://api.openai.com/v1",                      "OPENAI_API_KEY",     "bearer"),
    "anthropic":   ("https://api.anthropic.com/v1",                   "ANTHROPIC_API_KEY",  "anthropic"),
    "mistral":     ("https://api.mistral.ai/v1",                      "MISTRAL_API_KEY",    "bearer"),
    "cerebras":    ("https://api.cerebras.ai/v1",                     "CEREBRAS_API_KEY",   "bearer"),
    "together":    ("https://api.together.xyz/v1",                   "TOGETHER_API_KEY",   "bearer"),
    "cohere":      ("https://api.cohere.com/v1",                      "COHERE_API_KEY",     "bearer"),
    "xai":         ("https://api.x.ai/v1",                            "XAI_API_KEY",        "bearer"),
    "gemini":      ("https://generativelanguage.googleapis.com/v1beta","GEMINI_API_KEY",    "param"),
    "perplexity":  ("https://api.perplexity.ai",                      "PERPLEXITY_API_KEY", "bearer"),
    "deepseek":    ("https://api.deepseek.com/v1",                    "DEEPSEEK_API_KEY",   "bearer"),
    "fireworks":   ("https://api.fireworks.ai/inference/v1",          "FIREWORKS_API_KEY",  "bearer"),
    "ollama":      ("http://localhost:11434/v1",                      "",                   "none"),
    # ── To add a brand-new provider later, just add one line here: ──────────
    # "newco":     ("https://api.newco.com/v1",                       "NEWCO_API_KEY",      "bearer"),
}

# Per-role preferences — used only to decide WHICH discovered company's model
# gets inserted first for a given role. If a preferred company has no key,
# it's skipped; if NONE of a role's preferred companies are available, the
# role's manual chain is left completely untouched (no insertion happens).
_ROLE_DISCOVERY_PREFS = {
    "default":      ["anthropic","openai","groq","openrouter","mistral","cerebras","deepseek","xai","gemini","perplexity","together","cohere","fireworks","ollama"],
    "orchestrator": ["anthropic","openai","xai","deepseek","groq","openrouter","cerebras","mistral","gemini","ollama"],
    "analyst":      ["openai","anthropic","deepseek","xai","groq","openrouter","mistral","cerebras","gemini","ollama"],
    "intel":        ["groq","openrouter","perplexity","xai","mistral","cerebras","together","deepseek","ollama"],
    "trader":       ["groq","cerebras","openrouter","together","mistral","deepseek","ollama"],
    "risk":         ["anthropic","openai","deepseek","xai","groq","openrouter","cerebras","mistral","ollama"],
    "security":     ["anthropic","openai","deepseek","xai","groq","openrouter","cerebras","mistral","ollama"],
    "coder":        ["openai","anthropic","deepseek","groq","openrouter","mistral","xai","cerebras","ollama"],
    "research":     ["perplexity","anthropic","openai","deepseek","xai","groq","openrouter","mistral","ollama"],
    "onchain":      ["groq","cerebras","openrouter","together","mistral","deepseek","ollama"],
    "income":       ["groq","cerebras","openrouter","together","mistral","deepseek","ollama"],
}

# Keyword scoring — higher score = presumed smarter/better model. This is a
# heuristic over model-ID strings, nothing more; it can't know about models
# that don't follow common naming conventions, but it degrades gracefully
# (unscored/unknown models just rank low, never crash, never get excluded
# outright unless they match the embedding/audio/image-only blocklist).
def _score_discovered_model(model_id: str) -> int:
    m = model_id.lower()
    if any(x in m for x in ("embed", "whisper", "tts", "dall-e", "vision-only",
                             "rerank", "moderation", "audio")):
        return -1  # not a chat model — never use for council voting
    score = 0
    for kw, pts in (("405b",20),("claude-opus",19),("opus-4",19),("gpt-5",18),
                    ("claude-3-5",17),("claude-sonnet",16),("o3",16),("o1",15),
                    ("70b",13),("72b",13),("gpt-4o",13),("gpt-4",11),
                    ("deepseek-r1",12),("32b",10),("34b",10),("mixtral",9),
                    ("gemini-pro",9),("sonnet",9),("haiku",6),("flash",6),
                    ("mini",5),("8b",5),("7b",5),("small",4),
                    ("instruct",2),("chat",2),("versatile",2)):
        if kw in m:
            score += pts
    if any(x in m for x in ("preview","beta","alpha","experimental")):
        score -= 2
    return score


class _Discovery:
    """Holds discovery results. One instance, built once at import time."""
    def __init__(self):
        self.live_models   = {}   # company -> [(score, model_id), ...] best-first
        self.provider_cfgs = {}   # company -> (base_url, key, auth_style)
        self.ran           = False

    def run(self, timeout=6):
        if self.ran:
            return self.live_models
        results, lock = {}, _threading.Lock()

        def probe(company, base_url, key_env, auth_style):
            key = os.getenv(key_env, "") if key_env else ""
            if auth_style != "none" and (not key or len(key) < 8):
                return
            if not base_url:
                return
            models = self._fetch(company, base_url, key, auth_style, timeout)
            if models:
                with lock:
                    results[company] = models
                    self.provider_cfgs[company] = (base_url, key, auth_style)

        threads = [
            _threading.Thread(target=probe, args=(c, b, k, a), daemon=True)
            for c, (b, k, a) in _DISCOVERY_REGISTRY.items()
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout + 2)

        self.live_models = results
        self.ran = True
        return results

    @staticmethod
    def _fetch(company, base_url, key, auth_style, timeout):
        try:
            headers, params = {}, {}
            if auth_style == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            elif auth_style == "anthropic":
                headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
            elif auth_style == "param":
                params["key"] = key

            r = requests.get(base_url.rstrip("/") + "/models",
                              headers=headers, params=params, timeout=timeout)
            if r.status_code != 200:
                return []
            data = r.json()
            items = data.get("data", data.get("models", data)) if isinstance(data, dict) else data
            if not isinstance(items, list):
                return []
            scored = []
            for m in items:
                mid = m.get("id") or m.get("name") or m.get("model", "")
                if not mid:
                    continue
                s = _score_discovered_model(mid)
                if s >= 0:
                    scored.append((s, mid))
            scored.sort(reverse=True)
            return scored
        except Exception:
            return []  # network error, bad key, provider down — just skip it


_discovery = _Discovery()


def _register_discovered_provider(company: str, model_id: str) -> str:
    """Adds a discovered model into PROVIDERS so call_provider() can use it.
    Returns the key name to insert into an AGENT_PROVIDERS chain."""
    base_url, key, auth_style = _discovery.provider_cfgs.get(company, ("", "", "bearer"))
    key_name = f"{company}_live_{re.sub(r'[^a-zA-Z0-9]', '_', model_id)[:30]}"
    if key_name not in PROVIDERS:  # don't re-register if already present
        PROVIDERS[key_name] = {
            "url":     base_url.rstrip("/") + "/chat/completions",
            "key":     key,
            "model":   model_id,
            "format":  "anthropic" if company == "anthropic" else "openai",
            "free":    False,
            "min_ram": 0,
        }
    return key_name


def discover_and_extend_providers(verbose: bool = True):
    """
    Probe every configured company, then PREPEND the best live model(s) to
    each role's AGENT_PROVIDERS chain. Static/manual entries are never
    removed — they just move later in the priority order. If discovery
    finds nothing at all (no keys set, fully offline), this is a no-op and
    AGENT_PROVIDERS stays exactly as hand-written above.
    """
    live = _discovery.run()
    if not live:
        if verbose:
            print("  [AI] No live providers discovered — running on manual chains only")
        return

    if verbose:
        print(f"  [AI] Live providers online: {', '.join(sorted(live.keys()))}")
        for company in sorted(live.keys()):
            best = live[company][0][1] if live[company] else "?"
            print(f"       {company:12} best model: {best}")

    for role, prefs in _ROLE_DISCOVERY_PREFS.items():
        manual_chain = AGENT_PROVIDERS.get(role, AGENT_PROVIDERS["default"])
        inserted = []
        for company in prefs:
            models = live.get(company, [])
            if not models:
                continue
            # take the single best model from the first 1-2 available
            # preferred companies — keeps chains short and fast, while still
            # giving each role access to whatever's actually online.
            key = _register_discovered_provider(company, models[0][1])
            if key not in manual_chain:
                inserted.append(key)
            if len(inserted) >= 2:
                break
        if inserted:
            AGENT_PROVIDERS[role] = inserted + manual_chain

    if verbose:
        print(f"  [AI] Discovery-augmented {len(_ROLE_DISCOVERY_PREFS)} role chains "
              f"(manual chains kept as fallback, never removed)")


# Run discovery now, at import time. Wrapped in try/except as a final
# safety net: even if something inside discovery throws (a bug, a weird
# API response shape, anything), ai_engine.py must still import cleanly
# and AGENT_PROVIDERS must still be usable — manual mode always works.
try:
    discover_and_extend_providers()
except Exception as _e:
    logger.warning(f"[AI] Discovery failed, continuing on manual chains: {_e}")


# =============================================================================
# AVAILABILITY CHECK — silently skips anything without a key or enough RAM
# =============================================================================

def provider_available(name: str) -> bool:
    if name not in PROVIDERS:
        return False
    p = PROVIDERS[name]
    if p["min_ram"] > 0 and RAM_GB < p["min_ram"]:
        return False
    key = p.get("key", "")
    if key == "ollama":
        return True
    if name.startswith("cloudflare") and not os.getenv("CF_ACCOUNT_ID"):
        return False
    return bool(key)

# =============================================================================
# UNIVERSAL CALLER — openai-compatible, anthropic, cohere
# =============================================================================

def call_provider(name: str, prompt: str, system: str, max_tokens: int = 600) -> str:
    p    = PROVIDERS[name]
    fmt  = p["format"]
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(p.get("headers", {}))

    if fmt in ("openai", "ollama"):
        hdrs["Authorization"] = f"Bearer {p['key']}"
        payload = {
            "model":      p["model"],
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
        }
        r = requests.post(p["url"], headers=hdrs, json=payload, timeout=45)
        if r.status_code == 429:
            # One sleep-and-giveup wasn't enough — free-tier rate limits often
            # need several seconds to clear, and giving up after 2s meant
            # almost every call during a busy debate cycle failed outright.
            # Retry twice with growing backoff before truly giving up.
            for wait in (5, 12):
                time.sleep(wait)
                r = requests.post(p["url"], headers=hdrs, json=payload, timeout=45)
                if r.status_code != 429:
                    break
            if r.status_code == 429:
                raise Exception(f"{name}: rate limited")
        if r.status_code != 200:
            raise Exception(f"{name}: HTTP {r.status_code} — {r.text[:120]}")
        msg = r.json()["choices"][0]["message"]
        text = (msg.get("content") or msg.get("reasoning_content", "")).strip()
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        return text  # empty is ok — caller handles it

    elif fmt == "anthropic":
        hdrs["x-api-key"]         = p["key"]
        hdrs["anthropic-version"] = "2023-06-01"
        payload = {
            "model":      p["model"],
            "max_tokens": max_tokens,
            "system":     system,
            "messages":   [{"role": "user", "content": prompt}],
        }
        r = requests.post(p["url"], headers=hdrs, json=payload, timeout=45)
        if r.status_code != 200:
            raise Exception(f"{name}: HTTP {r.status_code} — {r.text[:120]}")
        return r.json()["content"][0]["text"].strip()

    elif fmt == "cohere":
        hdrs["Authorization"] = f"Bearer {p['key']}"
        payload = {
            "model":      p["model"],
            "max_tokens": max_tokens,
            "system":     system,
            "messages":   [{"role": "user", "content": prompt}],
        }
        r = requests.post(p["url"], headers=hdrs, json=payload, timeout=45)
        if r.status_code != 200:
            raise Exception(f"{name}: HTTP {r.status_code} — {r.text[:120]}")
        return r.json()["message"]["content"][0]["text"].strip()

    raise Exception(f"{name}: unknown format '{fmt}'")

# =============================================================================
# MAIN ask_ai — walks priority list, skips missing keys, never crashes
# =============================================================================

def ask_ai(prompt: str, agent: str = "default", system: str = None, max_tokens: int = 600) -> str:
    if system is None:
        system = "You are BR0THA, a sharp crypto trading analyst. Be concise and data-driven."

    priority = AGENT_PROVIDERS.get(agent, AGENT_PROVIDERS["default"])

    for name in priority:
        if not provider_available(name):
            continue
        try:
            result = call_provider(name, prompt, system, max_tokens)
            logger.info(f"[AI] {agent} → {name} ✅")
            return result
        except Exception as e:
            logger.warning(f"[AI] {agent} → {name} ✗  {str(e)[:80]}")
            time.sleep(0.3)
            continue

    return "⚠️ ALL PROVIDERS FAILED — check .env keys and run: python ai_engine.py"

# =============================================================================
# BACKWARD-COMPAT WRAPPERS
# =============================================================================

def ask_groq(prompt, system, model=None):       return ask_ai(prompt, "default",      system)
def ask_groq_large(prompt, system):             return ask_ai(prompt, "default",      system)
def ask_groq_small(prompt, system):             return ask_ai(prompt, "intel",        system)
def ask_groq_versatile(prompt, system):         return ask_ai(prompt, "analyst",      system)
def ask_cerebras(prompt, system):               return ask_ai(prompt, "orchestrator", system)
def ask_cerebras_small(prompt, system):         return ask_ai(prompt, "trader",       system)

# =============================================================================
# HEALTH CHECK — python ai_engine.py
# =============================================================================

if __name__ == "__main__":
    print(f"\n{'━'*62}")
    print(f"  BR0THERH00D AI Engine  |  RAM: {RAM_GB:.1f} GB")
    print(f"{'━'*62}\n")

    ping  = "Reply with exactly one word: online"
    sys_p = "Reply in one word only."

    available, locked, missing = [], [], []
    for name, p in PROVIDERS.items():
        if p["min_ram"] > RAM_GB:
            locked.append((name, p))
        elif not provider_available(name):
            missing.append((name, p))
        else:
            available.append((name, p))

    print(f"  🟢  AVAILABLE ({len(available)} providers)\n")
    for name, p in available:
        try:
            t0 = time.time()
            r  = call_provider(name, ping, sys_p, max_tokens=15)
            ms = int((time.time() - t0) * 1000)
            tag = "FREE" if p["free"] else "PAID"
            print(f"    ✅  {name:<32} [{tag}]  {ms:>5}ms  {r[:35]}")
        except Exception as e:
            print(f"    ❌  {name:<32}          {str(e)[:55]}")

    if missing:
        print(f"\n  🔑  OPTIONAL — add key to unlock ({len(missing)} providers)\n")
        for name, p in missing:
            print(f"    ○   {name:<32} → {_key_env(name)}")

    if locked:
        print(f"\n  🔒  NEEDS MORE RAM ({len(locked)} providers)\n")
        for name, p in locked:
            print(f"    🔒  {name:<32} (needs {p['min_ram']}GB, have {RAM_GB:.0f}GB)")

    print(f"\n  📋  AGENT ROUTING  (first available wins)\n")
    for agent, providers in AGENT_PROVIDERS.items():
        active = [p for p in providers if provider_available(p)]
        first  = active[0] if active else "⚠️ NONE"
        print(f"    {agent:<16} → {first}  (+{max(0,len(active)-1)} fallbacks)")

    print(f"\n  ➕  Add provider: new block in PROVIDERS dict (url/key/model/format/free/min_ram)")
    print(f"  🔑  Unlock paid:  add key to .env  (e.g. OPENROUTER_API_KEY=sk-or-...)\n")

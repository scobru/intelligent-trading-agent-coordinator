"""
Configurazione centrale del Master Coordinator.
Legge variabili d'ambiente con fallback sicuri per rete Base, agenti subordinati,
matrici di allocazione per regime e parametri di rischio.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Carica .env se presente
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

def _b(var_name: str, default: bool) -> bool:
    val = os.getenv(var_name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

def _f(var_name: str, default: float) -> float:
    try:
        return float(os.getenv(var_name, str(default)))
    except (TypeError, ValueError):
        return default

def _i(var_name: str, default: int) -> int:
    try:
        return int(os.getenv(var_name, str(default)))
    except (TypeError, ValueError):
        return default

# --- Rete Base ---
BASE_RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
CHAIN_ID = _i("CHAIN_ID", 8453)

# --- Modalità di Esecuzione ---
DRY_RUN = _b("DRY_RUN", True)
PAPER_TRADING = _b("PAPER_TRADING", True)
PAPER_START_USDC = _f("PAPER_START_USDC", 10000.0)

# --- Master Treasury Wallet ---
MASTER_WALLET_ADDRESS = os.getenv("MASTER_WALLET_ADDRESS", "").strip()
MASTER_PRIVATE_KEY = os.getenv("MASTER_PRIVATE_KEY", "").strip()

# --- Contratti Base L2 ---
USDC_ADDRESS = os.getenv("USDC_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
WETH_ADDRESS = os.getenv("WETH_ADDRESS", "0x4200000000000000000000000000000000000006")

# --- I 6 Agenti Subordinati ---
AGENTS = {
    "perp": {
        "id": "perp",
        "name": "Perpetual Trader",
        "repo": "intelligent-trading-agent",
        "url": os.getenv("AGENT_PERP_URL", "http://localhost:3001"),
        "wallet": os.getenv("AGENT_PERP_WALLET", ""),
        "color": "#3b82f6",  # Blu
        "icon": "📈",
        "type": "speculative_leverage",
        "description": "Perpetual su SynFutures V3 (leva su BTC/ETH, Prophet & LLM)"
    },
    "yield": {
        "id": "yield",
        "name": "Yield Aggregator",
        "repo": "intelligent-trading-agent-yield",
        "url": os.getenv("AGENT_YIELD_URL", "http://localhost:3002"),
        "wallet": os.getenv("AGENT_YIELD_WALLET", ""),
        "color": "#10b981",  # Verde smeraldo
        "icon": "🌱",
        "type": "passive_earn",
        "description": "Lending e vault a basso rischio (Aave, Compound, Morpho, ERC-4626)"
    },
    "neutral": {
        "id": "neutral",
        "name": "Delta Neutral Carry",
        "repo": "intelligent-trading-agent-neutral",
        "url": os.getenv("AGENT_NEUTRAL_URL", "http://localhost:3003"),
        "wallet": os.getenv("AGENT_NEUTRAL_WALLET", ""),
        "color": "#8b5cf6",  # Viola
        "icon": "⚖️",
        "type": "arbitrage",
        "description": "Funding rate carry (Spot Uniswap V3 + Short SynFutures V3)"
    },
    "lp": {
        "id": "lp",
        "name": "Concentrated LP",
        "repo": "intelligent-trading-agent-lp",
        "url": os.getenv("AGENT_LP_URL", "http://localhost:3004"),
        "wallet": os.getenv("AGENT_LP_WALLET", ""),
        "color": "#06b6d4",  # Ciano
        "icon": "💧",
        "type": "fee_generation",
        "description": "Fornitura di liquidità concentrata su Uniswap V3 con re-centering"
    },
    "dca": {
        "id": "dca",
        "name": "DCA & Rebalancer",
        "repo": "intelligent-trading-agent-dca",
        "url": os.getenv("AGENT_DCA_URL", "http://localhost:3005"),
        "wallet": os.getenv("AGENT_DCA_WALLET", ""),
        "color": "#f59e0b",  # Ambra/Arancio
        "icon": "⏳",
        "type": "accumulation",
        "description": "Dollar-Cost Averaging e ribilanciamento portfolio su Base"
    },
    "degen": {
        "id": "degen",
        "name": "Degen Spot Trader",
        "repo": "intelligent-trading-agent-degen",
        "url": os.getenv("AGENT_DEGEN_URL", "http://localhost:3006"),
        "wallet": os.getenv("AGENT_DEGEN_WALLET", ""),
        "color": "#ec4899",  # Rosa acceso
        "icon": "🎰",
        "type": "high_risk_spot",
        "description": "Spot trading di meme/altcoin con screening GoPlus Security"
    }
}

DASHBOARD_RUN_TOKEN = os.getenv("DASHBOARD_RUN_TOKEN", "").strip()
AGENT_RUN_TOKEN = os.getenv("AGENT_RUN_TOKEN", DASHBOARD_RUN_TOKEN).strip()
AGENT_HTTP_USER = os.getenv("AGENT_HTTP_USER", os.getenv("HTTP_BASIC_USER", "scobru")).strip()
AGENT_HTTP_PASS = os.getenv("AGENT_HTTP_PASS", os.getenv("HTTP_BASIC_PASS", AGENT_RUN_TOKEN or "francos88")).strip()

# Chiavi private opzionali per i sub-agenti (Cross-Bot Gas Sharing)
SUB_AGENTS_PRIVATE_KEY = os.getenv("SUB_AGENTS_PRIVATE_KEY", "").strip()

def get_agent_private_key(agent_id: str) -> str:
    """Ritorna la chiave privata di un agente (se disponibile) per trasferimenti diretti o cross-bot gas refuel."""
    env_var_name = f"AGENT_{agent_id.upper()}_PRIVATE_KEY"
    pk = os.getenv(env_var_name, "").strip()
    if pk:
        return pk
    if SUB_AGENTS_PRIVATE_KEY:
        return SUB_AGENTS_PRIVATE_KEY
    cfg = AGENTS.get(agent_id, {})
    agent_wallet = cfg.get("wallet", "").strip().lower()
    master_wallet = MASTER_WALLET_ADDRESS.strip().lower()
    if agent_wallet and master_wallet and agent_wallet == master_wallet and MASTER_PRIVATE_KEY:
        return MASTER_PRIVATE_KEY
    return ""

# --- Matrici di Allocazione Target per Regime (%) ---
# Somma sempre 100% (1.00)
REGIME_TARGET_WEIGHTS = {
    # Mercato neutrale / standard: Degen motore di crescita principale, DCA accumulo e Perp direzionale
    "BALANCED": {
        "degen": 0.35,     # 35% motore di crescita speculativo (altcoin/meme screening GoPlus)
        "dca": 0.25,       # 25% accumulo asset primari (WETH/CBTC)
        "neutral": 0.15,   # 15% funding rate carry (attivo solo se portafoglio capiente >= $1000)
        "lp": 0.15,        # 15% fee AMM (attivo solo se portafoglio capiente >= $350)
        "perp": 0.10,      # 10% direzionale a leva
        "yield": 0.00      # 0% lending (disattivato per micro-capitali, sostituito da degen)
    },
    # Trend rialzista confermato / Greed
    "BULL_MOMENTUM": {
        "degen": 0.35,     # 35% momentum su memecoin/altcoin
        "perp": 0.25,      # 25% leva e trend follower su BTC/ETH
        "dca": 0.15,       # 15% accumulo continuo
        "lp": 0.15,
        "neutral": 0.10,
        "yield": 0.00
    },
    # Mercato ribassista / Paura / Panic
    "BEAR_PANIC": {
        "dca": 0.50,       # 50% acquisto del dip a sconto moltiplicato
        "degen": 0.25,     # 25% rimbalzi veloci
        "neutral": 0.15,   # Arbitraggio funding (se finanziabile)
        "perp": 0.10,      # Solo coperture / short
        "lp": 0.00,        # Zero LP per evitare impermanent loss
        "yield": 0.00
    },
    # Mercato laterale a bassa volatilità (Chop)
    "RANGE_CHOP": {
        "degen": 0.25,     # 25% breakout trading
        "dca": 0.20,       # 20% accumulo range
        "neutral": 0.25,   # Cattura funding costante
        "lp": 0.25,        # Fee di trading su Uniswap V3 nei range stretti
        "perp": 0.05,
        "yield": 0.00
    },
    # Shock improvviso di volatilità / Cigno nero
    "HIGH_VOLATILITY": {
        "dca": 0.50,       # 50% acquisto a forte sconto
        "degen": 0.25,     # 25% cattura rimbalzi post-liquidazione
        "neutral": 0.15,
        "perp": 0.10,      # Minima leva protetta
        "lp": 0.00,        # LP ritira immediatamente le posizioni
        "yield": 0.00
    }
}

# --- AI Macro Strategist (OpenRouter) ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat").strip()
DYNAMIC_PERFORMANCE_REBALANCE = _b("DYNAMIC_PERFORMANCE_REBALANCE", True)
MAX_PERFORMANCE_WEIGHT_SHIFT = _f("MAX_PERFORMANCE_WEIGHT_SHIFT", 0.10)

# --- Parametri Operativi del Coordinator ---
INTERVAL_SECONDS = _i("COORDINATOR_INTERVAL_SECONDS", 900)  # Default 15 minuti
AUTO_REBALANCE = _b("AUTO_REBALANCE", False)
MIN_REBALANCE_USD = _f("MIN_REBALANCE_USD", 10.0)
MIN_SWEEP_IDLE_USD = _f("MIN_SWEEP_IDLE_USD", 1.0)          # Soglia minima di recupero per bot a target 0%
REBALANCE_THRESHOLD_PCT = _f("REBALANCE_THRESHOLD_PCT", 5.0)

# --- Soglie Minime Operative per Agente (USD) ---
# Se il capitale allocato o disponibile è inferiore alla soglia minima operativa,
# il bot non può piazzare ordini (es. Neutral richiede >= $150 per spot 1x e short perp SynFutures con nozionale >= $70).
AGENT_MIN_VIABLE_CAPITAL = {
    "neutral": _f("MIN_VIABLE_NEUTRAL_USD", 150.0), # Spot 1x ($70) + Margine Gate ($35) + buffer
    "lp": _f("MIN_VIABLE_LP_USD", 50.0),            # Concentrated LP + recentering fees
    "yield": _f("MIN_VIABLE_YIELD_USD", 50.0),      # Lending ha senso solo sopra $50
    "perp": _f("MIN_VIABLE_PERP_USD", 15.0),        # Con leva 5x copre il minimo nozionale di $70
    "degen": _f("MIN_VIABLE_DEGEN_USD", 15.0),      # Minimo swap altcoin e slippage
    "dca": _f("MIN_VIABLE_DCA_USD", 10.0),          # Minimo acquisto ricorrente spot
}

ENABLE_CAPITAL_PRUNING = _b("ENABLE_CAPITAL_PRUNING", True)
ENABLE_IDLE_CAPITAL_SWEEP = _b("ENABLE_IDLE_CAPITAL_SWEEP", True)

# --- Gas Balancer (ETH su Base) ---
AUTO_REFUEL_GAS = _b("AUTO_REFUEL_GAS", True)
GAS_WARN_ETH = _f("GAS_WARN_ETH", 0.0015)
MIN_GAS_RESERVE_ETH = _f("MIN_GAS_RESERVE_ETH", 0.001)
REFUEL_AMOUNT_ETH = _f("REFUEL_AMOUNT_ETH", 0.003)
MAX_GAS_PRICE_GWEI = _f("MAX_GAS_PRICE_GWEI", 0.1)

# --- Gestione del Rischio Globale ---
MAX_PORTFOLIO_DRAWDOWN_24H_PCT = _f("MAX_PORTFOLIO_DRAWDOWN_24H_PCT", 8.0)
EMERGENCY_HALT_DEGEN_ON_PANIC = _b("EMERGENCY_HALT_DEGEN_ON_PANIC", True)

# --- Master Dashboard ---
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = _i("DASHBOARD_PORT", _i("PORT", 3000))
DASHBOARD_RUN_TOKEN = os.getenv("DASHBOARD_RUN_TOKEN", "")

# --- Master Telegram Bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --- Database ---
_raw_db = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "coordinator.db")).strip()
if _raw_db == "app/data/coordinator.db" and Path("/app/data").exists():
    SQLITE_DB_PATH = "/app/data/coordinator.db"
elif _raw_db and not os.path.isabs(_raw_db) and Path("/app").exists():
    SQLITE_DB_PATH = str(Path("/app") / _raw_db)
else:
    SQLITE_DB_PATH = _raw_db
PAPER_ACCOUNT_FILE = str(BASE_DIR / "paper_treasury.json")

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

AGENT_RUN_TOKEN = os.getenv("AGENT_RUN_TOKEN", "")

# --- Matrici di Allocazione Target per Regime (%) ---
# Somma sempre 100% (1.00)
REGIME_TARGET_WEIGHTS = {
    # Mercato neutrale / standard
    "BALANCED": {
        "yield": 0.35,     # 35% sicuro a rendimento
        "dca": 0.25,       # 25% accumulo asset primari
        "neutral": 0.15,   # 15% funding rate carry
        "lp": 0.15,        # 15% fee AMM
        "perp": 0.07,      # 7% direzionale
        "degen": 0.03      # 3% speculativo
    },
    # Trend rialzista confermato / Greed
    "BULL_MOMENTUM": {
        "yield": 0.20,
        "dca": 0.15,
        "neutral": 0.10,
        "lp": 0.15,
        "perp": 0.25,      # Aumenta leva e trend follower
        "degen": 0.15      # Spazio alle meme/altcoin in corsa
    },
    # Mercato ribassista / Paura / Panic
    "BEAR_PANIC": {
        "yield": 0.50,     # Parcheggio sicuro in USDC
        "dca": 0.30,       # Acquisto del dip a sconto moltiplicato
        "neutral": 0.15,   # Arbitraggio funding
        "lp": 0.00,        # Zero LP per evitare impermanent loss asimmetrica
        "perp": 0.05,      # Solo short o minime coperture
        "degen": 0.00      # Zero degen durante i crash
    },
    # Mercato laterale a bassa volatilità (Chop)
    "RANGE_CHOP": {
        "yield": 0.25,
        "dca": 0.15,
        "neutral": 0.25,   # Cattura funding costante
        "lp": 0.30,        # Massimizza fee di trading su Uniswap V3 nei range stretti
        "perp": 0.05,
        "degen": 0.00
    },
    # Shock improvviso di volatilità / Cigno nero
    "HIGH_VOLATILITY": {
        "yield": 0.65,     # Massima conservazione in stable
        "dca": 0.20,
        "neutral": 0.15,
        "lp": 0.00,        # LP ritira immediatamente le posizioni
        "perp": 0.00,      # Perp disattivato
        "degen": 0.00
    }
}

# --- Parametri Operativi del Coordinator ---
INTERVAL_SECONDS = _i("COORDINATOR_INTERVAL_SECONDS", 900)  # Default 15 minuti
AUTO_REBALANCE = _b("AUTO_REBALANCE", False)
MIN_REBALANCE_USD = _f("MIN_REBALANCE_USD", 25.0)
REBALANCE_THRESHOLD_PCT = _f("REBALANCE_THRESHOLD_PCT", 5.0)

# --- Gas Balancer (ETH su Base) ---
AUTO_REFUEL_GAS = _b("AUTO_REFUEL_GAS", False)
GAS_WARN_ETH = _f("GAS_WARN_ETH", 0.0015)
MIN_GAS_RESERVE_ETH = _f("MIN_GAS_RESERVE_ETH", 0.001)
REFUEL_AMOUNT_ETH = _f("REFUEL_AMOUNT_ETH", 0.003)
MAX_GAS_PRICE_GWEI = _f("MAX_GAS_PRICE_GWEI", 0.1)

# --- Gestione del Rischio Globale ---
MAX_PORTFOLIO_DRAWDOWN_24H_PCT = _f("MAX_PORTFOLIO_DRAWDOWN_24H_PCT", 8.0)
EMERGENCY_HALT_DEGEN_ON_PANIC = _b("EMERGENCY_HALT_DEGEN_ON_PANIC", True)

# --- Master Dashboard ---
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = _i("DASHBOARD_PORT", 3000)
DASHBOARD_RUN_TOKEN = os.getenv("DASHBOARD_RUN_TOKEN", "")

# --- Master Telegram Bot ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# --- Database ---
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "coordinator.db"))
PAPER_ACCOUNT_FILE = str(BASE_DIR / "paper_treasury.json")

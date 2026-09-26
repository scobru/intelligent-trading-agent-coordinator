import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from risk_engine import RiskEngine

def test_risk_engine_sums_all_funds_including_gas_eth():
    engine = RiskEngine()
    eth_price = 2500.0

    agents_status = {
        "yield": {
            "equity_usd": 1000.0,
            "gas_eth": 0.02, # 0.02 * 2500 = $50.0
            "positions_count": 0,
            "online": True
        },
        "dca": {
            "equity_usd": 500.0,
            "gas_eth": 0.04, # 0.04 * 2500 = $100.0
            "positions_count": 0,
            "online": True
        },
        "perp": {
            "equity_usd": 200.0,
            "gas_eth": 0.01, # 0.01 * 2500 = $25.0
            "positions": [],
            "online": True
        }
    }

    # Master Treasury: $5000 USDC + 1.0 ETH (1.0 * 2500 = $2500.0) -> $7500.0
    risk = engine.evaluate_portfolio_risk(
        agents_status=agents_status,
        treasury_cash_usd=5000.0,
        treasury_eth=1.0,
        eth_price=eth_price
    )

    # Expected:
    # Treasury: 5000 + 2500 = 7500.0
    # Yield: 1000 + 50 = 1050.0
    # DCA: 500 + 100 = 600.0
    # Perp: 200 + 25 = 225.0
    # Total = 7500 + 1050 + 600 + 225 = 9375.0
    assert risk["total_net_worth_usd"] == 9375.0

    # Total gas ETH: 1.0 (treasury) + 0.02 + 0.04 + 0.01 = 1.07 ETH
    assert risk["total_gas_eth"] == 1.07
    assert risk["total_gas_usd"] == 1.07 * eth_price

    # Verify per-agent total_val_usd and gas_usd
    assert agents_status["yield"]["gas_usd"] == 50.0
    assert agents_status["yield"]["total_val_usd"] == 1050.0
    assert agents_status["dca"]["gas_usd"] == 100.0
    assert agents_status["dca"]["total_val_usd"] == 600.0

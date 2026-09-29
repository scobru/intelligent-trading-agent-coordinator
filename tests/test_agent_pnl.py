import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import db_utils


def _snap(agent, equity):
    db_utils.save_portfolio_snapshot({
        "total_net_worth_usd": equity, "regime": "NEUTRAL",
        "agents": {agent: {"online": True, "balance_usd": equity, "equity_usd": equity}},
    })


def test_pnl_ignores_zero_baseline_and_transfers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SQLITE_DB_PATH", str(tmp_path / "t.db"))
    db_utils.init_db()

    _snap("dca", 0.0)
    assert db_utils.get_agents_historical_pnl()["dca"]["pnl_pct"] is None

    db_utils.log_operation("TRANSFER_USDC", 50.0, "USDC", "master_treasury", "dca", status="SUCCESS")
    _snap("dca", 50.0)  # baseline = 50
    db_utils.log_operation("TRANSFER_USDC", 50.0, "USDC", "master_treasury", "dca", status="SUCCESS")
    _snap("dca", 105.0)  # +50 deposito, +5 di rendimento

    res = db_utils.get_agents_historical_pnl()["dca"]
    assert res["pnl_usd"] == 5.0
    assert res["pnl_pct"] == 5.0  # 5 / (50 + 50)

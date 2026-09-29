import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import db_utils


def _seed(tmp):
    config.SQLITE_DB_PATH = os.path.join(tmp, "t.db")
    db_utils.init_db()
    conn = db_utils.get_connection()
    t0 = datetime.now(timezone.utc) - timedelta(hours=30)
    equities = [100.0, 110.0, 160.0, 165.0]  # +10 gain, +50 deposit, +5 gain
    for i, eq in enumerate(equities):
        ts = (t0 + timedelta(hours=10 * i)).isoformat()
        conn.execute(
            "INSERT INTO agent_snapshots (created_at, agent_id, online, balance_usd, equity_usd) VALUES (?, 'perp', 1, 0, ?)",
            (ts, eq),
        )
    # deposito eseguito nel ciclo dello snapshot #2, visibile nell'equity dello snapshot #3
    dep_ts = (t0 + timedelta(hours=19)).isoformat()
    conn.execute(
        "INSERT INTO rebalance_operations (created_at, operation_type, from_agent, to_agent, amount, asset, status)"
        " VALUES (?, 'REBALANCE_FUND', 'yield', 'perp', 50.0, 'USDC', 'SUCCESS')",
        (dep_ts,),
    )
    conn.commit()
    conn.close()


def test_performance_excludes_capital_transfers():
    with tempfile.TemporaryDirectory() as tmp:
        old = config.SQLITE_DB_PATH
        try:
            _seed(tmp)
            perf = db_utils.get_agents_adjusted_performance(window_hours=24)["perp"]
        finally:
            config.SQLITE_DB_PATH = old
    assert perf["pnl_usd"] == 15.0  # 165 - 100 - 50
    assert perf["pnl_pct"] == 10.0  # 15 / (100 + 50)
    assert perf["pnl_window_usd"] > 0

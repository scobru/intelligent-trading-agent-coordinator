"""
Gestione del database SQLite per il Coordinator.
Traccia snapshot di portafoglio, metriche degli agenti, storico dei ribilanciamenti ed errori.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

def get_connection() -> sqlite3.Connection:
    db_path = config.Path(config.SQLITE_DB_PATH) if hasattr(config, "Path") else None
    if not db_path:
        from pathlib import Path
        db_path = Path(config.SQLITE_DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """Inizializza le tabelle del database se non esistono."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        total_net_worth_usd REAL NOT NULL,
        regime TEXT NOT NULL,
        fear_and_greed INTEGER,
        circuit_breaker_active INTEGER DEFAULT 0,
        pnl_24h_usd REAL DEFAULT 0.0,
        pnl_24h_pct REAL DEFAULT 0.0,
        details_json TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agent_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER,
        created_at TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        online INTEGER NOT NULL,
        balance_usd REAL NOT NULL,
        equity_usd REAL NOT NULL,
        gas_eth REAL,
        target_pct REAL,
        actual_pct REAL,
        status TEXT,
        FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS rebalance_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        operation_type TEXT NOT NULL, -- 'TRANSFER_USDC', 'REFUEL_ETH', 'SWEEP_PROFIT'
        from_agent TEXT,
        to_agent TEXT,
        amount REAL NOT NULL,
        asset TEXT NOT NULL,          -- 'USDC', 'ETH'
        tx_hash TEXT,
        status TEXT NOT NULL,         -- 'SUCCESS', 'SIMULATED', 'FAILED'
        reason TEXT
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS coordinator_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        error_type TEXT NOT NULL,
        error_message TEXT NOT NULL,
        source TEXT
    );
    """)

    conn.commit()
    conn.close()
    logger.info("Database SQLite coordinator inizializzato: %s", config.SQLITE_DB_PATH)

def save_portfolio_snapshot(data: Dict[str, Any]) -> int:
    """Salva uno snapshot globale e gli stati individuali dei bot."""
    conn = get_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        cur.execute("""
        INSERT INTO portfolio_snapshots (
            created_at, total_net_worth_usd, regime, fear_and_greed,
            circuit_breaker_active, pnl_24h_usd, pnl_24h_pct, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            now_iso,
            float(data.get("total_net_worth_usd", 0.0)),
            data.get("regime", "BALANCED"),
            data.get("fear_and_greed", 50),
            1 if data.get("circuit_breaker_active", False) else 0,
            float(data.get("pnl_24h_usd", 0.0)),
            float(data.get("pnl_24h_pct", 0.0)),
            json.dumps(data, default=str)
        ))
        snapshot_id = cur.lastrowid

        agents_data = data.get("agents", {})
        for agent_id, a in agents_data.items():
            cur.execute("""
            INSERT INTO agent_snapshots (
                snapshot_id, created_at, agent_id, online,
                balance_usd, equity_usd, gas_eth, target_pct, actual_pct, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                snapshot_id,
                now_iso,
                agent_id,
                1 if a.get("online", False) else 0,
                float(a.get("balance_usd", 0.0)),
                float(a.get("equity_usd", 0.0)),
                float(a.get("gas_eth", 0.0)) if a.get("gas_eth") is not None else None,
                float(a.get("target_pct", 0.0)),
                float(a.get("actual_pct", 0.0)),
                a.get("status", "unknown")
            ))

        conn.commit()
        return snapshot_id
    except Exception as exc:
        conn.rollback()
        logger.error("Errore salvataggio snapshot portfolio: %s", exc)
        return -1
    finally:
        conn.close()

def log_operation(
    op_type: str,
    amount: float,
    asset: str,
    from_agent: Optional[str] = None,
    to_agent: Optional[str] = None,
    tx_hash: Optional[str] = None,
    status: str = "SUCCESS",
    reason: Optional[str] = None
) -> None:
    """Registra una transazione o riallocazione eseguita."""
    conn = get_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        cur.execute("""
        INSERT INTO rebalance_operations (
            created_at, operation_type, from_agent, to_agent, amount, asset, tx_hash, status, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (now_iso, op_type, from_agent, to_agent, amount, asset, tx_hash, status, reason))
        conn.commit()
    except Exception as exc:
        logger.error("Errore salvataggio operazione: %s", exc)
    finally:
        conn.close()

def log_error(error_type: str, message: str, source: str = "coordinator") -> None:
    """Registra un errore rilevato."""
    conn = get_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        cur.execute("""
        INSERT INTO coordinator_errors (created_at, error_type, error_message, source)
        VALUES (?, ?, ?, ?);
        """, (now_iso, error_type, message, source))
        conn.commit()
    except Exception as exc:
        logger.error("Errore logging errore: %s", exc)
    finally:
        conn.close()

def get_recent_snapshots(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, created_at, total_net_worth_usd, regime, fear_and_greed,
           circuit_breaker_active, pnl_24h_usd, pnl_24h_pct
    FROM portfolio_snapshots
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return list(reversed(rows))

def get_recent_operations(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, created_at, operation_type, from_agent, to_agent, amount, asset, tx_hash, status, reason
    FROM rebalance_operations
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_recent_errors(limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, created_at, error_type, error_message, source
    FROM coordinator_errors
    ORDER BY id DESC LIMIT ?;
    """, (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

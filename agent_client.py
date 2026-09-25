"""
Client HTTP per l'interazione con i 6 agenti subordinati.
Esegue query concorrenti agli endpoint /api/status e invia comandi di esecuzione via POST /api/run.
Supporta fallback su file locali (SQLite/JSON) se un agent HTTP e' momentaneamente offline.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

import config

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 4.0

class AgentClient:
    def __init__(self):
        self.agents_config = config.AGENTS
        self.run_token = config.AGENT_RUN_TOKEN

    def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        """Interroga un singolo agente via HTTP /api/status con fallback locale."""
        cfg = self.agents_config.get(agent_id)
        if not cfg:
            return {"online": False, "error": f"Agente '{agent_id}' non configurato"}

        url = f"{cfg['url'].rstrip('/')}/api/status"
        res_data = {
            "id": agent_id,
            "name": cfg["name"],
            "repo": cfg["repo"],
            "color": cfg["color"],
            "icon": cfg["icon"],
            "type": cfg["type"],
            "online": False,
            "balance_usd": 0.0,
            "equity_usd": 0.0,
            "gas_eth": 0.0,
            "wallet": cfg.get("wallet", ""),
            "positions_count": 0,
            "positions": [],
            "status": "offline",
            "is_paused": False,
            "pause_info": {},
            "raw": {}
        }

        try:
            resp = requests.get(url, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                raw = resp.json()
                res_data["online"] = True
                res_data["raw"] = raw
                res_data["status"] = "online"
                self._extract_metrics(res_data, raw, agent_id)
                return res_data
        except Exception as exc:
            logger.debug("Agente %s non raggiungibile via HTTP (%s). Tento fallback locale.", agent_id, exc)

        # Fallback locale se il processo HTTP e' spento ma i dati su disco esistono
        self._local_disk_fallback(res_data, agent_id)
        return res_data

    def _extract_metrics(self, res: Dict[str, Any], raw: Dict[str, Any], agent_id: str) -> None:
        """Estrae in modo uniforme balance, equity e gas dalle diverse strutture delle dashboard."""
        meta = raw.get("meta", {})
        wallet_info = meta.get("wallet", {})

        # Stato pausa
        res["is_paused"] = bool(raw.get("is_paused", False))
        res["pause_info"] = raw.get("pause_info", {})

        # Estrazione wallet
        if not res["wallet"]:
            res["wallet"] = wallet_info.get("address", "") or raw.get("wallet_address", "")

        # Estrazione Gas ETH
        if "eth" in wallet_info:
            try:
                res["gas_eth"] = float(wallet_info["eth"])
            except (ValueError, TypeError):
                pass
        elif "gas_eth" in raw:
            try:
                res["gas_eth"] = float(raw["gas_eth"])
            except (ValueError, TypeError):
                pass

        # Estrazione Balance & Equity in base alla specifica implementazione del bot
        if agent_id == "perp":
            # intelligent-trading-agent
            res["balance_usd"] = float(raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", res["balance_usd"]) or res["balance_usd"])
            pos = raw.get("positions", [])
            res["positions"] = pos
            res["positions_count"] = len(pos)

        elif agent_id == "yield":
            # intelligent-trading-agent-yield
            res["balance_usd"] = float(raw.get("unallocated_usdc", 0.0) or raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", 0.0) or res["balance_usd"])
            pos = raw.get("active_positions", []) or raw.get("positions", [])
            res["positions"] = pos
            res["positions_count"] = len(pos)

        elif agent_id == "neutral":
            # intelligent-trading-agent-neutral
            res["balance_usd"] = float(raw.get("free_usdc", 0.0) or raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", 0.0) or res["balance_usd"])
            pos = raw.get("pairs", []) or raw.get("positions", [])
            res["positions"] = pos
            res["positions_count"] = len(pos)

        elif agent_id == "lp":
            # intelligent-trading-agent-lp
            res["balance_usd"] = float(raw.get("free_usd", 0.0) or raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", 0.0) or res["balance_usd"])
            pos = raw.get("positions", [])
            res["positions"] = pos
            res["positions_count"] = len(pos)

        elif agent_id == "dca":
            # intelligent-trading-agent-dca
            p = raw.get("portfolio", {})
            res["balance_usd"] = float(p.get("USDC", {}).get("value_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", 0.0) or res["balance_usd"])
            res["positions_count"] = len([k for k, v in p.items() if k != "USDC" and float(v.get("value_usd", 0.0)) > 1.0])

        elif agent_id == "degen":
            # intelligent-trading-agent-degen
            res["balance_usd"] = float(raw.get("free_usdc", 0.0) or raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", 0.0) or res["balance_usd"])
            pos = raw.get("positions", [])
            res["positions"] = pos
            res["positions_count"] = len(pos)

        else:
            res["balance_usd"] = float(raw.get("balance_usd", 0.0) or 0.0)
            res["equity_usd"] = float(raw.get("total_value_usd", res["balance_usd"]) or res["balance_usd"])

    def _local_disk_fallback(self, res: Dict[str, Any], agent_id: str) -> None:
        """Legge lo stato dai file persistenti se la dashboard HTTP del bot e' offline."""
        repo_name = res.get("repo", "")
        if not repo_name:
            return

        repo_dir = config.BASE_DIR.parent / repo_name
        if not repo_dir.exists():
            return

        # Cerca file tipici di stato paper o live
        paper_candidates = ["paper_account.json", "paper_portfolio.json", "paper_lp.json"]
        pos_file = repo_dir / "positions.json"

        for p_name in paper_candidates:
            p_file = repo_dir / p_name
            if p_file.exists():
                try:
                    with open(p_file, "r", encoding="utf-8") as f:
                        pdata = json.load(f)
                        b_val = float(pdata.get("balance", pdata.get("collateral", pdata.get("initial_usdc", 0.0))))
                        if "balances" in pdata and isinstance(pdata["balances"], dict):
                            b_val = float(pdata["balances"].get("USDC", b_val))
                        res["balance_usd"] = b_val
                        res["equity_usd"] = float(pdata.get("equity", pdata.get("total_value_usd", b_val)))
                        res["status"] = "offline (cached state)"
                        break
                except Exception:
                    pass

        if pos_file.exists():
            try:
                with open(pos_file, "r", encoding="utf-8") as f:
                    pos = json.load(f)
                    if isinstance(pos, list):
                        res["positions"] = pos
                        res["positions_count"] = len(pos)
                    elif isinstance(pos, dict):
                        res["positions"] = list(pos.values())
                        res["positions_count"] = len(pos)
            except Exception:
                pass

        # Verifica stato pausa da SQLite locale
        db_candidates = ["trading.db", "yield_agent.db", "neutral_agent.db", "lp_agent.db", "dca_agent.db", "degen_agent.db"]
        for db_name in db_candidates:
            db_file = repo_dir / db_name
            if db_file.exists():
                try:
                    import sqlite3
                    with sqlite3.connect(str(db_file), timeout=1.0) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT value FROM bot_control WHERE key = 'is_paused';")
                        row = cur.fetchone()
                        if row:
                            res["is_paused"] = str(row[0]).lower() in ("1", "true", "yes")
                except Exception:
                    pass
                break

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Recupera contemporaneamente lo stato di tutti i 6 agenti in parallelo."""
        statuses = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(self.get_agent_status, agent_id): agent_id
                for agent_id in self.agents_config.keys()
            }
            for fut in as_completed(futures):
                agent_id = futures[fut]
                try:
                    statuses[agent_id] = fut.result()
                except Exception as exc:
                    logger.error("Eccezione durante il fetch per %s: %s", agent_id, exc)
                    statuses[agent_id] = {
                        "id": agent_id,
                        "name": self.agents_config[agent_id]["name"],
                        "online": False,
                        "error": str(exc),
                        "balance_usd": 0.0,
                        "equity_usd": 0.0,
                        "gas_eth": 0.0,
                        "positions_count": 0,
                        "positions": []
                    }
        return statuses

    def trigger_agent_run(self, agent_id: str) -> Dict[str, Any]:
        """Invia un POST /api/run all'agente specificato."""
        cfg = self.agents_config.get(agent_id)
        if not cfg:
            return {"status": "error", "message": f"Agente '{agent_id}' inesistente"}

        url = f"{cfg['url'].rstrip('/')}/api/run"
        headers = {}
        if self.run_token:
            headers["Authorization"] = f"Bearer {self.run_token}"
            headers["X-Run-Token"] = self.run_token
            headers["X-Admin-Token"] = self.run_token

        try:
            resp = requests.post(url, headers=headers, timeout=TIMEOUT_SECONDS)
            if resp.status_code in (200, 202):
                data = {}
                try:
                    data = resp.json()
                except Exception:
                    pass
                return {"status": "success", "message": data.get("message", f"Ciclo avviato per {agent_id}"), "data": data}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def trigger_all_runs(self) -> Dict[str, Any]:
        """Triggera l'esecuzione su tutti i 6 agenti."""
        results = {}
        for agent_id in self.agents_config.keys():
            results[agent_id] = self.trigger_agent_run(agent_id)
        return results

    def pause_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        """Invia un POST /api/pause all'agente specificato per sospenderne l'attivita'."""
        cfg = self.agents_config.get(agent_id)
        if not cfg:
            return {"status": "error", "message": f"Agente '{agent_id}' inesistente"}

        url = f"{cfg['url'].rstrip('/')}/api/pause"
        headers = {"Content-Type": "application/json"}
        if self.run_token:
            headers["Authorization"] = f"Bearer {self.run_token}"
            headers["X-Run-Token"] = self.run_token
            headers["X-Admin-Token"] = self.run_token

        payload = {"reason": reason or "Pausa richiesta dal Coordinator"}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                return {"status": "success", "agent_id": agent_id, "is_paused": True, "message": f"Bot {agent_id} in pausa"}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def resume_agent(self, agent_id: str) -> Dict[str, Any]:
        """Invia un POST /api/resume all'agente specificato per ripristinarne l'attivita'."""
        cfg = self.agents_config.get(agent_id)
        if not cfg:
            return {"status": "error", "message": f"Agente '{agent_id}' inesistente"}

        url = f"{cfg['url'].rstrip('/')}/api/resume"
        headers = {}
        if self.run_token:
            headers["Authorization"] = f"Bearer {self.run_token}"
            headers["X-Run-Token"] = self.run_token
            headers["X-Admin-Token"] = self.run_token

        try:
            resp = requests.post(url, headers=headers, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                return {"status": "success", "agent_id": agent_id, "is_paused": False, "message": f"Bot {agent_id} riattivato"}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def emergency_stop_all(self, reason: str = "Circuit Breaker attivato dal Coordinator") -> Dict[str, Any]:
        """Invia /api/pause a tutti i bot simultaneamente (Circuit Breaker / Emergency Stop)."""
        logger.warning("🚨 EMERGENCY STOP su tutti i bot! Motivo: %s", reason)
        results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(self.pause_agent, aid, reason): aid
                for aid in self.agents_config.keys()
            }
            for fut in as_completed(futures):
                aid = futures[fut]
                try:
                    results[aid] = fut.result()
                except Exception as exc:
                    results[aid] = {"status": "error", "message": str(exc)}
        return results

    def resume_all(self) -> Dict[str, Any]:
        """Invia /api/resume a tutti i bot simultaneamente per riattivare l'ecosistema."""
        logger.info("🟢 Ripresa attivita' (resume_all) su tutti i bot.")
        results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(self.resume_agent, aid): aid
                for aid in self.agents_config.keys()
            }
            for fut in as_completed(futures):
                aid = futures[fut]
                try:
                    results[aid] = fut.result()
                except Exception as exc:
                    results[aid] = {"status": "error", "message": str(exc)}
        return results

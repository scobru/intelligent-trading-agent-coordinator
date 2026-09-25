"""
Gas Balancer per rete Base (L2).
Monitora costantemente il saldo di ETH nativo di tutti i sub-wallets dei 6 bot
e provvede al refuel automatico dal Master Treasury Wallet quando un agente scende sotto la riserva minima.
"""

import logging
from typing import Any, Dict, List, Optional
from web3 import Web3

import config
import db_utils

logger = logging.getLogger(__name__)

class GasBalancer:
    def __init__(self, w3: Optional[Web3] = None):
        self.w3 = w3
        self.min_reserve_eth = config.MIN_GAS_RESERVE_ETH  # Default 0.001 ETH
        self.warn_eth = config.GAS_WARN_ETH                # Default 0.0015 ETH
        self.refuel_amount_eth = config.REFUEL_AMOUNT_ETH  # Default 0.003 ETH
        self.auto_refuel = config.AUTO_REFUEL_GAS
        self.min_emergency_refuel_eth = 0.0005             # Soglia minima per refuel vitale d'emergenza

    def check_wallets_gas(
        self,
        agents_status: Dict[str, Dict[str, Any]],
        treasury_executor=None
    ) -> Dict[str, Any]:
        """Controlla i livelli di gas ETH di tutti i bot e avvia i refuel (dal Master o da altri bot donatori)."""
        wallet_reports: Dict[str, Dict[str, Any]] = {}
        refuels_performed = 0
        total_eth_sent = 0.0

        # 1. Rileva i saldi on-chain aggiornati per tutti i bot
        current_gas_balances = {}
        for agent_id, st in agents_status.items():
            wallet = st.get("wallet", "").strip()
            gas_eth = float(st.get("gas_eth", 0.0) or 0.0)

            # Query live on-chain se Web3 e indirizzo valido
            if self.w3 and wallet and Web3.is_address(wallet):
                try:
                    bal_wei = self.w3.eth.get_balance(Web3.to_checksum_address(wallet))
                    gas_eth = float(Web3.from_wei(bal_wei, "ether"))
                except Exception as exc:
                    logger.debug("Impossibile leggere balance ETH per %s: %s", agent_id, exc)

            current_gas_balances[agent_id] = gas_eth

            if gas_eth < self.min_reserve_eth:
                status = "CRITICAL_LOW"
            elif gas_eth < self.warn_eth:
                status = "WARN_LOW"
            else:
                status = "OK"

            wallet_reports[agent_id] = {
                "agent_id": agent_id,
                "name": st.get("name", agent_id),
                "wallet": wallet,
                "balance_eth": round(gas_eth, 6),
                "status": status,
                "refueled": False
            }

        # 2. Identifica i bot che necessitano di gas, prioritizzando chi ha saldo a 0
        needy_bots = [
            aid for aid, rep in wallet_reports.items()
            if rep["status"] in ("CRITICAL_LOW", "WARN_LOW") and rep["wallet"]
        ]
        needy_bots.sort(key=lambda aid: current_gas_balances[aid])

        # Se il refuel automatico è disattivato o non ci sono bot bisognosi, ritorna subito
        if not self.auto_refuel or not needy_bots or not treasury_executor:
            return {
                "wallets": list(wallet_reports.values()),
                "refuels_performed": 0,
                "total_eth_sent": 0.0
            }

        # 3. Saldo attuale Master Treasury
        treasury_eth = 0.0
        try:
            tbals = treasury_executor.get_treasury_balances()
            treasury_eth = float(tbals.get("eth", 0.0) or 0.0)
        except Exception:
            pass

        min_treasury_buffer = 0.0005  # Buffer di sicurezza per le commissioni di rete del Master

        for agent_id in needy_bots:
            item = wallet_reports[agent_id]
            recipient_wallet = item["wallet"]
            current_gas = current_gas_balances[agent_id]
            desired_refuel = self.refuel_amount_eth
            refueled = False

            # --- STRATEGIA 1: Refuel dalla Master Treasury (se ha balance disponibile) ---
            avail_master_eth = max(0.0, treasury_eth - min_treasury_buffer)
            if avail_master_eth >= self.min_emergency_refuel_eth:
                amount_to_send = round(min(desired_refuel, avail_master_eth), 5)
                try:
                    tx_hash = treasury_executor.transfer_eth(recipient_wallet, amount_to_send)
                    if tx_hash:
                        item["refueled"] = True
                        item["tx_hash"] = tx_hash
                        item["source"] = "master_treasury"
                        item["amount_eth"] = amount_to_send
                        refuels_performed += 1
                        total_eth_sent += amount_to_send
                        treasury_eth -= amount_to_send
                        current_gas_balances[agent_id] += amount_to_send
                        refueled = True
                        note = "Standard" if amount_to_send >= desired_refuel else "Parziale d'Emergenza"
                        db_utils.log_operation(
                            op_type="REFUEL_ETH",
                            amount=amount_to_send,
                            asset="ETH",
                            from_agent="master_treasury",
                            to_agent=agent_id,
                            tx_hash=tx_hash,
                            status="SUCCESS" if not (config.DRY_RUN or config.PAPER_TRADING) else "SIMULATED",
                            reason=f"Gas refuel {note}: saldo bot precedente {current_gas:.5f} ETH (Treasury residuo: {treasury_eth:.5f} ETH)."
                        )
                        logger.info("⛽ Refuel %s per %s: %.5f ETH inviati da master_treasury.",
                                    note, agent_id, amount_to_send)
                except Exception as exc:
                    logger.error("Errore durante refuel da master_treasury per %s: %s", agent_id, exc)
                    db_utils.log_error("GAS_REFUEL_MASTER_ERROR", str(exc), source=f"gas_balancer_{agent_id}")

            if refueled:
                continue

            # --- STRATEGIA 2: Cross-Bot Gas Sharing (Spostamento da un bot con surplus di ETH) ---
            # Trova il bot con il surplus di gas più alto
            donor_safety_floor = max(self.warn_eth, 0.0015) + 0.0005  # Conserva sempre una riserva minima al donatore
            best_donor_id = None
            max_donor_surplus = 0.0

            for other_id, other_gas in current_gas_balances.items():
                if other_id == agent_id:
                    continue
                surplus = other_gas - donor_safety_floor
                if surplus > max_donor_surplus:
                    max_donor_surplus = surplus
                    best_donor_id = other_id

            if best_donor_id and max_donor_surplus >= self.min_emergency_refuel_eth:
                donor_pk = config.get_agent_private_key(best_donor_id)
                amount_from_donor = round(min(desired_refuel, max_donor_surplus), 5)

                if donor_pk or config.DRY_RUN or config.PAPER_TRADING:
                    try:
                        tx_h = treasury_executor.transfer_eth_from_wallet(
                            from_private_key=donor_pk or "0x_dummy_pk",
                            to_address=recipient_wallet,
                            amount_eth=amount_from_donor
                        )
                        if tx_h:
                            item["refueled"] = True
                            item["tx_hash"] = tx_h
                            item["source"] = best_donor_id
                            item["amount_eth"] = amount_from_donor
                            refuels_performed += 1
                            total_eth_sent += amount_from_donor
                            current_gas_balances[best_donor_id] -= amount_from_donor
                            current_gas_balances[agent_id] += amount_from_donor
                            refueled = True
                            db_utils.log_operation(
                                op_type="REFUEL_ETH_CROSS_BOT",
                                amount=amount_from_donor,
                                asset="ETH",
                                from_agent=best_donor_id,
                                to_agent=agent_id,
                                tx_hash=tx_h,
                                status="SUCCESS" if not (config.DRY_RUN or config.PAPER_TRADING) else "SIMULATED",
                                reason=f"Cross-Bot Gas Sharing: {best_donor_id.upper()} finanzia gas a {agent_id.upper()} (saldo bot {current_gas:.5f} ETH)."
                            )
                            logger.info("⛽ Cross-Bot Gas Refuel: %.5f ETH trasferiti da %s a %s.",
                                        amount_from_donor, best_donor_id, agent_id)
                    except Exception as exc:
                        logger.error("Errore durante cross-bot gas refuel da %s a %s: %s", best_donor_id, agent_id, exc)
                        db_utils.log_error("GAS_REFUEL_CROSS_BOT_ERROR", str(exc), source=f"gas_balancer_{agent_id}")
                else:
                    msg = (
                        f"Bot donatore identificato: {best_donor_id.upper()} ha {current_gas_balances[best_donor_id]:.5f} ETH "
                        f"(surplus: {max_donor_surplus:.5f} ETH), ma per firmare il trasferimento automatico verso {agent_id.upper()} "
                        f"configurare AGENT_{best_donor_id.upper()}_PRIVATE_KEY (o SUB_AGENTS_PRIVATE_KEY) in .env."
                    )
                    logger.warning("⛽ %s", msg)
                    item["warning"] = msg

            if not refueled and not item.get("warning"):
                warn_msg = (
                    f"Impossibile rifornire {agent_id} (saldo: {current_gas:.5f} ETH): "
                    f"Master Treasury ha {treasury_eth:.5f} ETH e nessun altro bot ha surplus sufficiente (&ge; {donor_safety_floor:.4f} ETH)."
                )
                logger.warning("⛽ %s", warn_msg)
                item["warning"] = warn_msg

        return {
            "wallets": list(wallet_reports.values()),
            "refuels_performed": refuels_performed,
            "total_eth_sent": round(total_eth_sent, 5)
        }


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
        self.min_reserve_eth = config.MIN_GAS_RESERVE_ETH
        self.warn_eth = config.GAS_WARN_ETH
        self.refuel_amount_eth = config.REFUEL_AMOUNT_ETH
        self.auto_refuel = config.AUTO_REFUEL_GAS

    def check_wallets_gas(
        self,
        agents_status: Dict[str, Dict[str, Any]],
        treasury_executor=None
    ) -> Dict[str, Any]:
        """Controlla i livelli di gas ETH di tutti i bot e avvia i refuel se necessario."""
        wallet_reports: List[Dict[str, Any]] = []
        refuels_performed = 0
        total_eth_sent = 0.0

        for agent_id, st in agents_status.items():
            wallet = st.get("wallet", "").strip()
            gas_eth = st.get("gas_eth", 0.0)

            # Se abbiamo Web3 e un wallet valido, facciamo la query live on-chain
            if self.w3 and wallet and Web3.is_address(wallet):
                try:
                    bal_wei = self.w3.eth.get_balance(Web3.to_checksum_address(wallet))
                    gas_eth = float(Web3.from_wei(bal_wei, "ether"))
                except Exception as exc:
                    logger.debug("Impossibile leggere balance ETH per %s: %s", agent_id, exc)

            # Valutazione stato
            if gas_eth < self.min_reserve_eth:
                status = "CRITICAL_LOW"
            elif gas_eth < self.warn_eth:
                status = "WARN_LOW"
            else:
                status = "OK"

            item = {
                "agent_id": agent_id,
                "name": st.get("name", agent_id),
                "wallet": wallet,
                "balance_eth": round(gas_eth, 6),
                "status": status,
                "refueled": False
            }

            # Esecuzione refuel automatico se attivo e necessario
            if status in ("CRITICAL_LOW", "WARN_LOW") and self.auto_refuel and wallet and treasury_executor:
                if not config.DRY_RUN and not config.PAPER_TRADING:
                    try:
                        tx_hash = treasury_executor.transfer_eth(wallet, self.refuel_amount_eth)
                        if tx_hash:
                            item["refueled"] = True
                            item["tx_hash"] = tx_hash
                            refuels_performed += 1
                            total_eth_sent += self.refuel_amount_eth
                            db_utils.log_operation(
                                op_type="REFUEL_ETH",
                                amount=self.refuel_amount_eth,
                                asset="ETH",
                                from_agent="master_treasury",
                                to_agent=agent_id,
                                tx_hash=tx_hash,
                                status="SUCCESS",
                                reason=f"Gas refuel automatico: saldo precedente {gas_eth:.5f} ETH."
                            )
                    except Exception as exc:
                        logger.error("Errore durante refuel ETH per %s: %s", agent_id, exc)
                        db_utils.log_error("GAS_REFUEL_ERROR", str(exc), source=f"gas_balancer_{agent_id}")
                else:
                    # Simulazione in DRY_RUN / PAPER
                    item["refueled"] = True
                    item["tx_hash"] = "0x_simulated_gas_refuel_hash"
                    refuels_performed += 1
                    total_eth_sent += self.refuel_amount_eth
                    db_utils.log_operation(
                        op_type="REFUEL_ETH",
                        amount=self.refuel_amount_eth,
                        asset="ETH",
                        from_agent="master_treasury",
                        to_agent=agent_id,
                        tx_hash="0x_simulated",
                        status="SIMULATED",
                        reason=f"[SIMULATO] Gas refuel: saldo precedente {gas_eth:.5f} ETH."
                    )

            wallet_reports.append(item)

        return {
            "wallets": wallet_reports,
            "refuels_performed": refuels_performed,
            "total_eth_sent": round(total_eth_sent, 5)
        }

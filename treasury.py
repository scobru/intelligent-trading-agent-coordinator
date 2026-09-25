"""
Modulo Treasury: Gestione fondi on-chain e simulatore Paper Treasury.
Interagisce con rete Base per trasferimenti di USDC ed ETH,
mantenendo un registro coerente in paper trading quando attivo.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional
from eth_account import Account
from web3 import Web3

import config
import db_utils

logger = logging.getLogger(__name__)

# ABI minimale ERC-20
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf",
     "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
    {"constant": False, "inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}],
     "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"}
]

class Treasury:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(config.BASE_RPC_URL))
        self.master_address = config.MASTER_WALLET_ADDRESS
        self.private_key = config.MASTER_PRIVATE_KEY
        self.usdc_address = Web3.to_checksum_address(config.USDC_ADDRESS) if config.USDC_ADDRESS else None

        if self.usdc_address:
            self.usdc_contract = self.w3.eth.contract(address=self.usdc_address, abi=ERC20_ABI)
        else:
            self.usdc_contract = None

        self.paper_file = Path(config.PAPER_ACCOUNT_FILE)
        self._init_paper_state()

    def _init_paper_state(self) -> None:
        """Inizializza il file paper_treasury.json se in modalita' paper trading."""
        if not config.PAPER_TRADING:
            return
        self.paper_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.paper_file.exists():
            initial_state = {
                "treasury_usdc": config.PAPER_START_USDC,
                "virtual_allocations": {
                    "yield": 3500.0,
                    "dca": 2500.0,
                    "neutral": 1500.0,
                    "lp": 1500.0,
                    "perp": 700.0,
                    "degen": 300.0
                },
                "total_rebalances_count": 0
            }
            with open(self.paper_file, "w", encoding="utf-8") as f:
                json.dump(initial_state, f, indent=2)

    def get_paper_state(self) -> Dict[str, Any]:
        """Legge lo stato virtuale paper."""
        if not self.paper_file.exists():
            self._init_paper_state()
        try:
            with open(self.paper_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"treasury_usdc": 0.0, "virtual_allocations": {}}

    def save_paper_state(self, state: Dict[str, Any]) -> None:
        """Salva lo stato virtuale paper."""
        with open(self.paper_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def get_treasury_balances(self) -> Dict[str, float]:
        """Ritorna i saldi di cassa centrali (USDC ed ETH) della Master Treasury."""
        if config.PAPER_TRADING:
            pst = self.get_paper_state()
            return {
                "eth": 1.5,  # ETH simulato abbondante per gas
                "usdc": float(pst.get("treasury_usdc", config.PAPER_START_USDC))
            }

        eth_bal = 0.0
        usdc_bal = 0.0

        if self.master_address and Web3.is_address(self.master_address):
            c_addr = Web3.to_checksum_address(self.master_address)
            try:
                eth_wei = self.w3.eth.get_balance(c_addr)
                eth_bal = float(Web3.from_wei(eth_wei, "ether"))
            except Exception as e:
                logger.error("Errore lettura ETH Master Wallet: %s", e)

            if self.usdc_contract:
                try:
                    raw_usdc = self.usdc_contract.functions.balanceOf(c_addr).call()
                    usdc_bal = float(raw_usdc) / 1e6
                except Exception as e:
                    logger.error("Errore lettura USDC Master Wallet: %s", e)

        return {"eth": round(eth_bal, 5), "usdc": round(usdc_bal, 2)}

    def transfer_eth(self, to_address: str, amount_eth: float) -> Optional[str]:
        """Invia ETH nativo su Base (utilizzato dal Gas Balancer)."""
        if config.PAPER_TRADING or config.DRY_RUN:
            logger.info("[PAPER/DRY-RUN] Trasferiti %.4f ETH a %s", amount_eth, to_address)
            return "0x_simulated_eth_tx"

        if not self.private_key or not self.master_address:
            raise ValueError("MASTER_PRIVATE_KEY o MASTER_WALLET_ADDRESS non configurati.")

        account = Account.from_key(self.private_key)
        to_check = Web3.to_checksum_address(to_address)
        val_wei = Web3.to_wei(amount_eth, "ether")

        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        gas_price = self.w3.eth.gas_price

        tx = {
            "to": to_check,
            "value": val_wei,
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": config.CHAIN_ID
        }

        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        h_str = tx_hash.hex()
        logger.info("Trasferimento ETH completato: %s (tx: %s)", to_address, h_str)
        return h_str

    def transfer_usdc(self, to_address: str, amount_usd: float) -> Optional[str]:
        """Trasferisce USDC su Base L2."""
        if config.PAPER_TRADING:
            pst = self.get_paper_state()
            current_usdc = pst.get("treasury_usdc", 0.0)
            pst["treasury_usdc"] = max(0.0, current_usdc - amount_usd)
            pst["total_rebalances_count"] = pst.get("total_rebalances_count", 0) + 1
            self.save_paper_state(pst)
            logger.info("[PAPER] Trasferiti $%.2f USDC a %s", amount_usd, to_address)
            return "0x_simulated_usdc_tx"

        if config.DRY_RUN:
            logger.info("[DRY-RUN] Simulazione transfer $%.2f USDC a %s", amount_usd, to_address)
            return "0x_dry_run_usdc_tx"

        if not self.private_key or not self.master_address or not self.usdc_contract:
            raise ValueError("Configurazione on-chain incompleta per transfer USDC.")

        account = Account.from_key(self.private_key)
        to_check = Web3.to_checksum_address(to_address)
        amount_raw = int(amount_usd * 1e6)

        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        fn = self.usdc_contract.functions.transfer(to_check, amount_raw)
        gas_est = fn.estimate_gas({"from": account.address})

        tx = fn.build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": int(gas_est * 1.2),
            "gasPrice": self.w3.eth.gas_price,
            "chainId": config.CHAIN_ID
        })

        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        h_str = tx_hash.hex()
        logger.info("Trasferimento USDC completato verso %s: %s", to_address, h_str)
        return h_str

    def execute_rebalance_action(self, action: Dict[str, Any], agents_status: Dict[str, Any]) -> bool:
        """Esegue una specifica azione calcolata dal CapitalAllocator."""
        from_id = action.get("from_agent")
        to_id = action.get("to_agent")
        amount = float(action.get("amount_usd", 0.0))
        reason = action.get("reason", "")

        to_wallet = agents_status.get(to_id, {}).get("wallet", "")
        if not to_wallet:
            to_wallet = config.AGENTS.get(to_id, {}).get("wallet", "")

        logger.info("Esecuzione azione %s: $%.2f da %s a %s (%s)",
                    action.get("action"), amount, from_id, to_id, reason)

        try:
            tx_h = self.transfer_usdc(to_wallet or "0x_sub_wallet_placeholder", amount)
            status_str = "SIMULATED" if (config.PAPER_TRADING or config.DRY_RUN) else "SUCCESS"
            db_utils.log_operation(
                op_type=action.get("action", "TRANSFER_USDC"),
                amount=amount,
                asset="USDC",
                from_agent=from_id,
                to_agent=to_id,
                tx_hash=tx_h,
                status=status_str,
                reason=reason
            )
            return True
        except Exception as exc:
            logger.error("Errore esecuzione rebalance action: %s", exc)
            db_utils.log_error("REBALANCE_EXECUTION_ERROR", str(exc), source="treasury")
            return False

"""
Modulo Treasury: Gestione fondi on-chain e simulatore Paper Treasury.
Interagisce con rete Base per trasferimenti di USDC ed ETH,
mantenendo un registro coerente in paper trading quando attivo.
"""

import json
import logging
import os
import time
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

    def get_treasury_balances(self, eth_price: float = 0.0) -> Dict[str, float]:
        """Ritorna i saldi di cassa centrali (USDC ed ETH) della Master Treasury, con controvalore USD."""
        if config.PAPER_TRADING:
            pst = self.get_paper_state()
            eth_bal = 1.5  # ETH simulato abbondante per gas
            usdc_bal = float(pst.get("treasury_usdc", config.PAPER_START_USDC))
        else:
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

        eth_usd = round(eth_bal * eth_price, 2) if eth_price > 0 else 0.0
        total_usd = round(usdc_bal + eth_usd, 2)

        return {
            "eth": round(eth_bal, 5),
            "usdc": round(usdc_bal, 2),
            "eth_price": round(eth_price, 2),
            "eth_usd": eth_usd,
            "total_usd": total_usd
        }

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
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        h_str = tx_hash.hex()
        logger.info("Trasferimento ETH completato: %s (tx: %s)", to_address, h_str)
        return h_str

    def transfer_eth_from_wallet(self, from_private_key: str, to_address: str, amount_eth: float) -> Optional[str]:
        """Invia ETH nativo da uno specifico wallet subordinato a un altro (Cross-Bot Gas Sharing)."""
        if config.PAPER_TRADING or config.DRY_RUN:
            logger.info("[PAPER/DRY-RUN] Trasferiti %.5f ETH tra sub-wallets -> %s", amount_eth, to_address)
            return "0x_simulated_cross_bot_eth_tx"

        if not from_private_key:
            raise ValueError("Chiave privata del wallet mittente non configurata.")

        account = Account.from_key(from_private_key)
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

        signed = self.w3.eth.account.sign_transaction(tx, from_private_key)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        h_str = tx_hash.hex()
        logger.info("Trasferimento gas tra bot completato: %s -> %s (tx: %s)", account.address, to_address, h_str)
        return h_str

    def transfer_usdc(self, to_address: str, amount_usd: float, sender_private_key: Optional[str] = None) -> Optional[str]:
        """Trasferisce USDC su Base L2 dalla Master Treasury o da un sub-account fornito."""
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

        priv_key = sender_private_key or self.private_key
        if not priv_key or not self.usdc_contract:
            raise ValueError("Configurazione on-chain incompleta per transfer USDC (chiave privata o contratto mancante).")

        account = Account.from_key(priv_key)
        to_check = Web3.to_checksum_address(to_address)
        amount_raw = int(amount_usd * 1e6)

        # Verifica saldo on-chain effettivo per evitare revert dovuti ad arrotondamenti float
        actual_raw = self.usdc_contract.functions.balanceOf(account.address).call()
        if amount_raw > actual_raw:
            if amount_raw - actual_raw <= 50_000:  # tolleranza fino a 0.05$ di scarto float
                amount_raw = actual_raw
            else:
                raise ValueError(f"Saldo USDC on-chain insufficiente ({actual_raw / 1e6:.6f} USDC < {amount_usd:.6f} USDC)")

        if amount_raw <= 0:
            logger.warning("Importo USDC da trasferire nullo o negativo (%d raw). Operazione saltata.", amount_raw)
            return None

        nonce = self.w3.eth.get_transaction_count(account.address, "pending")
        fn = self.usdc_contract.functions.transfer(to_check, amount_raw)
        gas_est = fn.estimate_gas({"from": account.address})

        tx = fn.build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": int(gas_est * 1.25),
            "gasPrice": self.w3.eth.gas_price,
            "chainId": config.CHAIN_ID
        })

        signed = self.w3.eth.account.sign_transaction(tx, priv_key)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
        h_str = tx_hash.hex()
        logger.info("Trasferimento USDC completato da %s verso %s: %s", account.address, to_address, h_str)
        return h_str

    def execute_rebalance_action(self, action: Dict[str, Any], agents_status: Dict[str, Any], agent_client: Optional[Any] = None) -> bool:
        """Esegue una specifica azione calcolata dal CapitalAllocator."""
        from_id = action.get("from_agent")
        to_id = action.get("to_agent")
        amount = float(action.get("amount_usd", 0.0))
        reason = action.get("reason", "")

        to_wallet = agents_status.get(to_id, {}).get("wallet", "")
        if not to_wallet:
            to_wallet = config.AGENTS.get(to_id, {}).get("wallet", "")

        if not to_wallet:
            logger.warning("Wallet destinatario non trovato per agente '%s'. Azione saltata.", to_id)
            return False

        logger.info("Esecuzione azione %s: $%.2f da %s a %s (%s)",
                    action.get("action"), amount, from_id, to_id, reason)

        # Modalita' PAPER TRADING: aggiorna il bilancio virtuale tra allocazioni
        if config.PAPER_TRADING:
            pst = self.get_paper_state()
            allocs = pst.get("virtual_allocations", {})
            if from_id == "master_treasury":
                pst["treasury_usdc"] = max(0.0, float(pst.get("treasury_usdc", 0.0)) - amount)
                if to_id in allocs:
                    allocs[to_id] = allocs[to_id] + amount
            else:
                if from_id in allocs:
                    allocs[from_id] = max(0.0, allocs[from_id] - amount)
                if to_id in allocs:
                    allocs[to_id] = allocs[to_id] + amount
                elif to_id == "master_treasury":
                    pst["treasury_usdc"] = float(pst.get("treasury_usdc", 0.0)) + amount
            pst["total_rebalances_count"] = pst.get("total_rebalances_count", 0) + 1
            self.save_paper_state(pst)
            db_utils.log_operation(
                op_type=action.get("action", "TRANSFER_USDC"),
                amount=amount,
                asset="USDC",
                from_agent=from_id,
                to_agent=to_id,
                tx_hash="0x_paper_rebalance",
                status="SIMULATED",
                reason=reason
            )
            return True

        if config.DRY_RUN:
            logger.info("[DRY-RUN] Simulazione azione %s: $%.2f (%s -> %s)",
                        action.get("action"), amount, from_id, to_id)
            db_utils.log_operation(
                op_type=action.get("action", "TRANSFER_USDC"),
                amount=amount,
                asset="USDC",
                from_agent=from_id,
                to_agent=to_id,
                tx_hash="0x_dry_run_rebalance",
                status="DRY_RUN",
                reason=f"[DRY-RUN] {reason}"
            )
            return True

        # LIVE TRADING ON-CHAIN
        if from_id == "master_treasury":
            sender_pk = self.private_key
            sender_name = "Master Treasury"
        else:
            sender_pk = config.get_agent_private_key(from_id)
            sender_name = f"Sub-Agent {from_id.upper()}"

        if not sender_pk:
            logger.info("ℹ️ Ribilanciamento %s: nessuna chiave privata configurata per %s. Azione registrata come ADVISORY.",
                        action.get("action"), from_id)
            db_utils.log_operation(
                op_type=action.get("action", "REBALANCE_ADVISORY"),
                amount=amount,
                asset="USDC",
                from_agent=from_id,
                to_agent=to_id,
                tx_hash="N/A_ADVISORY",
                status="RECOMMENDED",
                reason=f"[ADVISORY] {reason}"
            )
            return True

        # Verifica saldo USDC e Gas del mittente per evitare revert on-chain
        try:
            account = Account.from_key(sender_pk)
            eth_wei = self.w3.eth.get_balance(account.address)
            if eth_wei < Web3.to_wei(0.0003, "ether"):
                warn_msg = f"{sender_name} ({account.address}) ha ETH gas insufficiente per il transfer USDC."
                logger.warning("⚠️ %s", warn_msg)
                return False

            raw_usdc = self.usdc_contract.functions.balanceOf(account.address).call()
            avail_usdc = float(raw_usdc) / 1e6
            is_sweep = action.get("action") in ("SWEEP_IDLE_FUNDS", "WITHDRAW_TO_SAFE_HAVEN")
            min_reb = min(config.MIN_REBALANCE_USD, getattr(config, "MIN_SWEEP_IDLE_USD", 1.0)) if is_sweep else min(config.MIN_REBALANCE_USD, 5.0)

            # Se il mittente è un sub-agent e non ha abbastanza USDC liquidi nel wallet:
            # tenta di liberare fondi vendendo token (es. Degen) o chiudendo/ritirando da Gate (es. Perp)
            if from_id != "master_treasury" and avail_usdc < amount:
                client = agent_client or getattr(self, "agent_client", None)
                if client:
                    needed = round(amount - avail_usdc, 2)
                    logger.info("ℹ️ %s ha solo $%.2f USDC liquidi (richiesti: $%.2f). Invio richiesta di svincolo fondi ($%.2f)...",
                                sender_name, avail_usdc, amount, needed)
                    release_res = client.release_agent_funds(from_id, needed)
                    logger.info("   -> Risultato svincolo fondi da %s: %s", from_id, release_res)
                    time.sleep(3)  # Attesa conferma transazione e sincronizzazione on-chain
                    raw_usdc = self.usdc_contract.functions.balanceOf(account.address).call()
                    avail_usdc = float(raw_usdc) / 1e6

            if avail_usdc < min_reb:
                warn_msg = (
                    f"{sender_name} ha USDC insufficienti per finanziare {to_id} "
                    f"(disponibili: ${avail_usdc:.2f}, richiesti: ${amount:.2f})."
                )
                logger.warning("⚠️ %s", warn_msg)
                db_utils.log_operation(
                    op_type=action.get("action", "REBALANCE_SKIPPED"),
                    amount=amount,
                    asset="USDC",
                    from_agent=from_id,
                    to_agent=to_id,
                    tx_hash="N/A_INSUFFICIENT_FUNDS",
                    status="SKIPPED",
                    reason=warn_msg
                )
                return False

            actual_amount = min(amount, avail_usdc)
            tx_h = self.transfer_usdc(to_wallet, actual_amount, sender_private_key=sender_pk)
            db_utils.log_operation(
                op_type=action.get("action", "TRANSFER_USDC"),
                amount=actual_amount,
                asset="USDC",
                from_agent=from_id,
                to_agent=to_id,
                tx_hash=tx_h,
                status="SUCCESS",
                reason=reason
            )
            return True
        except Exception as exc:
            logger.error("Errore esecuzione rebalance action (%s -> %s): %s", from_id, to_id, exc)
            db_utils.log_error("REBALANCE_EXECUTION_ERROR", str(exc), source="treasury")
            return False

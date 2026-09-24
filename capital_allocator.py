"""
Algoritmo di Allocazione e Ribilanciamento del Capitale.
Determina i pesi target in base al regime di mercato e genera piani di trasferimento
tra gli agenti per riallineare le quote operative (profit sweeping, liquidity injections, safe haven).
"""

import logging
from typing import Any, Dict, List

import config

logger = logging.getLogger(__name__)

class CapitalAllocator:
    def __init__(self):
        self.target_matrices = config.REGIME_TARGET_WEIGHTS
        self.min_rebalance_usd = config.MIN_REBALANCE_USD
        self.rebalance_threshold_pct = config.REBALANCE_THRESHOLD_PCT

    def compute_allocation_plan(
        self,
        regime: str,
        agents_status: Dict[str, Dict[str, Any]],
        treasury_cash_usd: float = 0.0
    ) -> Dict[str, Any]:
        """Calcola l'allocazione target, gli scostamenti correnti e le azioni di ribilanciamento."""
        weights = self.target_matrices.get(regime, self.target_matrices["BALANCED"])

        # Calcolo del Net Worth consolidato (somma equity dei 6 bot + cash master treasury)
        agents_equity = {}
        total_agents_equity = 0.0
        for agent_id, st in agents_status.items():
            eq = float(st.get("equity_usd", 0.0) or st.get("balance_usd", 0.0) or 0.0)
            agents_equity[agent_id] = eq
            total_agents_equity += eq

        total_net_worth = total_agents_equity + treasury_cash_usd

        # Se il portafoglio e' a zero (primo avvio), evitiamo divisioni per zero
        if total_net_worth <= 0:
            return {
                "regime": regime,
                "total_net_worth_usd": 0.0,
                "rebalance_needed": False,
                "allocations": {},
                "actions": []
            }

        allocations = {}
        overweight = []
        underweight = []

        for agent_id, target_pct in weights.items():
            actual_usd = agents_equity.get(agent_id, 0.0)
            actual_pct = actual_usd / total_net_worth if total_net_worth > 0 else 0.0
            target_usd = total_net_worth * target_pct
            drift_usd = actual_usd - target_usd
            drift_pct = (actual_pct - target_pct) * 100.0

            allocations[agent_id] = {
                "target_pct": round(target_pct, 4),
                "actual_pct": round(actual_pct, 4),
                "target_usd": round(target_usd, 2),
                "actual_usd": round(actual_usd, 2),
                "drift_usd": round(drift_usd, 2),
                "drift_pct": round(drift_pct, 2)
            }

            if drift_usd > self.min_rebalance_usd and drift_pct > self.rebalance_threshold_pct:
                overweight.append((agent_id, drift_usd))
            elif drift_usd < -self.min_rebalance_usd and drift_pct < -self.rebalance_threshold_pct:
                underweight.append((agent_id, abs(drift_usd)))

        actions: List[Dict[str, Any]] = []

        # 1. Regola Speciale per Alta Volatilita' / Panic: Svuota LP verso Yield
        if regime in ("HIGH_VOLATILITY", "BEAR_PANIC") and agents_equity.get("lp", 0.0) > self.min_rebalance_usd:
            lp_bal = agents_equity.get("lp", 0.0)
            actions.append({
                "action": "WITHDRAW_TO_SAFE_HAVEN",
                "from_agent": "lp",
                "to_agent": "yield",
                "amount_usd": round(lp_bal, 2),
                "asset": "USDC",
                "reason": f"Regime {regime}: Ritiro liquidita' LP concentrata per azzerare Impermanent Loss."
            })

        # 2. Profit Sweeping da bot speculativi (Degen o Perp) verso la Tesoreria / Yield
        for agent_id, surplus in overweight:
            if agent_id in ("degen", "perp"):
                target_dest = "yield"
                actions.append({
                    "action": "SWEEP_PROFIT",
                    "from_agent": agent_id,
                    "to_agent": target_dest,
                    "amount_usd": round(surplus, 2),
                    "asset": "USDC",
                    "reason": f"Sweep dei profitti in eccesso da {agent_id.upper()} verso {target_dest.upper()}."
                })

        # 3. Rebalancing standard tra surplus e deficit
        # Se abbiamo liquidita' inattiva in Yield o in Master Treasury, finanziamo i bot sottopesati (es. DCA)
        for agent_id, deficit in underweight:
            # Non finanziare bot a rischio se siamo in Panic
            if regime == "BEAR_PANIC" and agent_id in ("degen", "lp"):
                continue

            yield_surplus = allocations.get("yield", {}).get("drift_usd", 0.0)
            source = "yield" if yield_surplus > self.min_rebalance_usd else "master_treasury"

            amount_to_fund = min(deficit, 1000.0)  # Cap conservativo per transazione
            if amount_to_fund >= self.min_rebalance_usd:
                actions.append({
                    "action": "REBALANCE_FUND",
                    "from_agent": source,
                    "to_agent": agent_id,
                    "amount_usd": round(amount_to_fund, 2),
                    "asset": "USDC",
                    "reason": f"Ribilanciamento capitale: {source.upper()} finanzia {agent_id.upper()} (deficit: ${deficit:.2f})."
                })

        rebalance_needed = len(actions) > 0

        return {
            "regime": regime,
            "total_net_worth_usd": round(total_net_worth, 2),
            "rebalance_needed": rebalance_needed,
            "allocations": allocations,
            "actions": actions
        }

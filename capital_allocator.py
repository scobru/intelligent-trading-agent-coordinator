"""
Algoritmo di Allocazione e Ribilanciamento del Capitale.
Determina i pesi target in base al regime di mercato e genera piani di trasferimento
tra gli agenti per riallineare le quote operative (profit sweeping, liquidity injections, safe haven).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)

class CapitalAllocator:
    def __init__(self):
        self.target_matrices = config.REGIME_TARGET_WEIGHTS
        self.min_rebalance_usd = config.MIN_REBALANCE_USD
        self.rebalance_threshold_pct = config.REBALANCE_THRESHOLD_PCT
        self.min_viable_caps = getattr(config, "AGENT_MIN_VIABLE_CAPITAL", {
            "neutral": 150.0,
            "lp": 50.0,
            "perp": 15.0,
            "degen": 15.0,
            "dca": 10.0,
            "yield": 5.0
        })
        self.enable_pruning = getattr(config, "ENABLE_CAPITAL_PRUNING", True)
        self.enable_idle_sweep = getattr(config, "ENABLE_IDLE_CAPITAL_SWEEP", True)

    def adjust_weights_for_viability(
        self,
        base_weights: Dict[str, float],
        total_net_worth: float,
        agents_status: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Tuple[Dict[str, float], List[str]]:
        """
        Adatta i pesi target in base alle soglie minime di capitale operativo di ciascun bot.
        Se un bot riceverebbe un capitale inferiore alla sua soglia minima operativa
        (es. Neutral < $150), e non ha posizioni attive né saldo sufficiente,
        il suo peso viene azzerato e ridistribuito proporzionalmente sulle altre strategie attive.
        I bot già operativi con posizioni aperte o saldo >= soglia (es. Perp) vengono mantenuti attivi.
        """
        if not self.enable_pruning or total_net_worth <= 0:
            return dict(base_weights), []

        weights = {k: float(v) for k, v in base_weights.items()}
        pruned_notes: List[str] = []

        max_iterations = len(weights)
        for _ in range(max_iterations):
            below_threshold = []
            for agent_id, w in weights.items():
                if w <= 0.0:
                    continue
                min_cap = self.min_viable_caps.get(agent_id, 0.0)
                target_usd = total_net_worth * w
                if target_usd < min_cap:
                    shortfall = min_cap - target_usd
                    st = agents_status.get(agent_id, {}) if agents_status else {}
                    pos_cnt = int(st.get("positions_count", 0))
                    actual_usd = float(st.get("equity_usd", 0.0) or st.get("balance_usd", 0.0) or 0.0)
                    is_active_or_funded = (pos_cnt > 0 or actual_usd >= min_cap) and (min_cap <= total_net_worth)

                    below_threshold.append((agent_id, w, target_usd, min_cap, shortfall, is_active_or_funded))

            if not below_threshold:
                break

            active_agents = [aid for aid, w in weights.items() if w > 0.0]
            if len(active_agents) <= 1:
                break

            # Se tutti gli agenti sotto soglia sono già attivi/finanziati (es. Perp con trade aperto),
            # aumentiamo il loro peso al minimo sostenibile prelevando da Yield o altre strategie capienti
            prunable = [item for item in below_threshold if not item[5]]
            if not prunable:
                # Tutti i bot sotto soglia hanno posizioni o capitale sufficiente: adeguamento pesi
                for item in below_threshold:
                    aid, w, target_usd, min_cap, _, _ = item
                    needed_w = min_cap / total_net_worth
                    weights[aid] = max(weights[aid], needed_w)
                break

            # Chi ha un min_cap > total_net_worth non potrà mai essere finanziato dal portafoglio attuale
            impossible = [item for item in prunable if item[3] > total_net_worth]
            if impossible:
                target_to_prune = sorted(impossible, key=lambda x: x[3], reverse=True)[0]
            else:
                target_to_prune = sorted(prunable, key=lambda x: x[2] / max(x[3], 0.01))[0]

            agent_to_prune = target_to_prune[0]
            pruned_w = weights[agent_to_prune]
            weights[agent_to_prune] = 0.0
            note = (
                f"{agent_to_prune.upper()} disattivato: target ${target_to_prune[2]:.2f} "
                f"< minimo operativo ${target_to_prune[3]:.0f} (portafoglio: ${total_net_worth:.2f})"
            )
            pruned_notes.append(note)
            logger.info("   [CAPITAL PRUNING] %s", note)

            # Ridistribuisci proporzionalmente tra i rimanenti con peso > 0
            remaining_sum = sum(w for aid, w in weights.items() if aid != agent_to_prune and w > 0.0)
            if remaining_sum > 0:
                for aid in weights:
                    if weights[aid] > 0.0:
                        weights[aid] += (weights[aid] / remaining_sum) * pruned_w
            elif "yield" in weights:
                weights["yield"] = 1.0

        total_w = sum(weights.values())
        if total_w > 0:
            for aid in weights:
                weights[aid] = round(weights[aid] / total_w, 4)

        return weights, pruned_notes

    def compute_allocation_plan(
        self,
        regime: str,
        agents_status: Dict[str, Dict[str, Any]],
        treasury_cash_usd: float = 0.0,
        dynamic_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """Calcola l'allocazione target, gli scostamenti correnti e le azioni di ribilanciamento."""
        raw_weights = dynamic_weights or self.target_matrices.get(regime, self.target_matrices["BALANCED"])

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
                "actions": [],
                "pruned_notes": []
            }

        # Applica il filtro di sostenibilità operativa / pruning del capitale (con awareness dello stato attivo)
        weights, pruned_notes = self.adjust_weights_for_viability(raw_weights, total_net_worth, agents_status=agents_status)

        allocations = {}
        overweight = []
        underweight = []

        for agent_id, target_pct in weights.items():
            actual_usd = agents_equity.get(agent_id, 0.0)
            actual_pct = actual_usd / total_net_worth if total_net_worth > 0 else 0.0
            target_usd = total_net_worth * target_pct
            drift_usd = actual_usd - target_usd
            drift_pct = (actual_pct - target_pct) * 100.0

            min_cap = self.min_viable_caps.get(agent_id, 0.0)
            is_pruned = (target_pct == 0.0 and raw_weights.get(agent_id, 0.0) > 0.0)
            is_viable = (target_usd >= min_cap or target_usd == 0.0)

            allocations[agent_id] = {
                "target_pct": round(target_pct, 4),
                "actual_pct": round(actual_pct, 4),
                "target_usd": round(target_usd, 2),
                "actual_usd": round(actual_usd, 2),
                "drift_usd": round(drift_usd, 2),
                "drift_pct": round(drift_pct, 2),
                "min_viable_usd": min_cap,
                "pruned": is_pruned,
                "is_viable": is_viable
            }

            if drift_usd > self.min_rebalance_usd and drift_pct > self.rebalance_threshold_pct:
                overweight.append((agent_id, drift_usd))
            elif drift_usd < -self.min_rebalance_usd and drift_pct < -self.rebalance_threshold_pct:
                underweight.append((agent_id, abs(drift_usd)))

        actions: List[Dict[str, Any]] = []
        handled_overweight = set()

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
            handled_overweight.add("lp")

        # 2. Sweeping di profitti o recupero di capitale inerte (Idle Capital Recovery)
        # Se un bot è sovrappesato:
        # a) se il suo target è 0.0 o se è inattivo con capitale sotto la soglia minima -> SWEEP_IDLE_FUNDS
        # b) se è degen o perp in surplus di profitto -> SWEEP_PROFIT
        for agent_id, surplus in overweight:
            if agent_id in handled_overweight:
                continue

            st = agents_status.get(agent_id, {})
            pos_cnt = int(st.get("positions_count", 0))
            actual_usd = agents_equity.get(agent_id, 0.0)
            min_cap = self.min_viable_caps.get(agent_id, 0.0)
            tgt_usd = allocations.get(agent_id, {}).get("target_usd", 0.0)

            is_idle_sub_threshold = (pos_cnt == 0 and actual_usd < min_cap)
            is_zero_target_idle = (tgt_usd == 0.0 and pos_cnt == 0)

            if is_zero_target_idle or is_idle_sub_threshold:
                # Destinazione: bot con il deficit più elevato tra quelli attivi, altrimenti Yield o Master Treasury
                target_dest = "yield"
                if underweight:
                    valid_under = [u for u in underweight if allocations.get(u[0], {}).get("target_usd", 0.0) > 0]
                    if valid_under:
                        target_dest = sorted(valid_under, key=lambda x: x[1], reverse=True)[0][0]

                actions.append({
                    "action": "SWEEP_IDLE_FUNDS",
                    "from_agent": agent_id,
                    "to_agent": target_dest,
                    "amount_usd": round(surplus, 2),
                    "asset": "USDC",
                    "reason": (
                        f"Recupero capitale inerte da {agent_id.upper()}: saldo attuale ${actual_usd:.2f} "
                        f"insufficiente per operare (minimo ${min_cap:.0f}, target $0). Spostamento a {target_dest.upper()}."
                    )
                })
                handled_overweight.add(agent_id)
            elif agent_id in ("degen", "perp"):
                target_dest = "yield"
                actions.append({
                    "action": "SWEEP_PROFIT",
                    "from_agent": agent_id,
                    "to_agent": target_dest,
                    "amount_usd": round(surplus, 2),
                    "asset": "USDC",
                    "reason": f"Sweep dei profitti in eccesso da {agent_id.upper()} verso {target_dest.upper()}."
                })
                handled_overweight.add(agent_id)

        # 3. Rebalancing standard tra surplus e deficit
        # Se abbiamo liquidita' inattiva in Master Treasury o in bot in surplus non ancora gestiti, finanziamo i bot sottopesati
        for agent_id, deficit in underweight:
            # Calcola quanto deficit è già stato coperto da sweep precedenti destinati a questo agente
            already_funded = sum(a.get("amount_usd", 0.0) for a in actions if a.get("to_agent") == agent_id)
            remaining_deficit = max(0.0, deficit - already_funded)
            if remaining_deficit < self.min_rebalance_usd:
                continue

            # Non finanziare bot a rischio se siamo in Panic
            if regime == "BEAR_PANIC" and agent_id in ("degen", "lp"):
                continue

            # Non finanziare bot che sono stati potati a target 0
            if allocations.get(agent_id, {}).get("target_usd", 0.0) <= 0.0:
                continue

            # Priorità della sorgente:
            # 1. Master Treasury se ha saldo disponibile
            # 2. Altrimenti, l'agente con il surplus più cospicuo tra quelli non ancora gestiti
            source = None
            remaining_overweight = [o for o in overweight if o[0] not in handled_overweight]

            if treasury_cash_usd >= 5.0:
                source = "master_treasury"
                amount_to_fund = min(remaining_deficit, treasury_cash_usd)
            elif remaining_overweight:
                sorted_over = sorted(remaining_overweight, key=lambda x: x[1], reverse=True)
                source = sorted_over[0][0]
                amount_to_fund = min(remaining_deficit, sorted_over[0][1])
            else:
                # Nessuna sorgente con liquidità disponibile per finanziare questo deficit
                continue

            min_threshold = min(self.min_rebalance_usd, 5.0) if source == "master_treasury" else self.min_rebalance_usd
            if amount_to_fund >= min_threshold:
                actions.append({
                    "action": "REBALANCE_FUND",
                    "from_agent": source,
                    "to_agent": agent_id,
                    "amount_usd": round(amount_to_fund, 2),
                    "asset": "USDC",
                    "reason": f"Ribilanciamento capitale: {source.upper()} finanzia {agent_id.upper()} (deficit residuo: ${remaining_deficit:.2f})."
                })
                if source != "master_treasury":
                    handled_overweight.add(source)

        rebalance_needed = len(actions) > 0

        return {
            "regime": regime,
            "total_net_worth_usd": round(total_net_worth, 2),
            "rebalance_needed": rebalance_needed,
            "allocations": allocations,
            "actions": actions,
            "pruned_notes": pruned_notes
        }

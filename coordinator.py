"""
Master Coordinator Loop: Il cervello orchestratore dell'ecosistema ITA su Base.
Esegue periodicamente i controlli di telemetria, regime macro, gestione del rischio,
gas balancing, ribilanciamento dei capitali e trigger dei cicli degli agenti.
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict

import config
import db_utils
from agent_client import AgentClient
from ai_strategist import AiStrategist
from capital_allocator import CapitalAllocator
from gas_balancer import GasBalancer
from regime_detector import RegimeDetector
from risk_engine import RiskEngine
from treasury import Treasury

# Configurazione UTF-8 universale (Windows e Linux Docker)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Configurazione logging con flush immediato su sys.stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("coordinator")

class Coordinator:
    def __init__(self):
        db_utils.init_db()
        self.treasury = Treasury()
        self.agent_client = AgentClient()
        self.treasury.agent_client = self.agent_client
        self.regime_detector = RegimeDetector()
        self.ai_strategist = AiStrategist()
        self.capital_allocator = CapitalAllocator()
        self.risk_engine = RiskEngine()
        self.gas_balancer = GasBalancer(w3=self.treasury.w3)

    def run_cycle(self) -> Dict[str, Any]:
        """Esegue un ciclo completo di coordinamento e telemetria."""
        cycle_start = time.time()
        logger.info("==================================================================")
        logger.info("🚀 AVVIO CICLO COORDINATORE MASTER (Base L2)")
        logger.info("==================================================================")

        # 1. Recupero telemetria dai 6 agenti subordinati
        logger.info("1/8 Interrogazione dei 6 agenti...")
        agents_status = self.agent_client.get_all_statuses()
        online_count = sum(1 for a in agents_status.values() if a.get("online"))
        logger.info("   -> %d/6 agenti online e operativi.", online_count)

        # 2. Analisi Macro e Regime di Mercato
        logger.info("2/8 Rilevamento Regime di Mercato e Prezzi Asset...")
        regime_data = self.regime_detector.detect_regime()
        regime = regime_data["regime"]
        eth_price = float(regime_data.get("eth_price", 0.0) or 2650.0)
        logger.info("   -> Regime: %s (Fear & Greed: %d, %s) | Prezzo ETH: $%.2f",
                    regime, regime_data["fear_and_greed"], regime_data["fear_and_greed_label"], eth_price)

        # 3. Lettura saldi Master Treasury con controvalore totale
        logger.info("3/8 Calcolo saldi Master Treasury con controvalore ETH...")
        treasury_bals = self.treasury.get_treasury_balances(eth_price=eth_price)
        treasury_usdc = treasury_bals.get("usdc", 0.0)
        treasury_eth = treasury_bals.get("eth", 0.0)
        treasury_eth_usd = treasury_bals.get("eth_usd", 0.0)
        treasury_total_usd = treasury_bals.get("total_usd", treasury_usdc + treasury_eth_usd)
        logger.info("   -> Master Treasury: $%.2f USDC + %.4f ETH ($%.2f) = Valore Totale $%.2f",
                    treasury_usdc, treasury_eth, treasury_eth_usd, treasury_total_usd)

        # 4. Valutazione Rischio Globale, Delta Netto e Circuit Breaker
        logger.info("4/8 Valutazione del Rischio e Delta Netto...")
        risk_data = self.risk_engine.evaluate_portfolio_risk(
            agents_status=agents_status,
            treasury_cash_usd=treasury_usdc,
            treasury_eth=treasury_eth,
            eth_price=eth_price
        )
        logger.info("   -> Net Worth Totale: $%.2f | PnL 24h: $%.2f (%.2f%%)",
                    risk_data["total_net_worth_usd"], risk_data["pnl_24h_usd"], risk_data["pnl_24h_pct"])
        logger.info("   -> Delta Netto: $%.2f (Ratio: %.1f%%) | Rischio: %s",
                    risk_data["net_delta_usd"], risk_data["net_delta_ratio"] * 100, risk_data["risk_level"])

        if risk_data["warnings"]:
            for w in risk_data["warnings"]:
                logger.warning("   [ALERT] %s", w)

        # Se il Circuit Breaker e' scattato, arresto precauzionale di tutti i bot
        if risk_data.get("circuit_breaker_active"):
            logger.warning("🚨 [CIRCUIT BREAKER ATTIVO] Drawdown critico: invio STOP di emergenza a tutti i bot.")
            self.agent_client.emergency_stop_all(
                reason=f"Circuit Breaker attivato dal Coordinator (drawdown 24h: {risk_data.get('pnl_24h_pct', 0.0):.2f}%)"
            )

        # 5. Gas Balancing & Refuel automatico
        logger.info("5/8 Verifica riserve Gas ETH su Base...")
        gas_report = self.gas_balancer.check_wallets_gas(agents_status, treasury_executor=self.treasury)
        if gas_report["refuels_performed"] > 0:
            logger.info("   -> Eseguiti %d refuel di gas (Totale: %.4f ETH).",
                        gas_report["refuels_performed"], gas_report["total_eth_sent"])

        # 6. Analisi AI Strategist & Performance Ranking
        logger.info("6/8 Analisi AI Strategist (OpenRouter / Fallback Deterministico)...")
        ai_report = self.ai_strategist.analyze_and_optimize(
            regime_data=regime_data,
            agents_status=agents_status,
            treasury_balances=treasury_bals,
            risk_data=risk_data
        )
        if ai_report.get("best_strategy") and ai_report.get("worst_strategy"):
            logger.info("   -> AI Performance Ranking: Best '%s' | Worst '%s'",
                        ai_report.get("best_strategy"), ai_report.get("worst_strategy"))
        if ai_report.get("reasoning"):
            brief = ai_report.get("reasoning").split("\n")[0][:120]
            logger.info("   -> AI Briefing: %s", brief)

        # 7. Calcolo Allocazione Capitale e Piani di Ribilanciamento
        logger.info("7/8 Calcolo allocazione capitale per regime %s...", regime)
        alloc_plan = self.capital_allocator.compute_allocation_plan(
            regime=regime,
            agents_status=agents_status,
            treasury_cash_usd=treasury_usdc,
            dynamic_weights=ai_report.get("dynamic_weights")
        )

        if alloc_plan.get("pruned_notes"):
            for p_note in alloc_plan["pruned_notes"]:
                logger.info("   -> [Soglia Minima] %s", p_note)

        executed_actions = 0
        if alloc_plan["rebalance_needed"]:
            logger.info("   -> Rilevate %d azioni di ribilanciamento consigliate:", len(alloc_plan["actions"]))
            for act in alloc_plan["actions"]:
                logger.info("      • %s: $%.2f (%s -> %s): %s",
                            act.get("action"), act.get("amount_usd"), act.get("from_agent"), act.get("to_agent"), act.get("reason"))

            # Esecuzione se abilitato AUTO_REBALANCE e non in blocco di emergenza
            if config.AUTO_REBALANCE and not risk_data["circuit_breaker_active"]:
                logger.info("   -> AUTO_REBALANCE attivo. Esecuzione trasferimenti...")
                for act in alloc_plan["actions"]:
                    ok = self.treasury.execute_rebalance_action(act, agents_status, agent_client=self.agent_client)
                    if ok:
                        executed_actions += 1
            else:
                logger.info("   -> AUTO_REBALANCE disattivato (modalita' solo monitoraggio).")

        # 8. Salvataggio snapshot SQLite
        logger.info("8/8 Archiviazione snapshot di portafoglio...")
        consolidated_snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_net_worth_usd": risk_data["total_net_worth_usd"],
            "regime": regime,
            "fear_and_greed": regime_data["fear_and_greed"],
            "circuit_breaker_active": risk_data["circuit_breaker_active"],
            "pnl_24h_usd": risk_data["pnl_24h_usd"],
            "pnl_24h_pct": risk_data["pnl_24h_pct"],
            "risk_data": risk_data,
            "regime_data": regime_data,
            "treasury": treasury_bals,
            "agents": agents_status,
            "allocation_plan": alloc_plan,
            "gas_report": gas_report,
            "ai_strategist": ai_report,
            "cycle_duration_seconds": round(time.time() - cycle_start, 2)
        }
        snap_id = db_utils.save_portfolio_snapshot(consolidated_snapshot)
        logger.info("   -> Snapshot #%d archiviato con successo in SQLite.", snap_id)

        # Notifica Telegram se configurato
        try:
            from telegram_bot import send_cycle_summary
            send_cycle_summary(consolidated_snapshot)
        except Exception as e:
            logger.debug("Telegram notification skipped: %s", e)

        logger.info("✅ CICLO COORDINATORE COMPLETATO IN %.2f SECONDI.\n", time.time() - cycle_start)
        return consolidated_snapshot

    def start_loop(self):
        """Avvia il demone a intervalli regolari."""
        logger.info("Avvio demone Coordinator a intervalli di %d secondi...", config.INTERVAL_SECONDS)
        while True:
            try:
                self.run_cycle()
            except Exception as exc:
                logger.error("Errore critico durante il ciclo: %s", exc, exc_info=True)
                db_utils.log_error("CRITICAL_CYCLE_ERROR", str(exc), source="coordinator_loop")

            logger.info("Prossimo ciclo tra %d secondi. In attesa...", config.INTERVAL_SECONDS)
            time.sleep(config.INTERVAL_SECONDS)

    def pause_agent(self, agent_id: str, reason: str = "") -> Dict[str, Any]:
        """Mette in pausa un agente subordinato."""
        return self.agent_client.pause_agent(agent_id, reason)

    def resume_agent(self, agent_id: str) -> Dict[str, Any]:
        """Riattiva un agente subordinato."""
        return self.agent_client.resume_agent(agent_id)

    def emergency_stop(self, reason: str = "Blocco di emergenza manuale dal Coordinator") -> Dict[str, Any]:
        """Blocco di emergenza: mette in pausa tutti i 6 agenti."""
        return self.agent_client.emergency_stop_all(reason)

    def resume_all(self) -> Dict[str, Any]:
        """Ripresa globale: riattiva tutti i 6 agenti."""
        return self.agent_client.resume_all()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Master Coordinator per la suite ITA.")
    parser.add_argument("--once", action="store_true", help="Esegue un solo ciclo e termina.")
    args = parser.parse_args()

    coord = Coordinator()
    if args.once:
        coord.run_cycle()
    else:
        coord.start_loop()

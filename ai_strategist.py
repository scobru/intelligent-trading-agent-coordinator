"""
Modulo AI Macro Strategist & Performance Optimizer.
Analizza in tempo reale le performance dei 6 bot subordinati, il regime macroeconomico
e le riserve di cassa per determinare dinamicamente:
1. Quali strategie stanno performando meglio e quali peggio;
2. Lo spostamento di capitale consigliato dalle strategie deboli a quelle vincenti;
3. Un executive briefing in italiano (via OpenRouter o fallback quantitativo);
4. Direttive di protezione del capitale (profit sweep / safe-haven parking).
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import requests

import config
import db_utils

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 12.0

class AiStrategist:
    def __init__(self):
        self.api_key = config.OPENROUTER_API_KEY
        self.model = config.OPENROUTER_MODEL or "deepseek/deepseek-chat"
        self.dynamic_rebalance_enabled = getattr(config, "DYNAMIC_PERFORMANCE_REBALANCE", True)
        self.max_shift = getattr(config, "MAX_PERFORMANCE_WEIGHT_SHIFT", 0.10)
        self.last_analysis: Dict[str, Any] = {}

    def evaluate_performances_quantitatively(
        self,
        agents_status: Dict[str, Dict[str, Any]],
        regime: str
    ) -> Dict[str, Any]:
        """Calcola uno score quantitativo di performance (1-10) per ciascun bot."""
        history = db_utils.get_agents_historical_pnl()
        scores = {}

        for aid, st in agents_status.items():
            eq = float(st.get("equity_usd", 0.0) or 0.0)
            hist = history.get(aid, {})
            pnl_usd = float(hist.get("pnl_usd", 0.0))
            pnl_pct = float(hist.get("pnl_pct", 0.0))
            pos_cnt = int(st.get("positions_count", 0))

            # Base score neutrale
            score = 5.0

            # 1. PnL % impatto (+/- fino a 3.0 punti)
            if pnl_pct > 10.0:
                score += 3.0
            elif pnl_pct > 2.0:
                score += 1.5
            elif pnl_pct > 0.0:
                score += 0.5
            elif pnl_pct < -8.0:
                score -= 3.0
            elif pnl_pct < -2.0:
                score -= 1.5
            elif pnl_pct < 0.0:
                score -= 0.5

            # 2. Allineamento con il regime di mercato
            if regime in ("BEAR_PANIC", "HIGH_VOLATILITY"):
                if aid == "yield":
                    score += 2.0  # Yield è il rifugio primario
                elif aid in ("degen", "perp"):
                    score -= 2.0  # Troppo rischiosi nel panico
                elif aid == "lp":
                    score -= 2.5  # Rischio impermanent loss elevatissimo
            elif regime == "BULL_MOMENTUM":
                if aid in ("degen", "perp"):
                    score += 1.5  # Catturano il rally rialzista
                elif aid == "dca":
                    score += 1.0
            elif regime == "RANGE_CHOP":
                if aid in ("neutral", "lp"):
                    score += 2.0  # Ideali per funding e fee in laterale

            # 3. Attività e vitalità
            if not st.get("online"):
                score = 1.0
            elif pos_cnt > 0 and pnl_usd >= 0:
                score += 0.5

            # Normalizza punteggio tra 1.0 e 10.0
            final_score = max(1.0, min(10.0, round(score, 1)))

            # Trend classification
            if final_score >= 7.5:
                trend = "OUTPERFORMING 🚀"
            elif final_score >= 5.5:
                trend = "STEADY / POSITIVE 🟢"
            elif final_score >= 4.0:
                trend = "NEUTRAL / MODERATE 🟡"
            else:
                trend = "UNDERPERFORMING / AT RISK ⚠️"

            scores[aid] = {
                "agent_id": aid,
                "name": st.get("name", aid),
                "score": final_score,
                "trend": trend,
                "equity_usd": eq,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "positions_count": pos_cnt
            }

        # Ordina per score decrescente
        sorted_ranks = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        best = sorted_ranks[0]["agent_id"] if sorted_ranks else "yield"
        worst = sorted_ranks[-1]["agent_id"] if sorted_ranks else "degen"

        return {
            "rankings": sorted_ranks,
            "best_strategy": best,
            "worst_strategy": worst,
            "scores_dict": scores
        }

    def _call_openrouter(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Interroga l'API di OpenRouter per ottenere una valutazione strategica."""
        if not self.api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://intelligent-trading-agent-coordinator.scobrudot.dev",
            "X-Title": "Intelligent Trading Agent Coordinator",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sei il Chief Investment Officer e Portfolio Manager dell'ecosistema di trading autonomo su Base L2. "
                        "Analizza la situazione di mercato e la performance dei 6 bot subordinati (Perp, Yield, Neutral, LP, DCA, Degen). "
                        "Il tuo obiettivo prioritario è proteggere il capitale, tagliare le strategie in perdita/drawdown e riallocare fondi "
                        "verso le strategie più profittevoli o stabili. "
                        "Rispondi ESCLUSIVAMENTE in formato JSON valido senza codice markdown o spiegazioni extra, con lo schema:\n"
                        "{\n"
                        '  "market_briefing": "Breve sintesi macro e di portafoglio in italiano (max 250 caratteri)",\n'
                        '  "best_strategy": "id_agente_migliore",\n'
                        '  "worst_strategy": "id_agente_peggiore",\n'
                        '  "reallocation_rationale": "Perché spostare capitale (max 200 caratteri)",\n'
                        '  "suggested_actions": ["Azione 1", "Azione 2"]\n'
                        "}"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 600
        }

        try:
            resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                raw_txt = resp.json()["choices"][0]["message"]["content"].strip()
                # Pulizia eventuale markdown ```json ... ```
                raw_txt = re.sub(r"^```[a-zA-Z]*\n?", "", raw_txt)
                raw_txt = re.sub(r"\n?```$", "", raw_txt).strip()
                return json.loads(raw_txt)
            else:
                logger.warning("OpenRouter API error (status %d): %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("Chiamata OpenRouter non riuscita: %s. Uso fallback quantitativo.", exc)

        return None

    def analyze_and_optimize(
        self,
        regime_data: Dict[str, Any],
        agents_status: Dict[str, Dict[str, Any]],
        treasury_bals: Dict[str, float],
        risk_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Esegue l'analisi strategica completa combinando quantitativo e LLM."""
        regime = regime_data.get("regime", "BALANCED")
        fg_val = regime_data.get("fear_and_greed", 50)
        fg_label = regime_data.get("fear_and_greed_label", "Neutral")

        # 1. Valutazione quantitativa
        q_eval = self.evaluate_performances_quantitatively(agents_status, regime)
        best_strat = q_eval["best_strategy"]
        worst_strat = q_eval["worst_strategy"]
        rankings = q_eval["rankings"]

        # 2. Prepara prompt per OpenRouter (se disponibile)
        prompt_data = {
            "macro_regime": regime,
            "fear_and_greed": f"{fg_val} ({fg_label})",
            "total_net_worth_usd": risk_data.get("total_net_worth_usd", 0.0),
            "portfolio_pnl_24h_pct": risk_data.get("pnl_24h_pct", 0.0),
            "treasury_usdc": treasury_bals.get("usdc", 0.0),
            "treasury_eth": treasury_bals.get("eth", 0.0),
            "strategies_ranking": [
                {
                    "id": r["agent_id"],
                    "name": r["name"],
                    "score": r["score"],
                    "equity": f"${r['equity_usd']:.2f}",
                    "pnl": f"{r['pnl_pct']:+.1f}%"
                }
                for r in rankings
            ]
        }

        ai_response = None
        if self.api_key:
            ai_response = self._call_openrouter(json.dumps(prompt_data, indent=2))

        # 3. Composizione del report finale
        if ai_response and isinstance(ai_response, dict):
            briefing = ai_response.get("market_briefing", "")
            if ai_response.get("best_strategy") in config.AGENTS:
                best_strat = ai_response["best_strategy"]
            if ai_response.get("worst_strategy") in config.AGENTS:
                worst_strat = ai_response["worst_strategy"]
            rationale = ai_response.get("reallocation_rationale", "")
            actions = ai_response.get("suggested_actions", [])
            ai_engine = f"OpenRouter ({self.model})"
        else:
            # Fallback deterministico / quantitativo
            best_info = q_eval["scores_dict"].get(best_strat, {})
            worst_info = q_eval["scores_dict"].get(worst_strat, {})
            briefing = (
                f"Regime {regime} (F&G: {fg_val}). "
                f"Top strategy: {best_info.get('name', best_strat)} (Score: {best_info.get('score', 0)}). "
                f"Sotto pressione: {worst_info.get('name', worst_strat)} (Score: {worst_info.get('score', 0)})."
            )
            rationale = (
                f"Spostamento quote di capitale da {worst_strat.upper()} (de-allocazione difensiva) "
                f"a favore di {best_strat.upper()} / YIELD per massimizzare il rendimento risk-adjusted."
            )
            actions = [
                f"Riduci esposizione su {worst_strat.upper()} se il trend negativo persiste",
                f"Aumenta liquidità allocata verso {best_strat.upper()}"
            ]
            ai_engine = "Deterministic Quantitative Engine (Rules & Performance)"

        # 4. Calcolo Pesi Target Dinamici (Dynamic Weights)
        # Prende i pesi base del regime corrente e sposta una quota da worst_strat a best_strat
        base_weights = dict(config.REGIME_TARGET_WEIGHTS.get(regime, config.REGIME_TARGET_WEIGHTS["BALANCED"]))
        dynamic_weights = dict(base_weights)

        if self.dynamic_rebalance_enabled and best_strat != worst_strat:
            shift = min(self.max_shift, base_weights.get(worst_strat, 0.0) * 0.5)
            if shift >= 0.02:
                dynamic_weights[worst_strat] = max(0.0, round(dynamic_weights[worst_strat] - shift, 4))
                # Se siamo in panic, il surplus va a yield, altrimenti alla migliore strategia
                target_beneficiary = "yield" if regime in ("BEAR_PANIC", "HIGH_VOLATILITY") else best_strat
                dynamic_weights[target_beneficiary] = round(dynamic_weights.get(target_beneficiary, 0.0) + shift, 4)

        result = {
            "timestamp": time.time(),
            "source": "openrouter_ai" if "OpenRouter" in ai_engine else "deterministic",
            "ai_engine": ai_engine,
            "market_briefing": briefing,
            "reasoning": f"{briefing} {rationale}".strip(),
            "best_strategy": best_strat,
            "best_strategy_name": config.AGENTS.get(best_strat, {}).get("name", best_strat),
            "worst_strategy": worst_strat,
            "worst_strategy_name": config.AGENTS.get(worst_strat, {}).get("name", worst_strat),
            "rationale": rationale,
            "suggested_actions": actions,
            "rankings": rankings,
            "base_weights": base_weights,
            "dynamic_weights": dynamic_weights
        }

        self.last_result = result
        return result

"""
Motore di Gestione del Rischio Globale e Circuit Breaker.
Monitora il Net Worth aggregato, calcola il Delta Netto direzionale (Long vs Short) su Base,
traccia il Drawdown a 24h e innesca arresti di sicurezza (Circuit Breakers) in caso di perdite anomale.
"""

import logging
from typing import Any, Dict, List
import db_utils
import config

logger = logging.getLogger(__name__)

class RiskEngine:
    def __init__(self):
        self.max_drawdown_24h_pct = config.MAX_PORTFOLIO_DRAWDOWN_24H_PCT

    def evaluate_portfolio_risk(
        self,
        agents_status: Dict[str, Dict[str, Any]],
        treasury_cash_usd: float = 0.0,
        treasury_eth: float = 0.0,
        eth_price: float = 0.0
    ) -> Dict[str, Any]:
        """Analizza l'esposizione combinata e il rischio complessivo di tutti i bot."""
        treasury_eth_usd = round(treasury_eth * eth_price, 2) if eth_price > 0 else 0.0
        total_treasury_usd = round(treasury_cash_usd + treasury_eth_usd, 2)
        total_equity = total_treasury_usd
        net_long_usd = round(treasury_eth_usd, 2)
        net_short_usd = 0.0
        warnings: List[str] = []
        total_gas_eth = float(treasury_eth or 0.0)
        total_gas_usd = float(treasury_eth_usd or 0.0)

        for agent_id, st in agents_status.items():
            eq = float(st.get("equity_usd", 0.0) or st.get("balance_usd", 0.0) or 0.0)
            gas_eth = float(st.get("gas_eth", 0.0) or 0.0)
            gas_usd = round(gas_eth * eth_price, 2) if eth_price > 0 else 0.0
            st["gas_usd"] = gas_usd
            st["total_val_usd"] = round(eq + gas_usd, 2)
            total_equity += st["total_val_usd"]
            total_gas_eth += gas_eth
            total_gas_usd += gas_usd
            net_long_usd += gas_usd
            pos_list = st.get("positions", [])

            # Calcolo esposizione direzionale (Delta) per strategia
            if agent_id == "dca":
                # Lo spot accumulato (WETH, cbBTC) e' interamente Long
                p = st.get("raw", {}).get("portfolio", {})
                assets = p.get("assets", p) if isinstance(p, dict) else {}
                crypto_val = 0.0
                if isinstance(assets, dict):
                    for k, v in assets.items():
                        if k == "USDC":
                            continue
                        if isinstance(v, dict):
                            crypto_val += float(v.get("value_usd", 0.0) or 0.0)
                        elif isinstance(v, (int, float)):
                            crypto_val += float(v)
                elif isinstance(p, (int, float)):
                    crypto_val = float(p)
                net_long_usd += crypto_val

            elif agent_id == "degen":
                # Token spot meme/altcoin sono 100% Long
                net_long_usd += eq

            elif agent_id == "perp":
                # Posizioni perpetual su SynFutures: direzionali Long o Short
                for p in pos_list:
                    if not isinstance(p, dict):
                        continue
                    direction = str(p.get("direction", "")).upper()
                    val = float(p.get("notional_usd", p.get("size_usd", 0.0)) or 0.0)
                    if direction == "LONG":
                        net_long_usd += val
                    elif direction == "SHORT":
                        net_short_usd += val

            elif agent_id == "lp":
                # In Uniswap V3 LP, meta' della posizione e' tipicamente esposta all'asset volatile
                net_long_usd += eq * 0.50

            elif agent_id == "neutral":
                # Delta neutral e' coperto (Spot long bilanciato da Short perp), Delta quasi zero
                pass

            elif agent_id == "yield":
                # USDC in lending o vault non ha esposizione al prezzo di BTC/ETH
                pass

        net_delta_usd = net_long_usd - net_short_usd
        net_delta_ratio = net_delta_usd / total_equity if total_equity > 0 else 0.0

        # Calcolo PnL a 24h e Drawdown storico tramite SQLite
        snapshots = db_utils.get_recent_snapshots(limit=96) # 96 snapshot da 15min = 24 ore
        pnl_24h_usd = 0.0
        pnl_24h_pct = 0.0
        ath_usd = total_equity

        if snapshots:
            oldest_24h = snapshots[0]
            start_equity = float(oldest_24h.get("total_net_worth_usd", total_equity))
            pnl_24h_usd = total_equity - start_equity
            pnl_24h_pct = (pnl_24h_usd / start_equity * 100.0) if start_equity > 0 else 0.0

            # All Time High recente
            ath_usd = max([float(s.get("total_net_worth_usd", 0.0)) for s in snapshots] + [total_equity])

        drawdown_from_ath_pct = ((ath_usd - total_equity) / ath_usd * 100.0) if ath_usd > 0 else 0.0

        # Circuit Breaker Trigger
        circuit_breaker = False
        if pnl_24h_pct < -self.max_drawdown_24h_pct:
            circuit_breaker = True
            warnings.append(
                f"🚨 CIRCUIT BREAKER ATTIVATO: Drawdown 24h pari a {pnl_24h_pct:.2f}% "
                f"(soglia massima: -{self.max_drawdown_24h_pct:.1f}%). Sospensione bot speculativi!"
            )

        if net_delta_ratio > 0.65:
            warnings.append(f"⚠️ Eccessiva esposizione rialzista: Delta Netto = {net_delta_ratio*100:.1f}% del portafoglio.")
        elif net_delta_ratio < -0.30:
            warnings.append(f"⚠️ Elevata esposizione ribassista: Delta Netto = {net_delta_ratio*100:.1f}%.")

        # Livello di rischio sintetico
        if circuit_breaker or drawdown_from_ath_pct > 12.0:
            risk_level = "CRITICAL"
        elif drawdown_from_ath_pct > 6.0 or abs(net_delta_ratio) > 0.55:
            risk_level = "HIGH"
        elif abs(net_delta_ratio) > 0.35:
            risk_level = "MODERATE"
        else:
            risk_level = "LOW"

        return {
            "total_net_worth_usd": round(total_equity, 2),
            "total_gas_eth": round(total_gas_eth, 6),
            "total_gas_usd": round(total_gas_usd, 2),
            "pnl_24h_usd": round(pnl_24h_usd, 2),
            "pnl_24h_pct": round(pnl_24h_pct, 2),
            "all_time_high_usd": round(ath_usd, 2),
            "drawdown_from_ath_pct": round(drawdown_from_ath_pct, 2),
            "net_long_usd": round(net_long_usd, 2),
            "net_short_usd": round(net_short_usd, 2),
            "net_delta_usd": round(net_delta_usd, 2),
            "net_delta_ratio": round(net_delta_ratio, 4),
            "treasury_total_usd": total_treasury_usd,
            "treasury_usdc": round(treasury_cash_usd, 2),
            "treasury_eth": round(treasury_eth, 5),
            "treasury_eth_usd": treasury_eth_usd,
            "eth_price": round(eth_price, 2),
            "circuit_breaker_active": circuit_breaker,
            "risk_level": risk_level,
            "warnings": warnings
        }

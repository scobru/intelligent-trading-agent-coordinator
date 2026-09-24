"""
Rilevatore del Regime Macroeconomico di Mercato.
Analizza Fear & Greed Index, variazione a 24h e volatilita' di BTC ed ETH per
classificare lo stato del mercato in 5 regimi operativi (BULL, BEAR, RANGE, SHOCK, BALANCED).
"""

import logging
from typing import Any, Dict
import requests

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0

class RegimeDetector:
    def __init__(self):
        self.last_result: Dict[str, Any] = {}

    def get_fear_and_greed(self) -> Dict[str, Any]:
        """Interroga l'API pubblica di Alternative.me per il Crypto Fear & Greed Index."""
        try:
            url = "https://api.alternative.me/fng/?limit=2"
            resp = requests.get(url, timeout=TIMEOUT_SECONDS)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    val = int(data[0].get("value", 50))
                    label = data[0].get("value_classification", "Neutral")
                    prev_val = int(data[1].get("value", val)) if len(data) > 1 else val
                    return {"value": val, "label": label, "prev_value": prev_val}
        except Exception as exc:
            logger.warning("Impossibile recuperare Fear & Greed: %s", exc)

        return {"value": 50, "label": "Neutral", "prev_value": 50}

    def get_market_momentum(self) -> Dict[str, Any]:
        """Recupera prezzo e variazione 24h per BTC ed ETH da Binance (o fallback)."""
        metrics = {
            "btc_price": 0.0,
            "btc_change_24h": 0.0,
            "eth_price": 0.0,
            "eth_change_24h": 0.0,
            "success": False
        }
        try:
            # BTC
            r_btc = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=TIMEOUT_SECONDS)
            if r_btc.status_code == 200:
                d = r_btc.json()
                metrics["btc_price"] = float(d.get("lastPrice", 0.0))
                metrics["btc_change_24h"] = float(d.get("priceChangePercent", 0.0))

            # ETH
            r_eth = requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT", timeout=TIMEOUT_SECONDS)
            if r_eth.status_code == 200:
                d = r_eth.json()
                metrics["eth_price"] = float(d.get("lastPrice", 0.0))
                metrics["eth_change_24h"] = float(d.get("priceChangePercent", 0.0))

            metrics["success"] = True
        except Exception as exc:
            logger.warning("Impossibile recuperare momentum da Binance: %s", exc)

        return metrics

    def detect_regime(self) -> Dict[str, Any]:
        """Classifica il regime corrente di mercato."""
        fng = self.get_fear_and_greed()
        mom = self.get_market_momentum()

        fg_val = fng["value"]
        fg_label = fng["label"]
        btc_chg = mom["btc_change_24h"]
        eth_chg = mom["eth_change_24h"]
        avg_chg = (btc_chg + eth_chg) / 2.0 if mom["success"] else 0.0

        # Riconoscimento della volatilita'
        max_abs_chg = max(abs(btc_chg), abs(eth_chg))
        if max_abs_chg >= 6.5:
            vol_level = "HIGH"
        elif max_abs_chg <= 1.8:
            vol_level = "LOW"
        else:
            vol_level = "NORMAL"

        # Logica di classificazione
        # 1. Shock di volatilita' / Flash crash o pump incontrollato
        if max_abs_chg >= 8.0:
            regime = "HIGH_VOLATILITY"
            rationale = f"Volatilita' anomala a 24h ({max_abs_chg:.1f}%). Ritiro liquidita' LP e focus su preservazione capitale."

        # 2. Mercato in panico / Bear
        elif fg_val <= 26 or (avg_chg < -4.0 and fg_val < 40):
            regime = "BEAR_PANIC"
            rationale = f"Panico di mercato (F&G={fg_val}, {fg_label}). Massimizzazione riserva USDC e DCA aggressivo sui cali."

        # 3. Mercato in forte trend rialzista / Greed
        elif fg_val >= 68 and avg_chg > 1.5:
            regime = "BULL_MOMENTUM"
            rationale = f"Forte momentum rialzista (F&G={fg_val}, {fg_label}, media 24h: +{avg_chg:.1f}%). Allocazione aumentata su Perp e Degen."

        # 4. Mercato laterale a bassa volatilita' (Chop)
        elif vol_level == "LOW" and 40 <= fg_val <= 60:
            regime = "RANGE_CHOP"
            rationale = f"Mercato in compressione e range laterale (|chg| <= 1.8%). Ottimale per fee LP Concentrato e Delta-Neutral."

        # 5. Bilanciato standard
        else:
            regime = "BALANCED"
            rationale = f"Condizioni macro equilibrate (F&G={fg_val}, 24h media: {avg_chg:.1f}%). Allocazione proporzionata a basso rischio."

        result = {
            "regime": regime,
            "fear_and_greed": fg_val,
            "fear_and_greed_label": fg_label,
            "btc_price": mom["btc_price"],
            "btc_change_24h": btc_chg,
            "eth_price": mom["eth_price"],
            "eth_change_24h": eth_chg,
            "avg_change_24h": round(avg_chg, 2),
            "volatility_level": vol_level,
            "rationale": rationale
        }
        self.last_result = result
        return result

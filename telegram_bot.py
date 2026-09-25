"""
Master Telegram Bot per il Coordinator.
Invia briefing periodici consolidati e supporta comandi interattivi (/status, /regime, /alloc, /run).
"""

import json
import logging
import sys
import threading
import time
from typing import Any, Dict, Optional
import requests

import config

logger = logging.getLogger(__name__)

def send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Invia un messaggio al canale/chat configurato."""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID

    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    try:
        resp = requests.post(url, json=payload, timeout=8)
        return resp.status_code == 200
    except Exception as exc:
        logger.error("Errore invio messaggio Telegram: %s", exc)
        return False

def send_cycle_summary(snap: Dict[str, Any]) -> bool:
    """Formatta e invia un report di ciclo consolidato dell'intero ecosistema."""
    risk = snap.get("risk_data", {})
    regime_d = snap.get("regime_data", {})
    agents = snap.get("agents", {})
    alloc = snap.get("allocation_plan", {})

    mode = "📝 PAPER" if config.PAPER_TRADING else ("🧪 DRY-RUN" if config.DRY_RUN else "🔴 LIVE")

    nw = risk.get("total_net_worth_usd", 0.0)
    pnl_usd = risk.get("pnl_24h_usd", 0.0)
    pnl_pct = risk.get("pnl_24h_pct", 0.0)
    sign = "+" if pnl_usd >= 0 else ""

    fg_val = snap.get("fear_and_greed", 50)
    fg_label = regime_d.get("fear_and_greed_label", "Neutral")
    regime = snap.get("regime", "BALANCED")

    lines = [
        f"🌐 *ITA Master Coordinator (Base L2)* `{mode}`",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"💼 *Net Worth Totale:* `${nw:,.2f}`",
        f"📈 *PnL 24h:* `{sign}${pnl_usd:,.2f} ({sign}{pnl_pct:.2f}%)`",
        f"🧭 *Regime:* `{regime}` (F&G: {fg_val}, {fg_label})",
        f"⚖️ *Delta Netto:* `${risk.get('net_delta_usd', 0.0):,.2f}` ({risk.get('net_delta_ratio', 0.0)*100:.1f}% Long)",
        "",
        f"🤖 *Stato Strategie (6 Nodi):*"
    ]

    for aid, a in agents.items():
        icon = a.get("icon", "•")
        name = a.get("name", aid.capitalize())
        eq = a.get("equity_usd", 0.0)
        online_str = "🟢" if a.get("online") else "🔴"
        pause_str = " `[⏸️ PAUSA]`" if a.get("is_paused") else ""
        pos_str = f"({a.get('positions_count', 0)} pos)" if a.get("positions_count", 0) > 0 else ""
        lines.append(f"{online_str} {icon} *{name}:* `${eq:,.2f}` {pos_str}{pause_str}")

    gas_report = snap.get("gas_report", {})
    if gas_report.get("refuels_performed", 0) > 0:
        lines.append(f"\n⛽ *Gas Balancer:* Eseguiti {gas_report['refuels_performed']} refuel automatici ETH ({gas_report.get('total_eth_sent', 0.0):.4f} ETH).")

    ai = snap.get("ai_strategist", {})
    if ai and ai.get("best_strategy") and ai.get("worst_strategy"):
        lines.append(f"\n🧠 *AI Strategist:* 🏆 Best `{ai.get('best_strategy')}` | 🔻 Underperforming `{ai.get('worst_strategy')}`")
        if ai.get("reasoning"):
            brief = ai.get("reasoning").split("\n")[0][:140]
            lines.append(f"💬 _{brief}_")

    warnings = risk.get("warnings", [])
    if warnings:
        lines.append("\n⚠️ *Avvisi di Rischio:*")
        for w in warnings:
            lines.append(f"• `{w}`")

    actions = alloc.get("actions", [])
    if actions:
        lines.append("\n🔄 *Ribilanciamenti Raccomandati:*")
        for act in actions[:3]:
            lines.append(f"• `{act.get('from_agent')} ➔ {act.get('to_agent')}`: ${act.get('amount_usd'):.2f}")

    lines.append(f"\n⏱️ *Prossimo ciclo:* {config.INTERVAL_SECONDS // 60} minuti")

    msg = "\n".join(lines)
    return send_telegram_message(msg)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("Invio messaggio di prova Telegram...")
        ok = send_telegram_message("🚀 *Test di connettività Master Coordinator riuscito con successo!*")
        print("Risultato:", "Inviato" if ok else "Fallito (verifica token e chat_id)")

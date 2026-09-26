"""
Master Dashboard Web per l'ecosistema ITA (Base L2).
Fornisce una vista consolidata in tempo reale su Net Worth, Regime di mercato,
Delta netto, stato dei 6 agenti, ribilanciamento dei capitali e storico operazioni.
"""

import hmac
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Any, Dict

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

import config
import db_utils
from coordinator import Coordinator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("dashboard")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STATIC_ROUTES = {
    "/static/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/static/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8"),
    "/static/icon.svg": ("icon.svg", "image/svg+xml"),
    "/static/icon-small.svg": ("icon-small.svg", "image/svg+xml"),
    "/static/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/static/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/static/site.webmanifest": ("site.webmanifest", "application/manifest+json"),
}

_coordinator_instance: Coordinator = None
_run_lock = threading.Lock()
_latest_status_cache: Dict[str, Any] = {}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <title>Master Coordinator | Intelligent Trading Agent Suite</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" href="/static/favicon.ico">
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
  <link rel="manifest" href="/static/site.webmanifest">
  <link rel="stylesheet" href="/static/dashboard.css?v=2">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --primary: #8b5cf6;
      --accent: #a78bfa;
    }
    .grid-kpi {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 18px;
    }
    .card h3 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .5px;
      color: var(--muted);
      margin-bottom: 8px;
    }
    .card .val {
      font-size: 26px;
      font-weight: 700;
    }
    .card .sub {
      font-size: 12px;
      color: var(--muted);
      margin-top: 4px;
    }
    .agents-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .agent-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: transform .15s ease, border-color .15s ease;
    }
    .agent-card:hover {
      border-color: var(--accent);
      transform: translateY(-2px);
    }
    .agent-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    .agent-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 15px;
    }
    .prog-bar {
      height: 6px;
      background: var(--surface-2);
      border-radius: 3px;
      overflow: hidden;
      margin-top: 6px;
    }
    .prog-fill {
      height: 100%;
      background: var(--primary);
      border-radius: 3px;
    }
    .drift-pos { color: var(--success); }
    .drift-neg { color: var(--warning); }
    .panic-btn {
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border: 1px solid rgba(239, 68, 68, 0.4);
      padding: 7px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-size: 12px;
      transition: all .2s;
    }
    .panic-btn:hover {
      background: var(--danger);
      color: #fff;
    }
    .run-btn {
      background: var(--primary);
      color: #fff;
      border: none;
      padding: 7px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      font-size: 12px;
    }
    .run-btn:hover { opacity: 0.9; }
    .ai-card {
      background: linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(59, 130, 246, 0.05) 100%);
      border: 1px solid rgba(139, 92, 246, 0.3);
      border-radius: var(--radius);
      padding: 18px;
      margin-bottom: 24px;
    }
    .ai-top-badge {
      background: rgba(34, 197, 94, 0.15);
      color: var(--success);
      border: 1px solid rgba(34, 197, 94, 0.4);
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
    }
    .ai-worst-badge {
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border: 1px solid rgba(239, 68, 68, 0.4);
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
    }
  </style>
</head>
<body>

  <!-- HEADER -->
  <header class="header">
    <div class="brand">
      <img src="/static/icon.svg" alt="Coordinator Logo">
      <div>
        <h1>Master Coordinator <span id="mode-badge" class="badge b-paper">PAPER</span></h1>
        <div class="tagline">Orchestratore Centrale Multi-Strategia su Base L2 (Chain ID 8453)</div>
      </div>
    </div>
    <div class="header-actions">
      <span class="updated" id="last-update">Aggiornamento in corso...</span>
      <button class="run-btn" id="btn-run" onclick="triggerCycle()">⚡ Esegui Ciclo Ora</button>
      <button class="run-btn" style="background: var(--success); padding: 7px 14px; font-size: 12px;" onclick="emergencyResume()">🟢 Resume All</button>
      <button class="panic-btn" id="btn-panic" onclick="emergencyPanic()">🚨 Emergency Stop</button>
    </div>
  </header>

  <!-- KPI GLOBALI -->
  <div class="grid-kpi">
    <div class="card">
      <h3>Net Worth Consolidato</h3>
      <div class="val" id="total-net-worth">--</div>
      <div class="sub" id="pnl-24h">PnL 24h: --</div>
      <div class="sub" id="net-worth-note" style="font-size: 11px; margin-top: 4px; color: var(--accent);">Fondi operativi + riserve gas ETH</div>
    </div>
    <div class="card">
      <h3>Regime di Mercato</h3>
      <div class="val" id="regime-name">--</div>
      <div class="sub" id="regime-sub">Fear & Greed: --</div>
    </div>
    <div class="card">
      <h3>Delta Netto (Esposizione)</h3>
      <div class="val" id="net-delta">--</div>
      <div class="sub" id="net-delta-sub">Esposizione: --</div>
    </div>
    <div class="card">
      <h3>Master Treasury (Cassa Totale)</h3>
      <div class="val" id="treasury-cash">--</div>
      <div class="sub" id="treasury-gas">USDC + ETH Gas: --</div>
    </div>
  </div>

  <!-- AI MACRO STRATEGIST & PERFORMANCE OPTIMIZER -->
  <div class="ai-card" id="ai-section">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="font-size: 20px;">🧠</span>
        <h3 style="margin: 0; font-size: 13px; text-transform: uppercase; letter-spacing: .5px; color: var(--text);">
          AI Macro Strategist & Performance Optimizer
        </h3>
        <span id="ai-source-badge" style="background: rgba(139, 92, 246, 0.2); color: var(--accent); border: 1px solid rgba(139, 92, 246, 0.4); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;">AI Engine</span>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <span id="ai-best-badge" class="ai-top-badge">🏆 Top: --</span>
        <span id="ai-worst-badge" class="ai-worst-badge">🔻 Underperforming: --</span>
      </div>
    </div>
    <div id="ai-reasoning" style="font-size: 13px; line-height: 1.6; color: var(--text); background: rgba(0,0,0,0.25); padding: 12px 14px; border-radius: 8px; border-left: 3px solid var(--primary); margin-bottom: 12px;">
      Inizializzazione intelligenza artificiale in corso...
    </div>
    <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--muted); flex-wrap: wrap; gap: 8px;">
      <span>⚡ <strong>Ribilanciamento Dinamico:</strong> Spostamento automatico fino a ±10% di peso verso la strategia con migliore rendimento.</span>
      <span id="ai-gas-note">⛽ <strong>Auto-Refuel Gas:</strong> Trasferisce ETH solo se la Tesoreria Master ha saldo disponibile (&ge; 0.0038 ETH).</span>
    </div>
  </div>

  <!-- SEZIONE GRAFICO EQUITY -->
  <div class="card" style="margin-bottom: 24px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
      <h3 style="margin: 0;">Andamento del Valore Complessivo (Equity Curve)</h3>
      <span id="chart-info" style="font-size: 11px; color: var(--muted);">Caricamento dati...</span>
    </div>
    <div class="chart-box" style="height: 240px; position: relative;">
      <canvas id="equity-chart"></canvas>
      <div id="chart-empty" style="display: none; position: absolute; inset: 0; background: var(--surface); align-items: center; justify-content: center; color: var(--muted); font-size: 13px;">
        In attesa del primo snapshot di equity... Esegui un ciclo o attendi l'intervallo automatico.
      </div>
    </div>
  </div>

  <!-- STATO DEI 6 AGENTI SUBORDINATI -->
  <h2 style="font-size: 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">
    🤖 Nodi Operativi Subordinati (6 Agenti)
  </h2>
  <div class="agents-grid" id="agents-container">
    <!-- Popolato dinamicamente da JS -->
  </div>

  <!-- ALLOCAZIONE TARGET VS REALE -->
  <div class="card" style="margin-bottom: 24px;">
    <h3>Matrice di Allocazione Strategica (Regime Corrente)</h3>
    <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
      <thead>
        <tr style="text-align: left; color: var(--muted); border-bottom: 1px solid var(--border);">
          <th style="padding: 8px;">Strategia</th>
          <th>Tipo</th>
          <th>Target %</th>
          <th>Attuale %</th>
          <th>Valore Target</th>
          <th>Valore Attuale</th>
          <th>Scostamento (Drift)</th>
        </tr>
      </thead>
      <tbody id="alloc-table">
        <tr><td colspan="7" class="empty">Caricamento allocazione...</td></tr>
      </tbody>
    </table>
  </div>

  <!-- OPERAZIONI RECENTI -->
  <div class="card">
    <h3>Ultime Operazioni & Ribilanciamenti Tesoreria</h3>
    <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
      <thead>
        <tr style="text-align: left; color: var(--muted); border-bottom: 1px solid var(--border);">
          <th style="padding: 8px;">Data (UTC)</th>
          <th>Operazione</th>
          <th>Da</th>
          <th>A</th>
          <th>Importo</th>
          <th>Stato</th>
          <th>Motivazione</th>
        </tr>
      </thead>
      <tbody id="ops-table">
        <tr><td colspan="7" class="empty">Nessuna operazione registrata.</td></tr>
      </tbody>
    </table>
  </div>

  <script src="/static/dashboard.js?v=2"></script>
  <script>
    let chartInstance = null;

    function renderStatus(s) {
      if (!s) return;

      // Mode badge
      const mb = document.getElementById('mode-badge');
      if (s.mode === 'live') {
        mb.className = 'badge b-live'; mb.textContent = 'LIVE';
      } else if (s.mode === 'dry_run') {
        mb.className = 'badge b-dry'; mb.textContent = 'DRY-RUN';
      } else {
        mb.className = 'badge b-paper'; mb.textContent = 'PAPER';
      }

      // Net Worth & PnL
      document.getElementById('total-net-worth').textContent = ITA.usd(s.total_net_worth_usd);
      const sign = (s.pnl_24h_usd >= 0) ? '+' : '';
      const pnlEl = document.getElementById('pnl-24h');
      pnlEl.textContent = `PnL 24h: ${sign}${ITA.usd(s.pnl_24h_usd)} (${sign}${s.pnl_24h_pct.toFixed(2)}%)`;
      pnlEl.style.color = (s.pnl_24h_usd >= 0) ? 'var(--success)' : 'var(--danger)';

      const gasNote = document.getElementById('net-worth-note');
      if (gasNote) {
        const totGasEth = s.risk_data?.total_gas_eth;
        const totGasUsd = s.risk_data?.total_gas_usd;
        if (totGasEth !== undefined && totGasEth > 0) {
          gasNote.textContent = `Inclusi ${totGasEth.toFixed(4)} ETH gas fee (~${ITA.usd(totGasUsd || 0)})`;
        } else {
          gasNote.textContent = `Include fondi operativi + riserve gas ETH`;
        }
      }

      // Regime
      document.getElementById('regime-name').textContent = s.regime || '--';
      const fg = s.fear_and_greed || 50;
      document.getElementById('regime-sub').textContent = `Fear & Greed: ${fg} (${s.regime_data?.fear_and_greed_label || 'Neutral'})`;

      // Delta Netto
      const r = s.risk_data || {};
      document.getElementById('net-delta').textContent = ITA.usd(r.net_delta_usd);
      const ratio = ((r.net_delta_ratio || 0) * 100).toFixed(1);
      document.getElementById('net-delta-sub').textContent = `Esposizione: ${ratio}% Long`;

      // Treasury
      const tr = s.treasury || {};
      const ethPrice = s.regime_data?.eth_price || 2690;
      const trEthUsd = (tr.eth_usd !== undefined) ? tr.eth_usd : ((tr.eth || 0) * ethPrice);
      const trTotal = (tr.total_usd !== undefined) ? tr.total_usd : ((tr.usdc || 0) + trEthUsd);
      document.getElementById('treasury-cash').textContent = ITA.usd(trTotal);
      const ethSubStr = trEthUsd > 0 ? ` (~${ITA.usd(trEthUsd)})` : '';
      document.getElementById('treasury-gas').textContent = `${ITA.usd(tr.usdc || 0)} USDC + ${(tr.eth || 0).toFixed(4)} ETH${ethSubStr}`;

      // AI Strategist
      const ai = s.ai_strategist || {};
      const aiBadge = document.getElementById('ai-source-badge');
      if (aiBadge) {
        aiBadge.textContent = ai.source === 'openrouter_ai' ? 'OpenRouter LLM (Deep Reasoning)' : 'Algoritmo Quantitativo';
      }
      const bestEl = document.getElementById('ai-best-badge');
      if (bestEl) {
        bestEl.textContent = '🏆 Top: ' + (ai.best_strategy ? ai.best_strategy.toUpperCase() : '--');
      }
      const worstEl = document.getElementById('ai-worst-badge');
      if (worstEl) {
        worstEl.textContent = '🔻 Scaling: ' + (ai.worst_strategy ? ai.worst_strategy.toUpperCase() : '--');
      }
      const reasonEl = document.getElementById('ai-reasoning');
      if (reasonEl) {
        reasonEl.textContent = ai.reasoning || 'Nessun briefing disponibile.';
      }

      // Render 6 Agents Cards
      renderAgents(s.agents || {}, s.allocation_plan?.allocations || {}, ai, s.regime_data?.eth_price || 2690);

      // Render Allocation Table
      renderAllocTable(s.allocation_plan?.allocations || {}, ai);
    }

    function renderAgents(agents, allocs, ai, ethPrice = 2690) {
      const container = document.getElementById('agents-container');
      const html = Object.keys(agents).map(aid => {
        const a = agents[aid];
        const al = allocs[aid] || {};
        const isBest = (ai && ai.best_strategy === aid);
        const isWorst = (ai && ai.worst_strategy === aid);
        const aiRankBadge = isBest
          ? '<span class="ai-top-badge" style="font-size: 10px; padding: 2px 6px;">🏆 TOP</span>'
          : (isWorst ? '<span class="ai-worst-badge" style="font-size: 10px; padding: 2px 6px;">🔻 SCALED</span>' : '');
        const onlineBadge = a.online ? '<span class="badge b-ok">ONLINE</span>' : '<span class="badge b-bad">OFFLINE</span>';
        const pauseBadge = a.is_paused ? '<span class="badge b-warn">PAUSA</span>' : '';
        const pauseBtn = a.is_paused
          ? `<button onclick="toggleAgentPause('${aid}', false)" style="background: rgba(34, 197, 94, 0.15); border: 1px solid rgba(34, 197, 94, 0.4); border-radius: 6px; color: var(--success); padding: 3px 8px; font-size: 11px; cursor: pointer; font-weight: 600;">▶️ Ripristina</button>`
          : `<button onclick="toggleAgentPause('${aid}', true)" style="background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 6px; color: var(--warning); padding: 3px 8px; font-size: 11px; cursor: pointer;">⏸️ Pausa</button>`;
        const actualPct = (al.actual_pct ? (al.actual_pct * 100).toFixed(1) : 0);
        const targetPct = (al.target_pct ? (al.target_pct * 100).toFixed(1) : 0);
        const gasEth = (a.gas_eth || 0);
        const gasUsd = (a.gas_usd !== undefined) ? a.gas_usd : (gasEth * ethPrice);
        const gasUsdStr = gasUsd > 0 ? ` (~${ITA.usd(gasUsd)})` : '';
        const opEquity = (a.equity_usd || 0);
        const totalVal = (a.total_val_usd !== undefined) ? a.total_val_usd : (opEquity + gasUsd);

        return `
          <div class="agent-card">
            <div class="agent-header">
              <div class="agent-title">
                <span style="font-size: 18px;">${a.icon || '🤖'}</span>
                <span>${a.name}</span>
              </div>
              <div style="display: flex; gap: 6px; align-items: center;">
                ${aiRankBadge}
                ${pauseBadge}
                ${onlineBadge}
              </div>
            </div>
            <div style="font-size: 12px; color: var(--muted);">${a.description || ''}</div>
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
              <div>
                <div style="font-size: 11px; color: var(--muted);">VALORE TOTALE (FONDI + ETH)</div>
                <div style="font-size: 20px; font-weight: 700;">${ITA.usd(totalVal)}</div>
                <div style="font-size: 11px; color: var(--muted);">${ITA.usd(opEquity)} operativo + ${gasEth.toFixed(4)} ETH fee</div>
              </div>
              <div style="text-align: right;">
                <div style="font-size: 11px; color: var(--muted);">QUOTA PORTAFOGLIO</div>
                <div style="font-size: 14px; font-weight: 600;">${actualPct}% <span style="font-size: 11px; color: var(--muted);">(tgt ${targetPct}%)</span></div>
              </div>
            </div>
            <div class="prog-bar">
              <div class="prog-fill" style="width: ${Math.min(100, actualPct)}%; background: ${a.color || 'var(--primary)'};"></div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px; border-top: 1px solid var(--border); padding-top: 8px;">
              <span>Posizioni: <strong>${a.positions_count || 0}</strong></span>
              <span>Gas ETH: <strong>${gasEth.toFixed(4)}</strong>${gasUsdStr}</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px; gap: 6px;">
              <a href="${a.url || '#'}" target="_blank" style="font-size: 12px; text-decoration: none;">Apri Dashboard ↗</a>
              <div style="display: flex; gap: 6px;">
                <button onclick="releaseAgentFunds('${aid}')" title="Svincola liquidità USDC (vende token o ritira da Gate)" style="background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.4); border-radius: 6px; color: var(--primary); padding: 3px 8px; font-size: 11px; cursor: pointer; font-weight: 500;">💸 Libera USDC</button>
                ${pauseBtn}
                <button onclick="triggerAgentRun('${aid}')" ${a.is_paused ? 'disabled style="opacity: 0.5; cursor: not-allowed; padding: 3px 8px; font-size: 11px; border-radius: 6px;" title="Bot in pausa"' : 'style="background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--text); padding: 3px 8px; font-size: 11px; cursor: pointer;"'}>Avvia Ciclo</button>
              </div>
            </div>
          </div>
        `;
      }).join('');
      container.innerHTML = html;
    }

    function renderAllocTable(allocs, ai) {
      const tbody = document.getElementById('alloc-table');
      if (!allocs || Object.keys(allocs).length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">Nessuna allocazione disponibile.</td></tr>';
        return;
      }
      tbody.innerHTML = Object.keys(allocs).map(aid => {
        const al = allocs[aid];
        const driftCls = (al.drift_usd >= 0) ? 'drift-pos' : 'drift-neg';
        const sign = (al.drift_usd >= 0) ? '+' : '';
        const dynNote = (ai && ai.best_strategy === aid) ? ' <span style="color: var(--success); font-weight: 700;">(+boost)</span>' : ((ai && ai.worst_strategy === aid) ? ' <span style="color: var(--danger); font-weight: 700;">(-cut)</span>' : '');
        const roleBadge = al.pruned ? `<span style="color: #f59e0b; font-size: 11px; background: rgba(245, 158, 11, 0.12); padding: 2px 6px; border-radius: 4px;" title="Capitale insufficiente per operare (minimo $${al.min_viable_usd || 0})">⚠️ Sotto soglia (&lt;$${al.min_viable_usd || 0})</span>` : (al.target_pct > 0.2 ? 'Core Strategy' : 'Satellite');
        return `
          <tr style="border-bottom: 1px solid var(--border);">
            <td style="padding: 10px 8px; font-weight: 600;">${aid.toUpperCase()}${dynNote}</td>
            <td style="color: var(--muted); font-size: 12px;">${roleBadge}</td>
            <td>${(al.target_pct * 100).toFixed(1)}%</td>
            <td>${(al.actual_pct * 100).toFixed(1)}%</td>
            <td>${ITA.usd(al.target_usd)}</td>
            <td>${ITA.usd(al.actual_usd)}</td>
            <td class="${driftCls}"><strong>${sign}${ITA.usd(al.drift_usd)}</strong> (${sign}${al.drift_pct.toFixed(1)}%)</td>
          </tr>
        `;
      }).join('');
    }

    function renderOps(ops) {
      const tbody = document.getElementById('ops-table');
      if (!ops || ops.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">Nessuna operazione registrata.</td></tr>';
        return;
      }
      tbody.innerHTML = ops.map(o => `
        <tr style="border-bottom: 1px solid var(--border);">
          <td style="padding: 8px;">${ITA.time(o.created_at)}</td>
          <td><span class="badge b-ok">${o.operation_type}</span></td>
          <td>${o.from_agent || 'Master'}</td>
          <td>${o.to_agent || '--'}</td>
          <td style="font-weight: 600;">${o.asset === 'ETH' ? o.amount + ' ETH' : ITA.usd(o.amount)}</td>
          <td>${ITA.statusBadge(o.status)}</td>
          <td style="color: var(--muted); font-size: 12px;">${ITA.esc(o.reason || '')}</td>
        </tr>
      `).join('');
    }

    function renderChart(snaps) {
      const el = document.getElementById('equity-chart');
      const emptyEl = document.getElementById('chart-empty');
      const infoEl = document.getElementById('chart-info');
      if (!el) return;

      if (!window.Chart) {
        console.warn('Chart.js non ancora caricato, nuovo tentativo a breve...');
        setTimeout(() => renderChart(snaps), 250);
        return;
      }

      let data = Array.isArray(snaps) ? snaps.slice() : [];
      if (data.length === 0 && window.currentStatus && window.currentStatus.total_net_worth_usd) {
        data = [{
          created_at: new Date().toISOString(),
          total_net_worth_usd: window.currentStatus.total_net_worth_usd
        }];
      }

      if (data.length === 0) {
        if (emptyEl) emptyEl.style.display = 'flex';
        if (infoEl) infoEl.textContent = '0 snapshot';
        return;
      }

      if (emptyEl) emptyEl.style.display = 'none';

      if (infoEl) {
        infoEl.textContent = `${data.length} rilevazioni storiche`;
      }

      // Se c'è solo un dato storico, replichiamo con timestamp precedente per visualizzare una linea orizzontale
      let chartData = data;
      if (chartData.length === 1) {
        const s = chartData[0];
        const prevTime = new Date(new Date(s.created_at || Date.now()).getTime() - 60000).toISOString();
        chartData = [{ created_at: prevTime, total_net_worth_usd: s.total_net_worth_usd }, s];
      }

      const labels = chartData.map(s => ITA.time(s.created_at));
      const values = chartData.map(s => Number(s.total_net_worth_usd) || 0);

      chartInstance = ITA.lineChart(chartInstance, el, labels, [
        { label: 'Net Worth Totale ($)', data: values }
      ]);
    }

    async function refresh() {
      try {
        const [stRes, snapRes, opRes] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/snapshots').then(r => r.json()),
          fetch('/api/operations').then(r => r.json())
        ]);
        window.currentStatus = stRes;
        renderStatus(stRes);
        renderOps(opRes);
        renderChart(snapRes);
        document.getElementById('last-update').textContent = 'Aggiornato: ' + new Date().toLocaleTimeString();
      } catch(err) {
        console.error('Errore refresh:', err);
      }
    }

    async function triggerCycle() {
      const btn = document.getElementById('btn-run');
      btn.disabled = true;
      btn.textContent = '⏳ Invio richiesta...';
      try {
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'DashboardUI'
          }
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert('Attenzione: ' + (data.message || data.error || ('HTTP ' + res.status)));
          btn.disabled = false;
          btn.textContent = '⚡ Esegui Ciclo Ora';
        } else {
          btn.textContent = '🔄 Ciclo in elaborazione...';
          let count = 0;
          const poll = setInterval(async () => {
            count++;
            await refresh();
            if (count >= 5) {
              clearInterval(poll);
              btn.disabled = false;
              btn.textContent = '⚡ Esegui Ciclo Ora';
            }
          }, 2500);
        }
      } catch(e) {
        alert('Errore di connessione durante esecuzione ciclo: ' + e);
        btn.disabled = false;
        btn.textContent = '⚡ Esegui Ciclo Ora';
      }
    }

    async function emergencyPanic() {
      if (!confirm('ATTENZIONE: Attivare il blocco di emergenza globale? Tutti i 6 bot verranno messi in PAUSA.')) return;
      try {
        await fetch('/api/emergency_stop', { method: 'POST' });
        alert('Blocco di emergenza attivato su tutti i bot!');
        setTimeout(refresh, 1000);
      } catch(e) {
        alert('Errore: ' + e);
      }
    }

    async function emergencyResume() {
      if (!confirm('Riattivare tutti i bot subordinati?')) return;
      try {
        await fetch('/api/emergency_resume', { method: 'POST' });
        alert('Ripresa globale inviata con successo!');
        setTimeout(refresh, 1000);
      } catch(e) {
        alert('Errore: ' + e);
      }
    }

    async function toggleAgentPause(aid, shouldPause) {
      const endpoint = shouldPause ? '/api/agent_pause/' + aid : '/api/agent_resume/' + aid;
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ reason: 'Richiesta manuale da Master Dashboard' })
        }).then(r => r.json());
        if (res.status === 'success') {
          setTimeout(refresh, 1000);
        } else {
          alert('Errore operazione: ' + (res.message || JSON.stringify(res)));
        }
      } catch(e) {
        alert('Errore: ' + e);
      }
    }

    async function triggerAgentRun(aid) {
      try {
        const res = await fetch('/api/agent_run/' + aid, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (res.ok && (data.status === 'success' || data.success || !data.error)) {
          alert('Segnale di avvio ciclo inviato con successo a ' + aid);
          setTimeout(refresh, 2000);
        } else {
          alert('Errore invio segnale a ' + aid + ': ' + (data.message || data.error || JSON.stringify(data)));
        }
      } catch(e) {
        alert('Errore: ' + e);
      }
    }

    async function releaseAgentFunds(aid) {
      if (!confirm(`Vuoi richiedere a ${aid.toUpperCase()} di svincolare capitale (vendere token o ritirare da Gate) per liberare USDC?`)) return;
      try {
        const res = await fetch('/api/agent_release_funds/' + aid, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ amount_usd: 0 })
        }).then(r => r.json());
        if (res.status === 'success') {
          const detail = res.data?.message || (res.data ? JSON.stringify(res.data) : 'Fondi svincolati con successo.');
          alert(`Svincolo riuscito per ${aid.toUpperCase()}:\n${detail}`);
          setTimeout(refresh, 2000);
        } else {
          alert('Errore svincolo: ' + (res.message || JSON.stringify(res)));
        }
      } catch(e) {
        alert('Errore chiamata svincolo: ' + e);
      }
    }

    refresh();
    setInterval(refresh, 20000); // Auto-refresh ogni 20 secondi
  </script>
</body>
</html>
"""

class SafeThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, exc_value, _ = sys.exc_info()
        # Silenzia disconnessioni tipiche da parte dei client/browser/healthcheck (BrokenPipe, ConnectionReset)
        if exc_type in (BrokenPipeError, ConnectionResetError) or (isinstance(exc_value, OSError) and getattr(exc_value, "errno", None) in (32, 104)):
            return
        super().handle_error(request, client_address)

class MasterDashboardHandler(BaseHTTPRequestHandler):
    coordinator: Coordinator = None

    def log_message(self, format, *args):
        pass  # Silenzia access logs per pulizia terminale

    def _json(self, code: int, payload: Any):
        try:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_GET(self):
        try:
            self._do_GET_internal()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _do_GET_internal(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            body = HTML_TEMPLATE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path in STATIC_ROUTES:
            fname, ctype = STATIC_ROUTES[path]
            fpath = os.path.join(STATIC_DIR, fname)
            try:
                with open(fpath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except OSError:
                self.send_response(404)
                self.end_headers()
                return

        if path == "/api/status":
            global _latest_status_cache
            # Se la cache e' vuota, eseguiamo o leggiamo l'ultimo snapshot
            snaps = db_utils.get_recent_snapshots(limit=1)
            if snaps and not _latest_status_cache:
                last_snap = snaps[0]
                try:
                    conn = db_utils.get_connection()
                    cur = conn.cursor()
                    cur.execute("SELECT details_json FROM portfolio_snapshots WHERE id = ?", (last_snap["id"],))
                    row = cur.fetchone()
                    conn.close()
                    if row and row["details_json"]:
                        _latest_status_cache = json.loads(row["details_json"])
                except Exception:
                    pass

            if not _latest_status_cache and self.coordinator:
                try:
                    _latest_status_cache = self.coordinator.run_cycle()
                except Exception as exc:
                    logger.error("Errore run_cycle durante /api/status: %s", exc)
                    _latest_status_cache = {
                        "error": str(exc),
                        "total_net_worth_usd": 0.0,
                        "regime": "BALANCED",
                        "agents": {},
                        "treasury": {}
                    }

            if _latest_status_cache:
                _latest_status_cache["mode"] = "paper" if config.PAPER_TRADING else ("dry_run" if config.DRY_RUN else "live")
                if "ai_strategist" not in _latest_status_cache and self.coordinator:
                    try:
                        _latest_status_cache["ai_strategist"] = self.coordinator.ai_strategist.analyze_and_optimize(
                            regime_data=_latest_status_cache.get("regime_data", {}),
                            agents_status=_latest_status_cache.get("agents", {}),
                            treasury_balances=_latest_status_cache.get("treasury", {}),
                            risk_data=_latest_status_cache.get("risk_data", {})
                        )
                    except Exception:
                        pass
            self._json(200, _latest_status_cache or {})
            return

        if path == "/api/snapshots":
            snaps = db_utils.get_recent_snapshots(limit=100)
            self._json(200, snaps)
            return

        if path == "/api/operations":
            ops = db_utils.get_recent_operations(limit=50)
            self._json(200, ops)
            return

        if path == "/health":
            self._json(200, {"status": "healthy", "service": "coordinator"})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/run":
            token = getattr(config, "DASHBOARD_RUN_TOKEN", "")
            auth = self.headers.get("Authorization", "").replace("Bearer ", "").strip()
            is_browser_ui = self.headers.get("X-Requested-With") == "DashboardUI" or self.headers.get("Sec-Fetch-Site") in ("same-origin", "same-site")
            if token and not is_browser_ui and not (auth and hmac.compare_digest(auth, token)):
                self._json(403, {"error": "unauthorized", "message": "Autenticazione richiesta per /api/run"})
                return

            if _run_lock.locked():
                self._json(409, {"status": "already_running", "message": "Un ciclo è già in corso di esecuzione."})
                return

            def _bg_run():
                global _latest_status_cache
                with _run_lock:
                    try:
                        logger.info("⚡ [MANUAL RUN] Avvio manuale del ciclo Coordinator richiesto da Web Dashboard...")
                        coord = self.coordinator or _coordinator_instance
                        if not coord:
                            coord = Coordinator()
                        _latest_status_cache = coord.run_cycle()
                        logger.info("⚡ [MANUAL RUN] Ciclo completato con successo.")
                    except Exception as e:
                        logger.error("Errore esecuzione run coordinator: %s", e, exc_info=True)

            threading.Thread(target=_bg_run, daemon=True).start()
            self._json(200, {"status": "started", "message": "Ciclo avviato con successo in background."})
            return

        if path.startswith("/api/agent_run/"):
            aid = path.replace("/api/agent_run/", "").strip()
            if self.coordinator:
                res = self.coordinator.agent_client.trigger_agent_run(aid)
                self._json(200, res)
            else:
                self._json(500, {"error": "Coordinator non inizializzato"})
            return

        if path.startswith("/api/agent_pause/"):
            aid = path.replace("/api/agent_pause/", "").strip()
            reason = "Pausa richiesta da Master Dashboard"
            try:
                clen = int(self.headers.get("Content-Length", 0))
                if clen > 0:
                    body = json.loads(self.rfile.read(clen).decode("utf-8"))
                    reason = body.get("reason", reason)
            except Exception:
                pass
            if self.coordinator:
                res = self.coordinator.agent_client.pause_agent(aid, reason=reason)
                self._json(200, res)
            else:
                self._json(500, {"error": "Coordinator non inizializzato"})
            return

        if path.startswith("/api/agent_resume/"):
            aid = path.replace("/api/agent_resume/", "").strip()
            if self.coordinator:
                res = self.coordinator.agent_client.resume_agent(aid)
                self._json(200, res)
            else:
                self._json(500, {"error": "Coordinator non inizializzato"})
            return

        if path.startswith("/api/agent_release_funds/"):
            aid = path.replace("/api/agent_release_funds/", "").strip()
            amount_usd = 0.0
            try:
                clen = int(self.headers.get("Content-Length", 0))
                if clen > 0:
                    body = json.loads(self.rfile.read(clen).decode("utf-8"))
                    amount_usd = float(body.get("amount_usd", 0.0) or 0.0)
            except Exception:
                pass
            coord = self.coordinator or _coordinator_instance
            if coord:
                res = coord.agent_client.release_agent_funds(aid, amount_usd)
                self._json(200, res)
            else:
                self._json(500, {"error": "Coordinator non inizializzato"})
            return

        if path == "/api/emergency_stop":
            logger.warning("🚨 EMERGENCY STOP RICHIESTO DA DASHBOARD!")
            db_utils.log_error("EMERGENCY_STOP_TRIGGERED", "Attivato blocco globale dalla dashboard", source="dashboard")
            if self.coordinator:
                res = self.coordinator.agent_client.emergency_stop_all(reason="Blocco di emergenza richiesto da Master Dashboard")
                self._json(200, {"status": "emergency_activated", "details": res})
            else:
                self._json(200, {"status": "emergency_activated"})
            return

        if path == "/api/emergency_resume":
            logger.info("🟢 RIPRESA GLOBALE RICHIESTA DA DASHBOARD!")
            if self.coordinator:
                res = self.coordinator.agent_client.resume_all()
                self._json(200, {"status": "resumed_all", "details": res})
            else:
                self._json(200, {"status": "resumed_all"})
            return

        self.send_response(404)
        self.end_headers()

def run_dashboard():
    global _coordinator_instance
    _coordinator_instance = Coordinator()
    MasterDashboardHandler.coordinator = _coordinator_instance

    ports_to_listen = [config.DASHBOARD_PORT]
    if config.DASHBOARD_PORT != 3000:
        ports_to_listen.append(3000)

    servers = []
    for port in ports_to_listen:
        try:
            srv = SafeThreadingHTTPServer((config.DASHBOARD_HOST, port), MasterDashboardHandler)
            print(f"🚀 Master Coordinator Dashboard attiva su http://{config.DASHBOARD_HOST}:{port}", flush=True)
            logger.info("🌐 Master Coordinator Dashboard avviata su http://%s:%s", config.DASHBOARD_HOST, port)
            servers.append(srv)
        except Exception as exc:
            print(f"⚠️ Impossibile avviare dashboard su porta {port}: {exc}", flush=True)

    if not servers:
        raise RuntimeError("Impossibile avviare il server HTTP su nessuna porta.")

    threads = []
    for srv in servers[1:]:
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        threads.append(t)

    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        logger.info("Chiusura dashboard...")
    finally:
        for srv in servers:
            try:
                srv.server_close()
            except Exception:
                pass

if __name__ == "__main__":
    run_dashboard()

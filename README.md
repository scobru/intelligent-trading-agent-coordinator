<img src="static/icon.svg" alt="" width="88" height="88" align="left">

# Intelligent Trading Agent - Master Coordinator (Base L2)

<br clear="left">

Agente centrale di **orchestrazione strategica, allocazione del capitale e gestione del rischio globale** per la famiglia di bot su rete **Base (Chain ID 8453)**.

Il Coordinator connette e governa i 6 agenti specializzati dell'ecosistema, modulando dinamicamente il capitale in base ai regimi macroeconomici di mercato e proteggendo il portafoglio tramite controlli di rischio consolidati.

---

## 🌟 La Suite Completa dei 6 Nodi Subordinati

| Agente | Strategia Primaria | Focus di Rischio | Protocolli Base |
|---|---|---|---|
| [intelligent-trading-agent](https://github.com/scobru/intelligent-trading-agent) | **Perpetual direzionale** con leva | Alto / Trend & Momentum | SynFutures V3 (`synfutures-service`) |
| [intelligent-trading-agent-yield](https://github.com/scobru/intelligent-trading-agent-yield) | **Rendimento passivo** su lending/vault | Minimo / Capitale parcheggiato | Aave V3, Morpho, Moonwell, ERC-4626 |
| [intelligent-trading-agent-neutral](https://github.com/scobru/intelligent-trading-agent-neutral) | **Delta-Neutral Funding carry** | Basso / Cash & Carry | Uniswap V3 (Spot) + SynFutures V3 (Short) |
| [intelligent-trading-agent-lp](https://github.com/scobru/intelligent-trading-agent-lp) | **Liquidità concentrata AMM** | Medio / Fee harvesting & IL | Uniswap V3 NonfungiblePositionManager |
| [intelligent-trading-agent-dca](https://github.com/scobru/intelligent-trading-agent-dca) | **DCA & Rebalancing** ponderato | Medio-basso / Accumulo WETH/BTC | Uniswap V3 con Fear & Greed multiplier |
| [intelligent-trading-agent-degen](https://github.com/scobru/intelligent-trading-agent-degen) | **Spot speculativo / Meme** | Molto alto / Asimmetrico | Uniswap V3 con screening GoPlus Security |

---

## 🧠 Funzionalità Chiave dell'Orchestratore

### 1. Rilevamento Dinamico del Regime di Mercato (`regime_detector.py`)
Classifica in tempo reale le condizioni macro del mercato crypto:
* **`BULL_MOMENTUM`**: Sentiment Greed ($\ge 68$) e trend positivo $\rightarrow$ incrementa budget su Perp (25%) e Degen (15%).
* **`BEAR_PANIC`**: Extreme Fear ($\le 26$) o crolli $\rightarrow$ 50% parcheggiato in Yield passivo, 30% al DCA sui cali, 0% Degen/LP.
* **`RANGE_CHOP`**: Bassa volatilità e lateralizzazione $\rightarrow$ massimizza il budget di LP Concentrato (30%) e Funding Carry (25%).
* **`HIGH_VOLATILITY`**: Shock o oscillazioni estreme $\rightarrow$ 65% in Yield protetto, ritiro immediato della liquidità LP per azzerare l'Impermanent Loss.
* **`BALANCED`**: Mercato equilibrato standard $\rightarrow$ pesi conservativi proporzionati.

### 2. Allocazione e Ribilanciamento Automatico (`capital_allocator.py` & `treasury.py`)
* **Profit Sweeping**: Drena automaticamente i profitti realizzati dai bot speculativi (Degen, Perp) per consolidarli nella Tesoreria o in Yield.
* **Idle Cash Recycling**: Se un bot non trova opportunità (es. Degen con zero token sicuri), il capitale inattivo viene allocato a rendimento su Aave/Morpho fino a nuova richiesta.
* **Safety Withdrawals**: Ritira la liquidità dai mercati rischiosi in caso di cigni neri.

### 3. Gestione del Rischio e Circuit Breaker (`risk_engine.py`)
* **Delta Netto Globale**: Calcola costantemente l'esposizione reale Long vs Short su Base:
  $$\text{Delta Netto} = \text{Spot}_{\text{DCA}} + \text{Spot}_{\text{Degen}} + 0.5 \cdot \text{Valore}_{\text{LP}} + \text{Long}_{\text{Perp}} - \text{Short}_{\text{Perp}}$$
* **Circuit Breaker 24h**: Se il portafoglio aggregato subisce una perdita superiore alla soglia (`MAX_PORTFOLIO_DRAWDOWN_24H_PCT`, default 8%), congela immediatamente tutti i bot speculativi e attiva l'allerta rossa.

### 4. Gas Balancer Automatico (`gas_balancer.py`)
* Monitora costantemente le riserve di ETH nativo di tutti i sub-wallets dei bot.
* Esegue il refuel automatico dal Master Wallet inviando `0.003 ETH` ai bot che scendono sotto `GAS_WARN_ETH`.

### 5. Control Plane: Master Dashboard & Telegram Bot
* **Web Dashboard unificata** (`http://localhost:3000`):
  * Vista consolidata Net Worth e PnL 24h.
  * Grid con lo stato in tempo reale, equity, gas e link diretti ai 6 agenti.
  * Matrice target vs reale con barre di scostamento (drift).
  * Grafico storico dell'equity curve.
  * Pulsanti interattivi: *Esegui ciclo ora*, *Emergency Stop*, *Avvia singolo agente*.
* **Telegram Bot**: Notifiche periodiche di sintesi e allarmi critici.

---

## 📁 Struttura del Progetto

```
intelligent-trading-agent-coordinator/
├── config.py              # Configurazioni di rete, URL dei 6 bot, parametri di rischio
├── coordinator.py         # Loop principale dell'orchestratore (orologio dei cicli)
├── agent_client.py        # Client HTTP per dialogare con /api/status e /api/run dei bot
├── regime_detector.py     # Classificatore macro: Fear & Greed, trend BTC/ETH, volatilità
├── capital_allocator.py   # Algoritmo di allocazione (%) e calcolo dei drift
├── risk_engine.py         # Net Worth, Delta netto direzionale e Circuit Breaker
├── gas_balancer.py        # Monitoraggio e auto-refuel ETH dei sub-wallets su Base
├── treasury.py            # Gestione trasferimenti on-chain (USDC/ETH) e Paper Ledger
├── db_utils.py            # SQLite (coordinator.db) per storico portfolio e snapshot
├── dashboard.py           # Master Dashboard Web standalone
├── telegram_bot.py        # Notificatore Telegram consolidato
├── static/                # CSS, JS e icone condivise con il design system della suite
├── Dockerfile             # Container multi-ambiente con Python 3.11
├── docker-compose.yml     # Orchestrazione locale
├── captain-definition     # Distribuzione rapida su CapRover
├── requirements.txt       # Dipendenze Python
└── .env.example           # Template variabili d'ambiente
```

---

## 🚀 Installazione e Avvio Rapido

### 1. Installazione Dipendenze
```bash
cd d:/intelligent-trading-agent-coordinator
pip install -r requirements.txt
```

### 2. Configurazione Variabili d'Ambiente
```bash
cp .env.example .env
```
Compila `.env` impostando gli URL delle dashboard dei tuoi bot (es. porte `3001` - `3006`) e l'indirizzo del tuo Master Wallet.

### 3. Test Rapido di un Singolo Ciclo
```bash
python coordinator.py --once
```

### 4. Avvio della Dashboard e del Demone
```bash
python dashboard.py
```
Accedi da browser a: **`http://localhost:3000`**

---

## 🚢 Distribuzione su CapRover & Docker

Il progetto include il file `captain-definition` e il `Dockerfile` per il deploy one-click su CapRover:
1. Crea una nuova app `ita-coordinator` sulla tua dashboard CapRover.
2. Configura le variabili d'ambiente (copiando da `.env.example`).
3. Imposta un volume persistente su `/app/data` (label `coordinator-data`).
4. Fai il deploy via Git o CapRover CLI (`caprover deploy`).

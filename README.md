<img src="static/icon.svg" alt="" width="88" height="88" align="left">

# Intelligent Trading Agent - Master Coordinator (Base L2)

<br clear="left">

**English** · [Italiano](README.it.md)

> ⚠️ **Experimental software, not financial advice.** The coordinator moves real money between the bots on Base and can contribute to losing some or all of the capital. Start in paper mode (the default); when you go live, use dedicated wallets and only amounts you can afford to lose. See the **Disclaimer** section at the bottom.

The central agent for **strategic orchestration, capital allocation and
global risk management** of the bot family on **Base (chain ID 8453)**.

The coordinator connects and governs the 6 specialized agents of the
[Intelligent Trading](https://github.com/scobru/intelligent-trading) suite,
moving capital between them according to the market regime and protecting the
portfolio with consolidated risk controls.

---

## 🌟 The 6 subordinate agents

| Agent | Primary strategy | Risk focus | Base protocols |
|---|---|---|---|
| [intelligent-trading-agent-perp](https://github.com/scobru/intelligent-trading-agent-perp) | **Directional perpetuals** with leverage | High / trend & momentum | SynFutures V3 (`synfutures-service`) |
| [intelligent-trading-agent-yield](https://github.com/scobru/intelligent-trading-agent-yield) | **Passive yield** on lending/vaults | Minimal / parked capital | Aave V3, Morpho, Moonwell, ERC-4626 |
| [intelligent-trading-agent-neutral](https://github.com/scobru/intelligent-trading-agent-neutral) | **Delta-neutral funding carry** | Low / cash & carry | Uniswap V3 (spot) + SynFutures V3 (short) |
| [intelligent-trading-agent-lp](https://github.com/scobru/intelligent-trading-agent-lp) | **Concentrated AMM liquidity** | Medium / fee harvesting & IL | Uniswap V3 NonfungiblePositionManager |
| [intelligent-trading-agent-dca](https://github.com/scobru/intelligent-trading-agent-dca) | Weighted **DCA & rebalancing** | Medium-low / WETH/BTC accumulation | Uniswap V3 with a Fear & Greed multiplier |
| [intelligent-trading-agent-degen](https://github.com/scobru/intelligent-trading-agent-degen) | **Speculative spot / memecoins** | Very high / asymmetric | Uniswap V3 with GoPlus Security screening |

---

## 🧠 Key features

### 1. Dynamic market regime detection (`regime_detector.py`)
Classifies macro crypto market conditions in real time:
* **`BULL_MOMENTUM`**: Greed sentiment ($\ge 68$) and a positive trend $\rightarrow$ more budget for Perp (25%) and Degen (15%).
* **`BEAR_PANIC`**: Extreme Fear ($\le 26$) or crashes $\rightarrow$ 50% parked in passive Yield, 30% to DCA on the dips, 0% Degen/LP.
* **`RANGE_CHOP`**: low volatility and sideways markets $\rightarrow$ maximizes the budget for concentrated LP (30%) and funding carry (25%).
* **`HIGH_VOLATILITY`**: shocks or extreme swings $\rightarrow$ 65% in protected Yield, immediate withdrawal of LP liquidity to stop impermanent loss.
* **`BALANCED`**: standard balanced market $\rightarrow$ proportional, conservative weights.

### 2. Automatic allocation and rebalancing (`capital_allocator.py` & `treasury.py`)
* **Profit sweeping**: automatically drains realized profits from the speculative bots (Degen, Perp) into the treasury or into Yield.
* **Idle cash recycling**: if a bot finds no opportunities (e.g. Degen with zero safe tokens), its idle capital is put to work on Aave/Morpho until it is needed again.
* **Safety withdrawals**: pulls liquidity out of risky markets during black swan events.

### 3. Risk management and circuit breaker (`risk_engine.py`)
* **Global net delta**: continuously computes the real long vs short exposure on Base:
  $$\text{Net Delta} = \text{Spot}_{\text{DCA}} + \text{Spot}_{\text{Degen}} + 0.5 \cdot \text{Value}_{\text{LP}} + \text{Long}_{\text{Perp}} - \text{Short}_{\text{Perp}}$$
* **24h circuit breaker**: if the aggregated portfolio loses more than the threshold (`MAX_PORTFOLIO_DRAWDOWN_24H_PCT`, default 8%), it immediately freezes all the speculative bots and raises a red alert.

### 4. Automatic gas balancer (`gas_balancer.py`)
* Continuously monitors the native ETH reserves of all the bots' sub-wallets.
* Automatically refuels from the master wallet, sending `0.003 ETH` to bots that drop below `GAS_WARN_ETH`.

### 5. Control plane: master dashboard & Telegram bot
* **Unified web dashboard** (`http://localhost:3000`):
  * consolidated net worth and 24h P&L;
  * grid with the real-time status, equity, gas and direct links to the 6 agents;
  * target vs actual matrix with drift bars;
  * historical equity curve;
  * interactive buttons: *Run cycle now*, *Emergency stop*, *Pause / resume / run a single agent*, *Release funds*.
* **Every command requires `DASHBOARD_RUN_TOKEN`** (sent as `X-Run-Token` or
  `Authorization: Bearer`): the coordinator forwards commands to the bots with
  `AGENT_RUN_TOKEN`, so without this check anyone reaching the dashboard could
  command the bots. Until the token is set, the commands stay disabled; the
  browser asks for it once and remembers it.
* **Telegram bot**: periodic summaries and critical alerts.

---

## 📁 Project structure

```
intelligent-trading-agent-coordinator/
├── config.py              # Network settings, URLs of the 6 bots, risk parameters
├── coordinator.py         # Orchestrator main loop (cycle clock)
├── agent_client.py        # HTTP client for the bots' /api/status and /api/run
├── regime_detector.py     # Macro classifier: Fear & Greed, BTC/ETH trend, volatility
├── capital_allocator.py   # Allocation algorithm (%) and drift computation
├── risk_engine.py         # Net worth, directional net delta and circuit breaker
├── gas_balancer.py        # Monitoring and ETH auto-refuel of the sub-wallets on Base
├── treasury.py            # On-chain transfers (USDC/ETH) and paper ledger
├── db_utils.py            # SQLite (coordinator.db) for portfolio history and snapshots
├── dashboard.py           # Standalone master web dashboard
├── dashboard_auth.py      # Token check for the dashboard commands (same file as in the bots)
├── telegram_bot.py        # Consolidated Telegram notifier
├── static/                # CSS, JS and icons shared with the suite's design system
├── Dockerfile             # Python 3.11 container
├── docker-compose.yml     # Local orchestration
├── captain-definition     # Quick deployment on CapRover
├── requirements.txt       # Python dependencies
└── .env.example           # Environment variables template
```

---

## 🚀 Installation and quick start

### 1. Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment variables
```bash
cp .env.example .env
```
Fill in `.env` with the dashboard URLs of your bots (e.g. ports `3001` -
`3006`), your master wallet address, `DASHBOARD_RUN_TOKEN` and, if your bots'
dashboards sit behind HTTP basic auth, `AGENT_HTTP_USER` / `AGENT_HTTP_PASS`
(there are no defaults in the code). `DRY_RUN` and `PAPER_TRADING` are on by
default.

### 3. Quick test of a single cycle
```bash
python coordinator.py --once
```

### 4. Start the dashboard and the daemon
```bash
python dashboard.py
```
Open **`http://localhost:3000`** in your browser.

---

## 🚢 Deploying on CapRover & Docker

The project includes a `captain-definition` file and a `Dockerfile` for
one-click deployment on CapRover:
1. Create a new app, e.g. `ita-coordinator`, in your CapRover dashboard.
2. Set the environment variables (copy them from `.env.example`).
3. Set a persistent volume on `/app/data` (label `coordinator-data`).
4. Deploy via Git or the CapRover CLI (`caprover deploy`).

---

## ⚠️ Disclaimer

This software is experimental and provided "as is", without warranty of any
kind (see the MIT license). It is not financial advice nor an invitation to
invest.

- **You can lose money.** Bugs, wrong model decisions, slippage, protocol
  exploits, manipulated oracles and liquidations can cause the loss of some or
  all of your capital.
- **Decisions are made by an LLM.** It can be wrong or behave unpredictably:
  the executor's limits reduce the damage, they do not eliminate it. Past
  results, paper ones included, do not guarantee future ones.
- **Start with paper or dry-run.** When live, use a wallet dedicated to the
  bot, with amounts you can afford to lose, and never reuse that private key
  elsewhere.
- **Protect your keys.** The private key belongs only in the deployment's
  environment variables: never commit it. Without `DASHBOARD_RUN_TOKEN` the
  dashboard commands stay disabled: set it to a long random value before
  exposing the dashboard to the Internet.
- **Laws and taxes.** You are responsible for complying with the rules and tax
  obligations of your country.
- **The coordinator moves money.** Profit sweeping, capital reallocation,
  release-funds commands and the gas balancer sign transfers from the master
  wallet and trigger swaps and withdrawals in the bots. A wrong regime or a
  misconfigured bot URL can move capital where you did not expect it: start in
  paper mode and give the master wallet only what the suite needs.

## 📜 License

MIT.

# Polo CopyTrade · v0.2.1

[中文](README.zh-CN.md) · English

A local full-stack app for observing public Binance lead-trader operations, configuring follow rules, and explicitly connecting a USDT perpetual futures account. The navy, white and teal **P** identifies Polo without implying market direction.

**Account execution and the paper lab are separate. Production sessions can send real orders.** Startup does not connect an account or start trading. This release has local tests, but no completed online exchange, source or automated browser validation.

| Workspace | Funds / orders |
|---|---|
| Account: Production | Actual balances and real exchange orders after explicit start |
| Account: Testnet | Binance futures testnet API orders with separate testnet keys |
| Paper lab | Synthetic or public observations with local simulated fills |

## Run

Python 3.10+ is required. The dashboard and synthetic demo need no third-party package.

~~~powershell
python -m backend.server
~~~

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) or double-click `start.cmd`. Stop with Ctrl+C. Open `copytrade-studio.code-workspace` in VS Code. **After updating, restart the old Python server before refreshing the browser.**

For public collection and account following, run setup.cmd on Windows to prepare the project environment and install Playwright/Chromium. Run check.cmd for a local readiness report; neither script connects an account or places an order. Manual commands:

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-collector.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m backend.connect
~~~

Or run `connect-account.cmd`, which prefers an existing project virtual environment. Select production or testnet and enter hidden credentials locally. Keys remain in the process environment, are not saved to source files, and are not accepted by the browser API. Never send them to chat or GitHub.

Connecting reads the account only. Add a public trader, verify access permission and source timezone, pause its paper collector, select it in the account workspace, fill your own parameters and explicitly start. Follow the [bilingual account guide](docs/ACCOUNT_GUIDE.md).

## Execution

- Default **3% adverse entry deviation on both sides**: source long 100 permits buys up to 103; short 100 permits sells down to 97. Favorable prices pass. This measures deviation from the source price, distinct from execution slippage from the current quote.
- Account openings use IOC LIMIT orders. Partial/zero fills are possible. Intents are persisted before submission; uncertain outcomes are queried without blind resubmission.
- Each close signal reduces a user-selected fraction of this app's owned position through reduce-only orders. Public quantities do not reveal hidden leverage or the source trader's closing percentage. Late closes halt following for review.
- Following fills, the adapter submits and confirms a mark-price STOP_MARKET close-all protective order. Protection installation failure attempts a durable reduce-only exit and halts. Network failures, gaps and liquidation can still prevent the expected result.
- Paper stops need a running backend. Confirmed exchange stops remain at Binance when the backend stops.
- Each explicit account start creates a fresh observation baseline, without replaying old openings. Existing owned exposure blocks a fresh session until reviewed.
- Session loss budget compares actual equity with flat-start equity, including fees/funding and transfer effects. Use a dedicated account and avoid transfers/manual trading.

Multiple paper traders are supported. Account execution supports **one active trader per dedicated account**, one-way positions, single-asset USDT margin, isolated perpetuals and manually configured leverage.

## Runtime and validation

The backend, network and machine must stay running and awake; the browser may close. Publication delay, polling and network/API execution contribute to total latency. No verified upstream delay SLA exists.

Pause new entries keeps observing valid closes; Stop following stops observation without automatic liquidation or cancellation of confirmed exchange stops. Inspect actual positions before stopping or switching.

The service binds to loopback and checks Host, Origin and CSRF. It is not an authenticated public multi-user service. GitHub stores code; GitHub Pages cannot run this Python backend. Permanent hosting needs access control, supervision, secrets and monitoring.

~~~powershell
python -m unittest discover -s tests
node --check frontend/app.js
node --check frontend/live-ui.js
~~~

See [API](docs/API.md), [validation](docs/VALIDATION.md) and [production work](docs/PRODUCTION.md). No user's account was connected and no real order was sent during development.

| Component | Responsibility |
|---|---|
| `backend/core.py` | Paper rules and persistent multi-trader ledger |
| `backend/feeds.py` | Synthetic feed, public page parser and scheduler |
| `backend/live.py` | Account client, protective stops, session manager |
| `backend/executor.py` | Sizing, durable intents, order execution and recovery |
| `backend/connect.py` | Local hidden credentials and launcher |
| `backend/server.py` | Local API and static assets |
| `frontend/` | Bilingual account workspace and separate paper lab |

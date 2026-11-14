# Local API · v0.2

Base: `http://127.0.0.1:8765`. Account and paper execution are separate.

GET `/api/session` returns a per-process CSRF token. All POSTs require JSON, `X-CSRF-Token`, an allowed Host and allowed Origin when present. This is not multi-user authentication.

| Method | Route | Behavior |
|---|---|---|
| GET | `/api/state` | Paper data, traders, signals and logs; mode remains paper |
| GET | `/api/live/state` | Actual account snapshot when connected, environment, session and orders; no keys |
| POST | `/api/live/connect` | Empty object; uses local environment credentials and reads account; no order |
| POST | `/api/live/refresh` | Refresh actual account snapshot |
| POST | `/api/live/start` | Explicit trader_id and complete config; asynchronously verifies and starts following |
| POST | `/api/live/pause` | Boolean paused; blocks entries while continuing observation |
| POST | `/api/live/stop` | Request stop without automatic liquidation |
| GET | `/api/config/export` | Paper trader settings; no credentials |
| GET | `/api/events.csv` | Latest 300 paper observations; spreadsheet formula prefixes escaped |
| POST | `/api/traders` | Create paused trader |
| POST | `/api/traders/{id}/config` | Edit paused, flat paper trader; blocked during its active account session |
| POST | `/api/traders/{id}/toggle` | Boolean enabled; paper collection, cannot share active account source |
| POST | `/api/traders/{id}/demo` | Synthetic paper operation, optional scenario over_deviation |
| POST | `/api/traders/{id}/close` | Close paper positions only; optional symbol and side |
| POST | `/api/pause` | Pause paper entries; retain paper close/stop checks |
| POST | `/api/mode` | Paper compatibility only; cannot convert paper into account trading |

Account start config requires: budget, order_margin, leverage, max_deviation, stop_loss_pct, close_fraction, max_loss, max_signal_age, symbols, poll_seconds, utc_offset_minutes, fee_rate. Percentage fields are API fractions (3% = "0.03"); UI uses percent. Actual fees affect exchange equity, not the paper fee assumption.

A successful start response schedules verification, not proof of successful collection or an order. Inspect watching, error and actual order results. online_verified:false describes this release's verification limit, not current account connectivity.

Allowed source URL: `https://www.binance.com/[zh-CN/]copy-trading/lead-details/{numeric_id}`. No login or challenge bypass. Browser connect payload credentials and unknown paper config fields are rejected. Source size never infers hidden holdings.

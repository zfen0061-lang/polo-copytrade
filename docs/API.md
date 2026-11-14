# Local API

Base URL: `http://127.0.0.1:8765`. Single-user loopback service; paper execution only.

GET `/api/session` returns a per-process CSRF token. Every POST requires JSON, the token in `X-CSRF-Token`, an allowed Host, and an allowed Origin when present. No wildcard CORS. The token is not a replacement for production authentication.

| Method | Route | Behavior |
|---|---|---|
| GET | `/api/state` | Current capabilities, traders, paper metrics, positions, latest 200 orders, latest 300 signals, latest 100 logs |
| GET | `/api/config/export` | Schema-versioned trader configuration; no exchange credentials |
| GET | `/api/events.csv` | Latest 300 signal records; text formula prefixes escaped |
| POST | `/api/traders` | Create a paused trader with validated URL/source/config |
| POST | `/api/traders/{id}/config` | Edit a paused trader with no open paper positions |
| POST | `/api/traders/{id}/toggle` | `{ "enabled": true }`; public source requires verified timezone, access confirmation and optional collector dependency |
| POST | `/api/traders/{id}/demo` | Generate one synthetic signal; `{ "scenario": "over_deviation" }` generates a 5% adverse entry |
| POST | `/api/traders/{id}/close` | Close owned paper positions at last stored paper quotes; optional `symbol` and `side` |
| POST | `/api/pause` | `{ "paused": true }` blocks new entries but not valid closes or local paper stops |
| POST | `/api/mode` | Only paper is accepted; a live request returns 409 and sends no order |

Portfolio URLs must point to `https://www.binance.com/[zh-CN/]copy-trading/lead-details/{numeric_id}`. This is a strict destination allowlist, not arbitrary URL fetching. Unknown config fields, including attempted credential fields, are rejected.

Amounts are stored as decimal strings. `max_deviation`, `stop_loss_pct`, `close_fraction` and `fee_rate` are fractions in the API; the UI displays percentages. `order_margin × leverage` gives the approximate notional used to size each paper opening. The source trader's quantity is not used to infer hidden leverage or total position size.

# Production integration / 实盘接入边界

The application currently executes paper orders only. A live-mode API request is rejected, and there is no live API credential input. This boundary is deliberate and visible in the UI; it is not a claim that the previous real-order prototype is production-ready.

当前前后端 App 只执行模拟交易，不能通过更改前端显示状态启用实盘。此前命令行中的真实下单接口原型没有接到这里。

## Required before a live executor can be delivered

1. **Authorized signal adapter / 获准的数据接口**: establish source access rights, verify identity/portfolio ID and timezone, capture first-seen timestamps, quantify publication delay, detect gaps and preserve source ordering. Public UI access is not proof of automated-access permission or a fixed latency SLA.
2. **Live execution adapter / 真实执行器**: correct account type, symbol filters, quantity/price rounding, account mode, leverage/margin checks, real available balance, rate-limit handling, clock synchronization, order identifiers and explicit trade sizing rules.
3. **Exchange-side protection / 交易所保护单**: after every actual fill, submit and verify protective stops, handle partial fills and changing stop quantities, track trigger basis, clean up orphaned orders, and define what happens if protection fails. A browser timer is not an exchange stop.
4. **Reconciliation / 对账恢复**: use account execution streams plus REST recovery. Persist intent before submission, query uncertain orders before any resend, and distinguish exchange stops from manual intervention. Never claim exactly-once execution merely because a local database has unique rows.
5. **Multi-trader ownership / 多交易员仓位归属**: distinguish per-trader virtual allocations from the exchange's net/hedged positions. If two traders use the same symbol, one trader must not close another's allocation or a manual position. The paper ledgers in this version are isolated, but no exchange-side isolation is implemented.
6. **Risk policy / 风险规则**: user-specified allocation, leverage, total exposure, loss budgets, signal freshness, permitted slippage and source-switch behavior. Late close signals require reconciliation rather than blindly replaying historical trades. Unknown source closing percentages cannot be reconstructed from hidden positions.
7. **Online verification / 在线验证**: official demo environment, partial fills, disconnects, rejected stops, rate limits, duplicate events, process crashes, restarts and source-format changes. Then an explicitly user-configured production connection. No capital or leverage should be inferred from demo settings.
8. **Deployment / 部署**: durable service, supervision, secrets management, telemetry, time synchronization, backups and an authenticated frontend. GitHub stores source code; a private repository does not host a permanent trading engine.

Official references (consult current account-specific rules):

- https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order
- https://www.binance.com/en/support/faq/detail/30f1e3a2835345e0b8ffc87f261a8256

## Repository descriptions

**中文**：支持多交易员切换、独立参数、3%跟随价差控制、模拟执行和信号延迟记录的本地前后端研究应用。用于评估官方跟单不可用时公开操作数据的跟随可行性；不突破名额限制、不读取隐藏仓位，当前不支持实盘。

**English**: A local full-stack research app for multi-trader selection, configurable follow rules, a default 3% adverse entry-deviation limit, paper execution and auditable signal-latency logs. It evaluates public-signal strategies when official copying is unavailable; it does not bypass follower capacity, reveal hidden positions or support live trading in this release.

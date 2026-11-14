# Production status / 上线状态

v0.2 includes production/testnet account execution code. It has not completed online certification. No user's account or real funds were used in development.

## Implemented / 已实现

Separate account/paper UI; local hidden key entry; read-only connection; explicit parameters; one active trader; IOC limit openings and reduce-only closes; persisted intent and query-first recovery; exchange STOP_MARKET confirmation; protection-failure exit attempt; periodic position reconciliation and equity loss budget. No automatic following after restart.

The execution lock covers one local data directory, not all machines or accounts. Use one process per dedicated account.

## Before unattended use / 无人值守前

1. Verify source access, trader identity, timezone, parsing and measured publication delay. No fixed-delay guarantee or hidden data access exists.
2. Exercise actual testnet keys, account modes, filters, partial fills, stops, uncertain responses, rate limits, restarts and manual position changes.
3. Add authenticated account event-stream recovery, broader algo-state coverage and latency measurement. No exactly-once claim is made.
4. Concurrent real traders need verified virtual ownership and net-position reconciliation; first release rejects mixed/manual positions.
5. Add durable hosting, authenticated access, process supervision, restricted permissions/IPs, time synchronization, alerts and backups.
6. Only after online checks, use personally chosen production limits and inspect exchange confirmations. Demo amounts are not allocation advice.

本版未部署云服务或手机推送。UI日志在本机；机器停止就不会观察新操作。已确认交易所保护单仍可能触发，但不保证成交价格。

## Repository descriptions / 仓库简介

中文：Polo CopyTrade 是支持交易员切换、自定义参数和默认3%不利开仓价差的本地前后端跟单应用，分离模拟实验室与币安账户工作台，含测试网和正式账户执行适配器。不突破官方跟单容量、不读取隐藏仓位；真实接口尚待在线端到端验证。

English: A local full-stack copy-trading app with trader selection, configurable rules and default 3% adverse entry deviation. The paper lab is separate from Binance testnet/production execution. It does not bypass official capacity or reveal hidden positions; online end-to-end validation remains necessary.

## Primary documentation

- [Futures general information](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- [New order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)
- [New algo order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order)
- [Query algo order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Algo-Order)

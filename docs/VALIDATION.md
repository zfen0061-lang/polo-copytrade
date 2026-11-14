# Validation / 验证记录

v0.2.1: **44 local automated tests passed**: 21 core, 6 in-memory HTTP, 17 account-engine. Both JavaScript modules pass syntax checking.

Core covers long/short 3% boundaries, favorable prices, duplicate events/restarts, stale entries/late closes, independent paper ledgers, budgets, pauses, stops, timestamps and URL restrictions.

HTTP tests execute actual request parsing through in-memory byte streams: static logo/module routes, disconnected account state, browser credential rejection, Host/CSRF/Origin checks and paper/account separation.

Account tests use a fake exchange: read-only connect, rejection of demo arming/incomplete params, confirmed stops, partial/full closes, failed protection with full/partial exit attempts, uncertain order recovery, triggered/missing stops, manual quantity/flat changes, flat-only config changes and no submission after stopping during source retrieval. That scenario also exposed a Windows SQLite status-read handle leak; connections now close explicitly.

**No actual Binance credentials, real orders or source-to-exchange end-to-end runs were used.** Local passing tests do not establish live integration or financial results.

本版44项本地测试使用虚拟客户端，没有连接你的账户，没有向币安提交真实订单；实际密钥、公开采集、测试网和正式接口还需在线验证。

## Environment limits / 环境限制

The execution environment rejected local HTTP TCP clients with Windows socket error 10013. In-memory tests do not replace real-port checks. No automated browser rendering or interactive verification was completed. The VS Code CLI returned a permission error; no editor window was verified open.

用户已能访问旧版网页，不等于新版UI或交易接口已完成端到端验证。模拟成交省略深度、资金费和强平；真实延迟及故障恢复仍未实测。

## Setup recovery checkpoint / 环境续接检查

The project virtual environment was created. Local doctor reports dashboard ready but public collection unavailable: Playwright is not installed. The current package source returned no matching distribution; no collector was installed. setup.cmd and check.cmd allow installation and diagnosis from the user terminal. Missing dependencies are reported before an account-follow session starts. Online exchange and browser validation remain pending.

A subprocess smoke check started the backend on port 8766 with a temporary database and no scheduler. Startup reported account execution OFF and the process stayed running until deliberately stopped. This verifies process startup, not a TCP client, browser rendering or online account access.

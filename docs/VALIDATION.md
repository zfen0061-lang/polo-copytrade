# Validation / 验证记录

## Local checks

2026-11-15: **26 tests passed** (21 domain tests and 5 in-memory HTTP tests). JavaScript syntax checking passed. These results are local checks, not a live-exchange certification.

2026-11-15：26项本地测试通过（21项交易规则/数据处理、5项内存HTTP接口），JavaScript语法检查通过。

- Domain tests cover 3% entry boundaries for longs/shorts, favorable prices, duplicate events across restarts, first-read baselines, stale entries, late reductions, no reverse opening from a close, independent trader ledgers, entry pause semantics, local paper stops, fees, budgets, parameter locks, timestamps and source URL restrictions.
- HTTP tests execute `BaseHTTPRequestHandler`'s real request parser and response writer through in-memory byte streams. They cover static assets, state, creation/toggling/demo, exports, Host checks, CSRF/same-origin mutation checks and live-mode rejection.
- JavaScript receives a syntax check with `node --check frontend/app.js`.

## Environment limitations

The execution environment returned Windows socket error 10013 when a test client tried to connect to a local HTTP server. These TCP tests did not complete. In-memory HTTP tests do not replace that missing check. Browser rendering, visual layout and interactive UI have not been verified through an automated browser in this environment. The VS Code CLI also returned a permissions error while trying to change into its installation directory; the editor window was not verified open.

本环境阻止了真实回环 HTTP 客户端连接（WinError 10013）。内存 HTTP 测试可以验证请求解析与路由，但不代表端口连接或浏览器交互已通过。VS Code 启动命令也受到权限限制，不能据此声称编辑器窗口已经打开。

No Binance account is connected. No real orders were submitted. The optional public collector has not been exercised end-to-end in this release. Paper fills omit liquidity/depth, funding and exchange liquidation behavior.

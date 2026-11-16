# 实盘自动跟随 / Production automatic following

从 8765 首页进入：点击顶部“进入实盘跟单”按钮，或左侧“实盘跟单”。两处都会在当前标签页打开 8767，可查看专用跟单账户的运行状态、参数、持仓和交易记录；账户查看与采集页不代表实盘会话的启停状态。

From the port 8765 homepage, use the prominent Open live copy trading button or the sidebar link. Both open port 8767 in the same tab, showing the dedicated account's status, settings, positions and trade history. The read-only collection page does not report the production session's execution state.

桌面旧图标如果仍打开 8765，请在项目目录双击 `repair-real-desktop-shortcut.cmd` 一次。它会备份旧快捷方式，并将同名的 Polo CopyTrade 图标改为打开 8767 的实盘页面；不重新下载程序、不修改密钥、不启动下单。该步骤需要用户在本机运行。此后双击桌面图标会复用当前后台，或启动本安装的独立后台任务；自动交易仍需在页面中明确启动一次。

If the old desktop shortcut still opens port 8765, run `repair-real-desktop-shortcut.cmd` locally once. It preserves the previous shortcut and links Polo CopyTrade to this source installation's production workspace on port 8767. It does not download an old release, replace credentials, or enable trading. Opening the shortcut reuses the workspace or starts this installation's separate background tasks; order execution still requires an explicit dashboard start.

此功能已接入源码中的共用策略引擎。它不是逐笔人工确认工具：用户在本机明确启动一次后，程序可按已保存规则自动处理后续公开信号。打开页面、保存参数、读取账户或重启服务不会自行启动交易。

This source implementation connects the shared strategy to a separately gated production transport. One explicit local user start enables subsequent automatic order handling; individual signals do not require manual confirmation. Opening, configuring, inspecting or restarting the workspace does not start trading.

## 三个入口 / Workspaces

| 地址 | 用途 | 启动后默认状态 |
|---|---|---|
| http://127.0.0.1:8765 | 实盘账户只读、公开信号采集 | 实盘下单关闭 |
| http://127.0.0.1:8766 | 独立 Demo 自动执行 | 需单独启动 Demo |
| http://127.0.0.1:8767 | 实盘自动跟随控制台 | 未授权下单 |

源码安装双击 `open-real-workspace.cmd`，或在项目终端运行：

```powershell
.\.venv\Scripts\python.exe -m backend.real_connect
```

已打开的同一工作台会被复用。启动器不会创建执行授权，不会携带明文密钥到命令行、环境变量、浏览器或日志。已有旧版可下载 EXE 不包含此更新；本次没有构建或发布新版安装包。未来重新构建的运行包将包含 `Open-Real-Workspace.cmd`。

The source launcher reuses the same workspace and starts only a disarmed local service. It never passes credentials through arguments, environment, browser requests or logs. The previously published executable does not contain this source update; no new binary release is claimed here.

## 本机启动 / Local user start

1. 保持 8765 的采集后台运行，确认目标为熬鹰资本、公开数据新鲜。
2. 打开 8767，查看或调整实盘参数；启动按钮会先保存本次编辑。单独保存参数不会下单。
3. 首次连接时运行 `connect-trading-subaccount.cmd`，在本机隐藏输入窗口填写已在币安核对归属的子账户 API Key 和 Secret。账户读取验证通过后单独加密保存；主账户与 Demo 连接不会被覆盖，浏览器不接收密钥。以后正常启动不必重建 API。“刷新账户”可单独读取状态，不是启动前必须点击的步骤。
4. 页面列出阻止启动的具体问题。程序要求：账户可交易、单向持仓、单资产 USDT、可用 USDT 足够、没有已有仓位或委托、账本没有待确认订单或遗留保护记录。BNB 合约手续费支付须关闭；本版只核算 USDT 手续费。
5. 点击“启动实盘自动跟随”。程序自动核对账户和信号，没有阻碍时弹出当前金额、杠杆、止损和跟随规则，用户确认后开始。无需勾选框、复制或输入启动短语；取消确认不会启动或下单。
6. 后台再次核对账户和来源，建立当前历史基线后只跟随后续新信号。页面保持自动刷新。

Click Start to save any edited settings and perform read-only preflight automatically. The user confirms the displayed funding and rules in one dialog; no checkbox or typed/copied phrase is required. Cancelling leaves execution disabled. The client retains the current account/policy-bound review handshake internally, and the worker rechecks ownership, capital, mode and source under the production execution lock before arming. Existing public history is baselined; old openings are never replayed.

## 本次规则 / Rules

| 项目 | 规则 |
|---|---|
| 初始策略分配 | 60 USDT；独立核算已验证净收益、手续费与资金费，并复投 |
| 同时持仓 | 一个共享资金池最多一笔持仓，不叠加同品种开仓；未采用尚未敲定的多仓分配方案 |
| 加密货币杠杆 | 当前用户参数为 10 倍，代码上限 10 倍 |
| 股票／传统资产 | 当前用户参数为 3 倍，类别按实盘合约元数据核对 |
| 开仓价差 | 做多用卖一，做空用买一，`abs(报价/来源成交价 - 1) <= 0.03`；下单前复核，不满足则跳过 |
| 入场处理时限 | 本机首次检测后 60 秒；来源成交时间另用于记录发布／检测延迟 |
| 平仓信号 | 全平该合约、该方向的本程序持仓，不受入场价差或入场时限限制 |
| 止损 | 当前目标为初始保证金亏损 40%，按标记价格生成交易所 STOP_MARKET；费用、资金费、滑点不包含在该目标内 |
| 累计亏损 | 当前为相对初始策略资金净亏损 60 USDT；达到时尝试退出本程序仓位并停止新开仓 |
| 止盈 | 无固定止盈，跟随匹配的平仓信号 |

策略预算不是交易所子账户，也不是物理隔离的资金钱包。空池入场前，目标合约必须支持逐仓并关闭自动追加保证金；程序可准备逐仓和用户选定杠杆并回读，不会切换账户模式或启用自动补保证金。已有手动仓位会阻止启动，不能通过本页自动接管、平掉或并入资金池。

Entry quotes use an absolute band for both directions and IOC limit orders. The limit bounds adverse execution, but a quote check cannot guarantee every eventual favorable fill remains inside an absolute band during a rapid market move. Exits use full owned quantity and reduce-only market orders. A strategy budget is accounting, not a segregated exchange wallet. Isolated margin and disabled automatic margin additions are required for the target contract. Manual positions are never adopted.

候选合约列表来自明确保存的策略，每次入场核对实盘可交易状态与类别。列表中的全部合约未逐一做过交易所实单验证，不保证每个品种、地区、最小名义金额或交易时段都允许成交。

## 暂停、停止与重启 / Pause, stop and restart

- “暂停新开仓”：继续处理匹配平仓、账本核对和保护维护。
- “全平本程序仓位”：明确请求退出本程序持仓，并暂停新开仓；不会平掉别人的仓位。
- “停止跟随”：停止本次执行，不代表全平；已确认的交易所止损继续保留。
- 关闭网页不停止后台。电脑须接电、不睡眠并保持网络；当前已有只读监测与防睡眠任务仍独立运行。
- 进程或系统重启后只恢复连接，执行保持关闭。若有持仓、未确认订单或未清理保护，须先核对，不能用新空账本假装继续。
- `data/STOP_REAL_TRADING` 会阻止启动并停止后续跟随；已有交易所保护不被该文件删除。

The worker never blindly repeats an unknown submission. Stable client IDs, durable intents, verified fills and stop acknowledgements are retained. Network, API permission, rate-limit, ownership or accounting errors may halt following. Exchange-resident stops do not depend on the web page, but order placement/fills and loss amounts cannot be guaranteed under all conditions.

## 账本与隐私 / Journal and privacy

默认执行目录为 `data/real-v2/`，策略文件 `real-policy.json`，账本 `real-execution.sqlite3`。与 Demo 数据目录严格分开。API 身份和策略指纹会阻止错误账本被继续使用；有交易历史时不能通过改参数清零资金。其他分配或策略变更需要独立审核，不应删除旧账本。

实盘交易使用独立的当前 Windows 用户 DPAPI 文件 `data/real-v2/account-trading.dpapi`，主账户只读文件 `data/account-readonly.dpapi` 和 Demo 文件不会被覆盖或作为回退。连接存在本身不会授权交易；实盘工作台仍需用户明确启动。接入器会拒绝与已知主账户监测 API 相同的 Key，也会阻止替换有历史的其他账户账本；这不替代用户在币安对子账户邮箱/UID及 API 归属的确认。运行文件、数据库、日志和密钥文件均不应推送到 GitHub。

The dedicated trading connection uses its own Windows-user DPAPI file and encryption context. It never falls back to or overwrites the main monitoring or Demo connection. The local hidden-input connector verifies account reads without orders; sub-account ownership must still be confirmed in Binance. The process-local execution permit is revoked when the worker stops and is never persisted. HTTP rejects credential entry, arbitrary trading commands, Demo rehearsal commands and legacy execution controls in this workspace.

## 验证范围 / Validation boundaries

实盘模块使用离线交易所替身验证开多、开空、分类杠杆、超价差跳过、完整平仓、重复信号、止损结算、保护失败退出、丢失回执查单、未知订单重启、授权失效、手动仓位冲突、互斥锁和 HTTP 隔离。另以独立的浏览器替身场景验证控制页。

**离线替身通过不等于真实资金交易已通过。开发与本次验收不发送真实订单，不代用户启动实盘。实际公开信号驱动的 Demo 开平仓和真实交易所止损触发验证仍以记录中的实际结果为准。**

Production integration is implemented in source, with offline and browser-fixture evidence. That is not proof of a successful real-money cycle, overnight reliability or actual exchange stop-trigger execution. See `DEMO_VERIFICATION.md` for the historical exchange results and unresolved evidence.

Official API references used for transport checks:

- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade
- https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
- https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/general-info

## IP 白名单 / IP allowlist

白名单应填写运行后台的电脑或服务器当前使用的公网出口 IPv4，不是 127.0.0.1、局域网地址或设备固定编号。换网络、代理或宽带重新拨号后出口可能变化，需要在币安现有 API 的 IP 限制中更新地址，而不是重建 API。保存可能要求安全验证。HMAC 密钥在没有 IP 限制时可能仅有读取权限；以币安实际权限为准。固定出口服务器可减少地址变化，但不改变平台的地区使用条件。

The allowlist must match the backend's public egress IPv4. A changed network or proxy may require editing the existing key's allowlist, not recreating the key. Fixed egress and jurisdictional availability are separate concerns. Unrestricted HMAC keys may be limited to reads by Binance's default controls.

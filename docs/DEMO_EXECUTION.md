# 测试网执行台 / Futures Demo workspace

当前入口只允许币安合约 Demo，固定网关 `https://demo-fapi.binance.com`。它不会读真实账户加密密钥，不会改变真实仓位、杠杆或账户模式。真实账户继续在 `http://127.0.0.1:8765` 只读监测。

## 本机使用

1. 保持只读监测正常采集熬鹰资本。
2. 双击 `open-demo-preview.cmd`，在 `http://127.0.0.1:8766` 查看测试台。当前桌面安装的旧 v0.3.0-preview 不包含这些源码新增入口。
3. 在 https://demo.binance.com/zh-CN/my/settings/api-management 创建单独的合约 Demo HMAC API。现有真实账户 API 不需要重建。
4. 双击 `connect-demo-v2.cmd`，只在本机隐藏输入 Demo Key 与 Secret。如果预览已运行，会通过经认证的本地管道送入该会话，密钥不会经过网页表单或 HTTP 请求。已经接入时重复打开入口会复用会话；只有明确 `--replace` 才更换密钥。
5. 在测试台点“验证 Demo 账户（不下单）”。明确选择累计亏损口径，保存测试参数，并在 Demo 交易所手动核对相应合约杠杆。程序不自动修改账户模式或杠杆。
6. 勾选虚拟资金确认，点“启动测试网跟随”。此前不会下单。当前可见历史作为基线，不追补旧开仓。也可点击明确标注的演练按钮，经同一执行器提交 Demo 演练订单；它们不会被标成交易员真实信号。
7. 对照 Demo 交易所核对实际订单、成交数量、保护单、手续费、平仓及资金池变化。测试完成不代表实盘自动获准；真实执行保持关闭。

后续重新构建的 Windows 便携包对应入口为 `Open-Demo-Preview.cmd` 和 `Connect-Demo.cmd`，不需要自行安装 Python。旧已发布包不会因源码推送自动更新。

现有模拟手动仓位不会被自动接管。程序账本有持仓而会话重启时，会核对保护单并要求人工在 Demo 交易所检查处理，再开始新跟随。信号过期、源身份或时区改变、采集不新鲜、持仓数量改变、未知订单结果、保护单异常都会阻止继续开仓。

## 已实现的规则

- 策略预算复投仅使用账本初始资金和已核实的净成交损益及 USDT 资金费；其他余额、非 USDT 抵押物和浮盈不进入可复投预算。同一资金池同一时刻只开一个仓位。预算是软件记账，不是交易所资金隔离。
- 多空开仓均有不利价差上限，使用限价 IOC。实际部分成交按真实数量记账并设止损。撮合、最小名义价值、数量步长及最小最大量均按交易所规则检查。
- 平仓信号全平匹配合约、方向的程序仓位。单向模式使用 reduceOnly；双向模式明确 LONG/SHORT，不发送不适用的 reduceOnly。未验证任何真实账户模式适配。
- 保证金止损目标换算为价格距离，并按价格步长向更紧的方向取整；使用数量受限的 MARK_PRICE 条件止损。目标不保证实际损失，费用、资金费、跳空和滑点仍影响结果。
- 订单意图先落账本。丢失响应只按原客户订单编号查询，不盲目重发。成交记录不完整则保留待核对状态。旧止损取消结果持久记录，取消未确认会阻止继续。
- 非 USDT 费用不猜汇率；会停止要求核对。资金费按程序拥有仓位的区间归属并按流水去重。
- 达到已选择的累计亏损/回撤阈值，尝试平掉程序拥有的 Demo 仓位并停止。若平仓无法按交易所数量规则完成、网络失联或订单结果不明，需手动核对，不保证损失被严格封顶。
- 暂停新开仓仍处理平仓和保护；停止会话不主动平仓，已确认的交易所止损保留。停止或异常后不会自动重新启动下单。

## 数据与运行

公开源数据库以 SQLite `mode=ro` 打开。Demo 使用独立目录 `data/demo-v2`，与真实数据目录必须不同，包含自己的参数、账本和日志。Demo Key 仅保留本测试进程内存；关闭后台、退出 Windows 或重启后需重新输入同一组 Demo 密钥，不等于必须新建 API。真实账户的 Windows 加密记住功能不受影响。

`scripts/install_demo_workspace.ps1` 可为当前用户注册一个手动启动、无自动下单的后台任务，使预览与浏览器、终端或聊天会话独立。它不在登录时自动下单，也不自动恢复带密钥交易。停止后台可运行 `Stop-ScheduledTask -TaskName PoloCopyTrade-DemoWorkspace`，删除任务可用 `Unregister-ScheduledTask`。

源码测试、浏览器假网关演练和真实 Demo API 验单是不同层次。没有实际 Demo 密钥及交易所对账结果前，不标记为线上验单通过。

## English

The separate workspace uses Binance Futures Demo only, on localhost:8766. Production account monitoring remains read-only on localhost:8765. Open `open-demo-preview.cmd`, then enter separate Demo HMAC credentials locally using `connect-demo-v2.cmd`. The authenticated local pipe accepts credentials only, never orders. The browser never receives API secrets. Choose the cumulative loss basis, verify leverage on the Demo exchange, save the policy, and explicitly start. Historical openings are baselined, not replayed.

The journal tracks actual fills, USDT fees and owned-interval funding, uses stable order IDs to resolve uncertain outcomes, and preserves exchange-stop ownership and pending cancellations. Hedge and single-direction test paths are supported. Unowned/manual positions are blocked. A cumulative loss threshold attempts an owned Demo exit and halts. Exchange-side stops remain after stopping the session. Gaps, stale signals, incomplete accounting and unknown order outcomes require review.

Rehearsal controls use the same Demo engine and are clearly separate from public trader operations. The initial strategy allocation is bookkeeping, not exchange fund segregation. The Demo journal, policy and logs use a separate directory; its keys remain in session memory and no trading resumes automatically. Fixture/browser tests are not a substitute for actual Demo exchange order and fill validation. No production order capability is enabled by this workflow.

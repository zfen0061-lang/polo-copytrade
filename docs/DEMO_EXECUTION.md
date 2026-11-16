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

Rehearsal controls use the same Demo engine and are clearly separate from public trader operations. The initial strategy allocation is bookkeeping, not exchange fund segregation. The Demo journal, policy and logs use a separate directory. Keys are memory-only by default; the opt-in Windows-encrypted Demo connection below allows reconnecting without another prompt. No trading resumes automatically. Fixture/browser tests are not a substitute for actual Demo exchange order and fill validation. No production order capability is enabled by this workflow.

## 本机记住 Demo 连接与后台复测 / Remember Demo and verify in the background

1. 在本机运行 `remember-demo.cmd`，输入已有 Demo Key 和 Secret。此步骤只验证账户并用当前 Windows 用户的 DPAPI 加密保存连接，不下单。不要输入实盘密钥，不必重新创建 Demo API。
2. 独立密文 `data/demo-v2/demo-account.dpapi` 使用与实盘不同的文件、格式、加密上下文和环境标记；运行数据不会纳入 Git。重新启动 Demo 后台可恢复连接，但不会恢复自动买卖。
3. 打开 `http://127.0.0.1:8766`，确认虚拟资金说明后，点击“运行 Demo 止损检查”。此时不能同时启动跟随、修改策略或运行第二份复测。
4. 后台独立进程使用保存的 Demo 连接、20 USDT 虚拟额度和独立账本进行有时限复测。页面显示进度、实际止损成交、空仓和保护单清理结果；`timeout`、`blocked`、`error` 都不是通过。
5. 只有核对完结果、策略参数和新鲜的公开信号源后，才另行启动 Demo 跟随。后台复测本身不会自动启动跟随；只接收到平仓信号时也不会凭空创建仓位。

Run `remember-demo.cmd` once to verify and encrypt the existing Demo pair locally. This uses current-user Windows DPAPI with a separate Demo file and encryption context. The webpage never accepts credentials. After reconnection, the authenticated Demo UI can launch a bounded verification worker using `--saved`; no keys are placed in child arguments or environment variables, and real-account keys are never used. Verification and following are mutually exclusive. Restarting reconnects only: following still requires explicit start. A changed/revoked API key or unavailable original Windows user can require local reconnection.

## 扩展 Demo 合约范围 / Expand the approved Demo universe

在停止跟随、账户空仓且没有委托时，可明确运行 `python -m backend.demo_scope --expand`。程序读取 Demo 合约目录，只纳入交易中的 USDT 保证金永续、支持当前 LIMIT/IOC、MARKET 和 STOP_MARKET 方式的合约。COIN 归类为加密资产，EQUITY/HK_EQUITY 及有明确 TradFi/Pre-IPO 标记的盘前合约归类为股票，INDEX/COMMODITY 归类为传统资产；其他不明确的盘前类型不会默认按币交易。

扩展前备份账本，保留本金、已实现净盈亏、最高净值、历史成交和去重记录，原损失上限不重置。在明确扩展模式下，首次开仓前可以自动将 **Demo** 对应合约准备为批准的杠杆（本安装中加密 10 倍，股票/传统资产 3 倍），并读取确认；只有资金池空闲、无未归属仓位或订单、分类仍有效时才会准备。默认模式仍要求手动核对杠杆。不会改变实盘杠杆、账户模式或现有手动仓位。

这些合约是候选范围，共用一个资金池，同时最多一笔跟单仓位。扩展不意味着每种合约都已实际成交测试，也不保证市场开放、报价、最小数量等条件总能满足。新上市品种需要重新审核并更新目录快照；不追溯补开停机或启动前的历史仓位。

Explicit expansion is Demo-only and requires a stopped, flat, settled account with no open orders. It backs up the existing ledger and changes only the approved symbol scope and its fingerprint, retaining capital, losses and deduplication history. In expansion mode the first eligible entry may prepare and verify Demo leverage using the fixed policy; no production settings or position mode changes occur. Unknown classifications are excluded. The scope shares one capital pool and is a catalogue snapshot, not a claim that every contract has been exchange-tested.

公开采集短暂超过新鲜度阈值时，Demo 会暂挂信号处理，继续核对账户、资金风险和已有保护单；采集恢复后按原游标和开仓信号有效期继续检查。明确的用户平仓请求仍可处理。未解决订单、仓位不一致或交易所异常仍可能停止会话，不会自动盲目重下单。

Temporary public-source staleness holds signal processing while exchange protection and risk maintenance continue. Freshness recovery resumes from the same cursor with the same entry-age limit. Unknown orders, mismatched ownership and exchange failures still halt for review; this is not an automatic order replay or restart of execution after a process reboot.

## 正负 3% 开仓与平仓优先 / Symmetric entry band and exit priority

当前 Demo 的开仓门槛是 `abs(可成交报价 / 交易员成交价 - 1) <= 0.03`：开多使用卖一价，开空使用买一价。上下两边都检查；即使价格朝有利方向变化超过 3%，也按此规则跳过。下单仍使用 IOC 限价单约束不利成交价格。下单前报价检查不等于能保证最终每笔成交价都在绝对区间内：更优价格成交和快速行情变化仍可能发生。

公开操作的成交时间保留用于延迟统计；开仓处理时限从本机 `first_seen` 首次检测时间起算，仍为 60 秒。启动历史基线、稳定信号编号去重和资金检查保留。同批已经有后续同合约同方向平仓记录的开仓会记为 `superseded_by_close`，不追入已经结束的一轮交易。被暂挂的开仓保留游标，以免跨过尚未处理的信号；仍受检测后处理时限限制。

已记录、可验证的平仓操作会优先检查并尝试市价平掉对应的自有 Demo 仓位，不受 3% 开仓价差、开仓时效、入场杠杆核对或后续采集暂时失去新鲜度的限制。平空是买入减仓，不能把所有 SELL 都当平仓。没有匹配自有仓位时跳过，不会替用户关闭其他手动仓位。网络、交易所拒单、未解决订单或仓位不一致仍可能阻止完成，不能保证任何条件下都立即成交。

New public openings use executable ask/bid quotes and a symmetric absolute 3% band. Detection-based processing age replaces execution-age rejection, without replaying history. Recorded matching exits are processed first, including during a later source freshness gap; they use quantity-bounded market closes and bypass entry-only gates. Actual execution is still subject to exchange availability and ownership reconciliation. Subsequent opening decisions log their reference, executable quote, signed/absolute deviation and source delay.

## 后台恢复与校时 / Runtime recovery and signing clock

签名时间使用服务端时间锚点与单调计时，避免 Windows 自动校时改变请求时间；过慢的校时样本会被丢弃。只读 GET 遇到 `-1021` 时最多校时并重试一次，下单与撤单不会因此重发。公开采集在响应完成时立即核验正文；特定的浏览器正文失效错误会按退避机制重建采集器，保留进程内的观察游标。访问限制、限流、格式或身份异常仍会停止采集，不能保证任何网络条件下持续运行。

Signed timestamps use a server-time anchor and monotonic elapsed time; slow clock samples are rejected. Only a rejected signed GET receives one clock correction and retry. Submissions and cancellations are not replayed. Completed public responses are validated immediately; an expired browser-body error rebuilds the collector with backoff and preserves its in-process cursor. Access restrictions, rate limits and invalid source data remain blocked. Restart restores saved credentials, not automatic execution after a process reboot.

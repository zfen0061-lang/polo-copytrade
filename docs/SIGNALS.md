# Public signal observation / 公开信号追踪

The observer is locked to **熬鹰资本**, portfolio `5075281354358777856`.
It reads only the visible **最新操作记录** tab. It never submits paper or exchange orders,
uses no account credentials, and does not infer hidden positions, leverage or closing percentages.

观察器当前锁定熬鹰资本。仅读取网页公开操作：开多、开空、平多、平空、时间、成交均价和成交数量。
开仓操作可能属于加仓，公开成交数量不能证明平掉了总仓位的多少比例；逐笔杠杆没有公开时显示未知。

## Run / 运行

1. Start `connect-real-readonly.cmd` and enter the account credentials locally.
2. Verify the local read-only account connection in the dashboard.
3. With the target configured as `binance_public`, authorized, and source timezone verified as UTC,
   run `start-aoying-watch.cmd` (or `python -m backend.observe`).
4. The dashboard's public-signal card shows status, last successful poll, baseline count and new operations.
   Use **查看真实信号记录** to open the signal log. Pause/resume affects observation only.

当前已在本机启动的观察器可以与已连接账户的后台同时运行，无需重新输入密钥。
黑色账户窗口关闭、后台退出或后台会话更换时，观察器会停止。
重新启动账户后台后，需要再次启动观察器；不会自动恢复实盘交易。

## Timing and history / 时间与历史

The browser context is fixed to UTC. The same visible operation was checked in UTC and
Asia/Kuala_Lumpur contexts: the display shifted by eight hours while the operation body stayed identical.
Stored timestamps use `+00:00`; the dashboard renders times in the viewer's local timezone.

Each completed poll is followed by a 15-second wait. Navigation, page loading and Binance's own
publication delay add to detection time. This is not an instant trade feed or an exchange latency SLA.

首次启动及暂停后恢复时，当前可见历史只建立基线，不生成新操作通知或订单。
重复记录按来源编号去重。连续读取需要衔接到已知记录；发现历史缺口或格式变化时停止并报告。
暂时的页面加载故障会退避重试；访问限制不会被绕过。状态显示最近一次成功采集时间和错误。

## Separation / 执行隔离

Observation mode is independent of both the paper scheduler and account following. Its records have
`baseline` or `observed` status, no fabricated quote or slippage, and retain source filled quantity.
The paper scheduler skips observation-only traders; the new execution adapter rejects their account-follow starts.
Production read-only sessions also retain the separate server-side execution lock.

3% remains the user's configured adverse-entry deviation limit for later execution work. No price-cap order,
stop order, simulated fill or real fill is produced by this observer.

# Continuous observation and strategy drafts / 持续追踪与策略草案

## Power and session lifetime / 电源与会话

`keep-awake.cmd` (`python -m backend.awake`) holds a temporary Windows system idle-sleep request
only while the local read-only account server and signal observer are active and the computer is on AC.
It does not hold the display on. Pausing observation or unplugging AC releases the request; exiting also
clears it. The dashboard reports the guard heartbeat and status.

保持接电、网络连接和账户后台窗口运行。普通息屏或锁屏不会结束后台进程。
此功能只防止自动空闲睡眠，不能阻止手动睡眠、合盖动作、断电、关机或 Windows 重启。
它不修改电源计划、系统更新策略，也不在磁盘保存交易密钥。

After restart, credentials must be entered locally again. The observer and awake guard must also be
started again. There is no automatic recovery of live trading. Monitor **last successful poll** and the
guard status, rather than relying only on the page's render clock.

常驻服务器、进程监控、受限的凭据存储和固定出口 IP 可以作为之后的部署工作；
当前本机版本不保证断电、重启或网络故障期间持续在线。

Microsoft reference:
https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate

## Allocated-pool compounding draft / 独立资金池复投草案

The draft records a user-selected initial allocation. After a settled trade, verified net realized P&L
belongs to that pool. Unrelated account funds and unrealized profits are excluded. Occupied margin and
fee reserves must be deducted, and exchange available balance remains an upper bound.

For example, an allocated pool of 60 may grow to 120; the next eligible entry may use the available
120 minus required reserves, instead of taking half again. Matching close signals request a full close
of the corresponding bot-owned symbol and direction. Existing manual or unrelated positions are not
owned by this strategy.

This is a **draft and arithmetic preview**, not a finished compounding execution engine. Stop distance,
loss limit, equity leverage rules, ownership of existing positions and validated P&L/fee/funding
reconciliation are still required. The live manager rejects this draft instead of silently running the
older fixed-order-size strategy. Saving the draft does not transfer funds or enable trading.

# 持续监测 / Continuous monitoring

源码版本：双击 `install-continuous-monitor.cmd`，为当前 Windows 用户安装登录启动任务并立即启动。以后双击 `open-continuous-monitor.cmd` 打开页面。需要先运行 `setup.cmd`。

For the source checkout, run `install-continuous-monitor.cmd` once to register the current user's login task. Open the dashboard with `open-continuous-monitor.cmd`. Run `setup.cmd` first if necessary.

- 守护器管理只读后台、公开信号采集和接电防自动睡眠进程；进程退出后按退避时间重启。后台连续无响应也会重启。网页关闭不影响后台采集。
- 账户读取由后台约每 10 秒刷新；错误时退避至最多 60 秒。公开采集每轮完成后等待 15 秒，平台发布及网页加载另有延迟，不代表实时成交推送。
- 首次运行及采集进程重建时，当前可见历史仅作为基线；断线期间不能保证补齐所有操作。数据缺口、权限拒绝或解析异常需要人工检查，不会据此猜测交易信号。
- 采集会等待指定交易员详情及该交易员的操作请求返回成功，防止页面初始化阶段的空编号、空白记录误报。需要人工检查的故障会显示“重新检查采集”按钮。
- 本模式不会下单。已有持仓、杠杆及币安账户模式均不修改。
- 账户密钥只保留在守护器及其账户子进程内存。双击 `reconnect-readonly-account.cmd` 本机隐藏输入。后台子进程重启可复用内存密钥；守护器、系统重启或注销后需要重新输入。不会从掩码、聊天或剪贴板恢复密钥。
- 登录任务只在当前用户登录时启动；不保证关机、断网、合盖或手动睡眠期间运行。防自动睡眠仅在接电且采集运行时生效，允许息屏。
- v0.3.0-preview 下载包不包含此新增守护功能；以上入口针对当前源码版本。

The supervisor restarts failed or unresponsive read-only workers. Account reads run independently of the browser. Collection waits 15 seconds after each completed poll and is subject to source publication delays. Rebuilt collectors baseline visible history rather than replaying historical operations. Gaps and access or parsing failures require review.

This mode never places orders. Keys stay in process memory, survive account-worker restarts, and must be entered again after supervisor or system restart. The login task requires an interactive user login. Power loss, manual sleep, lid close and network loss interrupt monitoring. The existing v0.3.0-preview binary does not include these source changes.

卸载登录任务 / Remove the login task:

```powershell
Stop-ScheduledTask -TaskName PoloCopyTrade-ReadOnlyMonitor
Unregister-ScheduledTask -TaskName PoloCopyTrade-ReadOnlyMonitor -Confirm:$false
```

运行状态为 `http://127.0.0.1:8765/api/runtime/state`，账户快照时间与采集成功时间分别展示；打开网页或页面时钟变化不代表采集成功。

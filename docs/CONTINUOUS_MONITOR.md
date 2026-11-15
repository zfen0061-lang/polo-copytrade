# 持续监测 / Continuous monitoring

源码版本：双击 `install-continuous-monitor.cmd`，为当前 Windows 用户安装登录启动任务并立即启动。以后双击 `open-continuous-monitor.cmd` 打开页面。需要先运行 `setup.cmd`。

For the source checkout, run `install-continuous-monitor.cmd` once to register the current user's login task. Open the dashboard with `open-continuous-monitor.cmd`. Run `setup.cmd` first if necessary.

- 守护器管理只读后台、公开信号采集和接电防自动睡眠进程；进程退出后按退避时间重启。后台连续无响应也会重启。网页关闭不影响后台采集。
- 账户读取由后台约每 10 秒刷新；错误时退避至最多 60 秒。公开采集每轮完成后等待 15 秒，平台发布及网页加载另有延迟，不代表实时成交推送。
- 首次运行及采集进程重建时，当前可见历史仅作为基线；断线期间不能保证补齐所有操作。数据缺口、权限拒绝或解析异常需要人工检查，不会据此猜测交易信号。
- 采集会等待指定交易员详情及该交易员的操作请求返回成功，防止页面初始化阶段的空编号、空白记录误报。需要人工检查的故障会显示“重新检查采集”按钮。
- 本模式不会下单。已有持仓、杠杆及币安账户模式均不修改。
- 可选“记住当前连接”：在当前账户进程内使用 Windows 当前用户 DPAPI 加密保存，明文不经过网页或聊天。后台重启及同一 Windows 用户重新登录后可自动恢复账户读取，不会自动开启下单。密文放在忽略提交的 `data/account-readonly.dpapi`。
- 已连接的旧后台可运行 `remember-current-account.cmd` 升级保存，无需重输；其他情况使用 `reconnect-readonly-account.cmd` 在本机隐藏输入并验证、加密保存。新后台页面也有“记住当前连接”和“不再记住连接”按钮。忘记保存仅删除密文，本次连接继续。
- 登录任务只在当前用户登录时启动；不保证关机、断网、合盖或手动睡眠期间运行。接电且持续监测后台活跃时防自动睡眠，允许息屏；采集暂时失败等待恢复时仍保持。关闭网页不会停止后台，使用“停止后台”按钮明确退出。
- 若 Windows 用户变更、系统重装导致密文无法解锁，或 API 被撤销、权限及可信 IP 改变，仍需重新连接。不要把遮罩圆点当作 Secret；保留原始 Secret 时不需要反复创建新 API。
- v0.3.0-preview 下载包不包含此新增守护功能；以上入口针对当前源码版本。

The supervisor restarts failed or unresponsive read-only workers. Account reads run independently of the browser. Collection waits 15 seconds after each completed poll and is subject to source publication delays. Rebuilt collectors baseline visible history rather than replaying historical operations. Gaps and access or parsing failures require review.

This mode never places orders. Optional Remember connection encrypts the account pair inside the account process using Windows current-user DPAPI. It supports automatic read-only reconnection after supervisor restart or login without sending credentials through HTTP. Existing sessions can use remember-current-account.cmd; the local reconnect launcher verifies and encrypts new credentials. Forget saved connection removes ciphertext without closing the current session. Lost Windows protection context, revoked keys or changed account/IP permissions require local reconnection.

The login task requires an interactive user login. AC idle-sleep prevention follows the active background supervisor, including source recovery periods; display off is allowed. Closing the web page leaves the monitor running; Stop background monitor explicitly exits. Power loss, manual sleep, lid close and network loss interrupt monitoring. The existing v0.3.0-preview binary does not include these source changes.

卸载登录任务 / Remove the login task:

```powershell
Stop-ScheduledTask -TaskName PoloCopyTrade-ReadOnlyMonitor
Unregister-ScheduledTask -TaskName PoloCopyTrade-ReadOnlyMonitor -Confirm:$false
```

运行状态为 `http://127.0.0.1:8765/api/runtime/state`，账户快照时间与采集成功时间分别展示；打开网页或页面时钟变化不代表采集成功。

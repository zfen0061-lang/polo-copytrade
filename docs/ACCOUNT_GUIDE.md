# 账户接入 / Account setup

## 1. 更新 / Update

旧终端 Ctrl+C 停止服务，备份 data/。新版解压到独立文件夹，不覆盖或删除旧数据。若正在用本次编辑的项目文件夹，只需重启。不要删除实盘账本来绕过核对；不要多机器运行同一账户。

Stop the old server, back up data/, unpack separately and keep account ledgers. One account must have one owning process.

## 2. 安装 / Install

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-collector.txt
.venv\Scripts\python.exe -m playwright install chromium
~~~

已有可用虚拟环境可跳过创建。Only public/account collection needs these dependencies; the synthetic demo does not.

## 3. 密钥 / Credentials

双击 connect-account.cmd，或：

~~~powershell
.venv\Scripts\python.exe -m backend.connect
~~~

选1正式账户，选2合约测试网（默认2）。密钥不可混用。隐藏输入不显示字符是正常的。进程退出后重启需重新输入。

Use separate production/testnet keys. Credentials remain in the process environment, not files.

在币安创建专用 API Key，按账户可用选项仅启用必要读取/合约交易权限，关闭提现权限并限制运行机器出口IP。所在地区和账户需具备产品/API权限。不要发到聊天、网页表单或GitHub。

Create a dedicated key with necessary read/futures access, no withdrawal permission and allowed source IPs. Regional/account eligibility applies. Never share keys in chat or source control.

## 4. 读取 / Connect read-only

打开 [本地工作台](http://127.0.0.1:8765)，“连接并读取账户”。检查 Production/Testnet 标签、实际余额与仓位，此步骤不下单。报错检查网络、API权限、IP、电脑时间和所选环境。

Connect and verify actual account data before starting. Do not bypass failed account checks.

## 5. 交易员 / Trader

在交易员页面添加/编辑公开数据源，填写带单链接，核实允许自动读取及页面时间时区。熬鹰参考链接：

https://www.binance.com/zh-CN/copy-trading/lead-details/5075281354358777856

名称不等于身份验证。先关闭此人的模拟采集，再在账户工作台选择他。首次采集仅建立历史基线，不补开旧单。公开采集不登录或绕过验证码。

Add a public source with verified access and timezone. Pause its paper collector. First observation is a baseline, not an order backlog.

## 6. 参数 / Parameters

先在币安手动设置单向、单资产、逐仓及选定杠杆。程序不代改。专用账户不要混用手动交易、其他机器人或遗留挂单。

| 参数 / Field | 含义 / Meaning |
|---|---|
| 总保证金预算 / Budget | 分配上限，不是独立钱包；仍受实际余额限制 |
| 每笔保证金 / Entry margin | 乘杠杆得到目标名义金额，不复制源金额 |
| 杠杆 / Leverage | 与币安每个允许合约配置一致 |
| 开仓价差 / Deviation | 默认3%，源参考价的不利偏离上限，多空相同 |
| 价格止损 / Price stop | 相对本账户均价的价格变化，不是保证金回报率 |
| 每次平仓比例 / Close fraction | 每条平仓信号减少本程序剩余仓位的比例 |
| 会话亏损预算 / Loss budget | 相对空仓启动权益，含手续费、资金费和转账影响 |
| 信号有效期 / Signal age | 过期新开仓跳过；迟到平仓停止核对 |
| 允许合约 / Symbols | 明确的USDT永续合约清单 |
| 采集间隔 / Poll | 与源发布时间、网络共同决定延迟 |
| 源时区 / Offset | 已核实的页面源时间相对UTC的分钟偏移 |

金额、杠杆等不使用模拟默认值，需要你主动填。建议先用测试网验证；正式验证金额自行确定。启动请求通过不表示采集或下单成功，继续观察状态、错误和交易所结果。

Fill explicit parameters. Validate testnet first. A scheduled session is not a successful order.

## 7. 持续运行 / Runtime

- 后端、网络和电脑必须运行且不休眠；网页可关。
- 暂停新增仍观察平仓；停止跟随停止观察，不自动平掉真实仓位。
- 已确认交易所止损保留，但不保证成交价格。
- 切换前停止、核对并处理旧仓位和挂单。首版一个账户只跟一位。
- 重启重新输入密钥、连接、填参数；旧仓位不自动恢复跟随。
- 运行中不要手动调仓、转账或同时使用其他机器人。
- 全天运行需另行部署常在线服务、进程守护、访问控制、密钥管理和告警。当前未部署云服务或手机推送。
- 更新保留实盘SQLite账本，不上传运行数据或密钥到GitHub。

Keep the backend online and machine awake. Stop does not liquidate; confirmed exchange stops remain. Handle existing exposure before switching/restarting. Durable hosting and monitoring are separate deployment work.

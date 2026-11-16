# Polo CopyTrade · v0.3.0

源码执行入口：[实盘自动跟随](docs/REAL_EXECUTION.md)（8767）与[合约 Demo](docs/DEMO_EXECUTION.md)（8766）。两者共用策略与账务核心，端点、账本和启动授权分开。实盘页面打开时未启用交易；由用户核对并明确启动后，后续信号自动开平仓，无需逐笔确认。开发期间没有实盘下单。

[持续只读监测](docs/CONTINUOUS_MONITOR.md) 继续使用 8765，提供 Windows 登录启动、后台恢复和账户刷新。旧版 v0.3.0-preview 下载包不包含这些源码更新，本次没有发布新版 EXE。交易所实测结果与限制见[验证记录](docs/DEMO_VERIFICATION.md)。

中文 · [English](README.md)

观察币安公开带单操作、测试自定义跟随规则，并可主动连接个人 U 本位永续合约账户的本地前后端应用。深蓝底、白色 **P** 与青绿色细节对应 Polo，颜色不代表涨跌。

**账户工作台与模拟实验室独立；正式账户主动启动后可以提交真实订单。** 打开网页不会自动连接或开仓。本版通过本地测试，尚未完成交易所在线、公开源和自动化浏览器端到端验证。

| 入口 | 数据与执行 |
|---|---|
| 实盘自动跟随（8767） | 用户明确启动后按保存规则自动下单，独立实盘账本 |
| Demo 自动跟随（8766） | 测试网 API、独立测试密钥与账本 |
| 模拟实验室 | 虚构行情或公开观察数据，本地模拟成交 |

账户未连接显示空状态。账户只读与采集使用 8765，实盘执行使用 8767；要求单向持仓、单资产 USDT、目标合约逐仓且关闭自动追加保证金，使用 USDT 手续费。已有手动仓位或委托会阻止实盘启动，程序不会接管。

## 给其他人使用：Windows 运行包

[下载 Windows 64位预览版](https://github.com/zfen0061-lang/polo-copytrade/releases/download/v0.3.0-preview/PoloCopyTrade-Windows-x64.zip) · [发布页面](https://github.com/zfen0061-lang/polo-copytrade/releases/tag/v0.3.0-preview)

完整解压运行包后双击 PoloCopyTrade.exe，即会启动本地服务并打开浏览器。无需分别安装 Python、采集库或 Chromium。保留 _internal 等所有子目录。预发布版本已通过源码、内置浏览器和本地 HTTP 启动检查；币安在线交易接口仍需验证。源码 ZIP 仍需开发环境。

运行包默认打开未连接的账户工作台，密钥及交易参数由每个人自己在本机配置，不自动交易。持久数据保存在用户本地目录，不写进可执行文件或随源码共享。

[便携版使用说明](docs/PORTABLE.md) · [GitHub 构建和发布步骤](docs/PUBLISH.md)

## 打开和更新

需要 Python 3.10+。只看网页和合成模拟不需第三方包。

~~~powershell
python -m backend.server
~~~

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)，或双击 `start.cmd`。Ctrl+C 关闭服务。VS Code 用“文件 → 打开文件夹”打开本项目，或打开 `copytrade-studio.code-workspace`。

更新后必须停止旧服务、重启后端再刷新网页。已有运行数据先备份，不删除实盘账本。

## 接账户

详见 [中英文账户操作指南](docs/ACCOUNT_GUIDE.md)。公开采集和账户跟随需安装依赖。Windows 双击 setup.cmd 自动创建项目虚拟环境、安装 Playwright 和 Chromium，完成后双击 check.cmd 查看缺项。两者都不读取密钥、不连接账户、不下单。也可手动执行：

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-collector.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m backend.connect
~~~

或双击 `connect-account.cmd`。本地终端选择正式账户/测试网，隐藏输入 API Key / Secret。密钥只在服务进程环境中，重启重新输入，不写入源码，不通过网页提交。不要发给聊天或上传 GitHub。

“连接并读取账户”只查询余额、持仓和配置。跟随另需添加公开源交易员、核实读取权限与源时区、暂停该人的模拟采集，然后在账户工作台选择他、自己填参数并主动启动。

## 规则

- 多空默认最多 **3% 不利开仓价差**：参考100，多单最高103，空单最低97。有利价格允许。这是相对源参考价的偏离，与当前盘口成交滑点不同。
- 开仓 IOC 限价，可部分成交或不成交；下单前保存意图，不确定先查单，不盲目重发。
- 平仓信号按自定比例减少本程序剩余仓位，使用只减仓。公开操作不能推断隐藏杠杆或原交易员减仓比例；迟到平仓停止跟随要求核对。
- 成交后提交并确认交易所 STOP_MARKET 全平保护，以标记价格触发。安装失败尝试只减仓退出并停止；断网、跳空或强平仍可能影响结果，止损不保证成交价。
- 模拟止损依赖后端运行；交易所已确认止损在本程序停止后仍存在。
- 每次主动启动建立新观察基线，不补做历史开仓。旧仓位需核对处理后再开始。
- 会话亏损预算对比空仓启动权益，含手续费、资金费和转账影响。不要混用手动交易或其他机器人。

## 持续运行

需要后端、网络和电脑一直运行且不休眠；网页可关。源发布时间、轮询、网络和接口耗时共同决定延迟，无法保证立即发现。

“暂停新增”继续观察有效平仓；“停止跟随”停止观察，不自动平掉实际仓位或撤销已确认交易所保护。停机、切换前到币安核对。

本服务只供本机单用户使用，含 Host、Origin 和 CSRF 检查，不直接暴露公网。GitHub 保存代码，GitHub Pages 不能运行后端。全天运行需另部署常在线服务、密钥管理、访问控制和监控。

~~~powershell
python -m unittest discover -s tests
node --check frontend/app.js
node --check frontend/live-ui.js
~~~

[验证记录](docs/VALIDATION.md) · [接口](docs/API.md) · [后续上线工作](docs/PRODUCTION.md)

开发本版没有连接你的账户，也没有向币安提交真实订单。

## 桌面 P 图标

已有本地项目的用户可以双击 create-desktop-shortcut.cmd。它会安装已发布的运行版到个人程序目录并创建桌面 P 图标。首次需下载运行包，以后不再依赖源码目录或 Python。详见 [桌面图标说明](docs/DESKTOP.md)。
## 真实公开信号追踪

源码版本新增熬鹰资本（`5075281354358777856`）的仅观察模式：记录网页公开操作，
不生成模拟订单或实盘订单。运行方式、时间处理和限制见[信号追踪说明](docs/SIGNALS.md)。
已发布的旧版便携预览包尚未包含本次源码更新。

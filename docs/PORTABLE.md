# Polo CopyTrade · Windows portable preview

中文 / English

此文描述构建成功后的 Windows 运行包。源码 ZIP 不包含 EXE；只有通过构建和检查的运行包才提供免安装体验。在线币安接口验证与打包验证分别进行。

## 使用 / Use

1. 从 GitHub Releases 下载 PoloCopyTrade-Windows-x64.zip。不要把 GitHub 的 Source code.zip 当作运行包。
2. 完整解压整个文件夹，保留 _internal 和所有子目录；不要直接在压缩包里运行，也不要只移动 EXE。
3. 双击 PoloCopyTrade.exe，会启动本地服务并打开系统浏览器。无需安装 Python、pip 或 Playwright，也无需管理员权限。
4. 账户最初未连接、跟随未启动。只体验模拟实验室无需密钥。
5. 接账户时先关掉正在运行的服务，在终端按 Ctrl+C；双击 Connect-Account.cmd，在本机隐藏输入密钥，选测试网或正式账户。重新启动后在页面读取并核对账户，再填写自己的参数并主动启动。
6. 不要关闭服务终端或让电脑休眠；网页可以关。停止服务不会自动平掉账户仓位，已确认交易所保护单仍保留。

Download the Windows x64 release, extract the **entire folder**, and double-click PoloCopyTrade.exe. Python, collector dependencies and Chromium are bundled. The system browser displays the local interface. Startup does not connect an account or trade.

For account setup, stop the first server and run Connect-Account.cmd. Enter keys locally, inspect the account, configure your own rules and explicitly start. Keep the server and network running. Closing the webpage does not stop the server; closing its terminal does.

## 数据与更新 / Data and upgrades

运行包的账本保存在当前 Windows 用户的 %LOCALAPPDATA%/PoloCopyTrade，独立于下载文件夹。更新程序不会自动删除该目录。每个人使用自己的账本和密钥，密钥只在进程内，不随运行包分发。

已有源码用户不要丢弃原项目 data/。切换运行包前停止旧进程并核对仓位；需要继续使用原账本时，从终端传入 --data 原账本完整路径。不要用空账本掩盖旧持仓，运行包也不会自动接续旧仓位跟随。

Runtime ledgers live under the current user's LocalAppData/PoloCopyTrade. Keys remain in process memory. Source-version users must retain their existing data and reconcile exposure before switching. --data can select an existing ledger; do not run two processes on the same account.

## 范围 / Scope

- 当前便携目标为 Windows x64。macOS、Linux 暂用源码方式。
- 运行包较大，因为附带采集浏览器；一次下载后无需分别下载这些组件。
- 未购买或配置代码签名证书。不宣称已签名；不要要求用户关闭系统防护。
- 运行包是预览版，不等于已完成在线交易验证。账户、地区、访问权限和公开数据可用性仍需分别确认。
- 本地用户数据不会提交 GitHub。它是开源本地应用，不是托管所有人 API 密钥的公共交易网站。
- 查看或运行源码需自行准备开发环境，详见仓库 README。

The portable build is Windows x64 only and is not currently code-signed. Packaging does not certify live Binance execution. Eligibility, source access and online verification remain separate. No cloud trading service or phone notification service is provisioned.

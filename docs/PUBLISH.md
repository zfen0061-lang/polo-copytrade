# GitHub distribution / GitHub 发布

## 给用户的体验 / End-user flow

目标：GitHub Releases 下载一次 → 完整解压 → 双击 PoloCopyTrade.exe → 页面添加交易员 → 自己配置账户和交易规则。运行包内含 Python、Playwright 和 Chromium。源码 ZIP 仍面向开发者。

Target: download the release once, extract it, launch the EXE and configure your own account/rules. No separate Python installation is required for a successfully built portable release.

## 仓库与首次推送 / Repository and first push

项目仓库：https://github.com/zfen0061-lang/polo-copytrade 。不要上传密钥、运行数据库或整个虚拟环境。贡献者可克隆仓库后修改代码、运行测试并提交更改。

Do not publish local runtime data or credentials. This project includes an MIT license for its code; bundled third-party components retain their own licenses.

## 自动打包 / Automated build

.github/workflows/windows-release.yml 提供：

1. 推送影响运行程序或构建流程的代码到 main，或 GitHub Actions → Build Windows app → Run workflow，使用 Windows x64 / Python 3.13 构建。
2. 安装构建依赖，运行源码测试。
3. 将 Chromium 安装到 Playwright 包内部，与 Python 和前端一起打包。
4. 启动构建出的 EXE，验证本地浏览器页面、HTTP接口及账户默认未连接。
5. 检查运行包不带开发者账本或密钥，生成 ZIP 和 SHA256 校验文件。
6. 成功后在工作流产物 polo-windows 中下载测试包；这不是公开 Releases 下载入口。
7. 推送 v 开头的版本标签会执行同样构建，并创建附带 ZIP 的 **草稿 Release**；维护者检查后发布，普通用户即可从 Releases 下载。

The workflow builds and checks the Windows package. Manual runs upload a workflow artifact. Version tags additionally prepare a draft release. Publish that reviewed draft to provide a public release download. No user's Binance credentials are needed by CI.

## 本机打包 / Local build

在 Windows x64 有 Python 和网络的电脑上双击 build-windows.cmd。它安装构建依赖、构建、测试并生成 dist/PoloCopyTrade-Windows-x64.zip。构建者需要开发依赖，使用运行包的人不需要。

Build on Windows using build-windows.cmd. The build includes only explicit app assets, installed runtime dependencies and public docs. Developer data/ and .env files are excluded. Do not upload the developer virtual environment as a release.

## 发布前检查 / Before public distribution

- 构建必须实际成功，不能把已写好的流程当作已有 EXE。
- 在干净 Windows x64 机器验证完整解压、双击启动和账户只读连接；当前环境的源码测试不替代该检查。
- 继续完成测试网与实际公开源联调；分别验证部分成交、断网、重启、止损和异常恢复。
- 真实交易仍由每个用户明确配置；不提供默认资金和杠杆承诺，不自动跟随历史仓位。
- 公共网页托管不等于后台交易服务。仅发布前端不能让 Python 后端持续运行。
- 若将来提供浏览器即用的云服务，需要单独设计账户隔离、身份验证、密钥管理和持续运行服务，本版未实现。

Do not announce an EXE before the build and tests pass. Verify a clean target machine and online account/source behavior separately. A hosted multi-user trading service requires additional architecture and is not provided by GitHub source hosting.

## 本机推送备用入口 / Local push fallback

若连接返回403写入拒绝，维护者可在已有本地Git项目中双击 publish-github.cmd，按Git的浏览器提示登录账号。脚本只推送已提交的main，不自动暂存文件，不强制推送，不上传忽略的运行数据。源码ZIP不含.git，不能在新解压的源码目录直接使用此脚本。

If integration writes are denied, run publish-github.cmd from this existing Git working tree and complete Git Credential Manager sign-in locally. It pushes committed main only, without staging files or force-pushing. A source ZIP does not contain Git history.

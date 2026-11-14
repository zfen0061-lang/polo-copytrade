# Validation / 验证记录

v0.2.1: **44 local automated tests passed**: 21 core, 6 in-memory HTTP, 17 account-engine. Both JavaScript modules pass syntax checking.

Core covers long/short 3% boundaries, favorable prices, duplicate events/restarts, stale entries/late closes, independent paper ledgers, budgets, pauses, stops, timestamps and URL restrictions.

HTTP tests execute actual request parsing through in-memory byte streams: static logo/module routes, disconnected account state, browser credential rejection, Host/CSRF/Origin checks and paper/account separation.

Account tests use a fake exchange: read-only connect, rejection of demo arming/incomplete params, confirmed stops, partial/full closes, failed protection with full/partial exit attempts, uncertain order recovery, triggered/missing stops, manual quantity/flat changes, flat-only config changes and no submission after stopping during source retrieval. That scenario also exposed a Windows SQLite status-read handle leak; connections now close explicitly.

**No actual Binance credentials, real orders or source-to-exchange end-to-end runs were used.** Local passing tests do not establish live integration or financial results.

本版44项本地测试使用虚拟客户端，没有连接你的账户，没有向币安提交真实订单；实际密钥、公开采集、测试网和正式接口还需在线验证。

## Environment limits / 环境限制

The execution environment rejected local HTTP TCP clients with Windows socket error 10013. In-memory tests do not replace real-port checks. No automated browser rendering or interactive verification was completed. The VS Code CLI returned a permission error; no editor window was verified open.

用户已能访问旧版网页，不等于新版UI或交易接口已完成端到端验证。模拟成交省略深度、资金费和强平；真实延迟及故障恢复仍未实测。

## Setup recovery checkpoint / 环境续接检查

The project virtual environment was created. Local doctor reports dashboard ready but public collection unavailable: Playwright is not installed. The current package source returned no matching distribution; no collector was installed. setup.cmd and check.cmd allow installation and diagnosis from the user terminal. Missing dependencies are reported before an account-follow session starts. Online exchange and browser validation remain pending.

A subprocess smoke check started the backend on port 8766 with a temporary database and no scheduler. Startup reported account execution OFF and the process stayed running until deliberately stopped. This verifies process startup, not a TCP client, browser rendering or online account access.

## v0.3 distribution work

53 local source tests pass (44 existing tests plus 9 packaging/runtime-path tests). This does not count a Windows EXE build: no EXE has been produced or run, and the GitHub workflow has not been executed.

Portable entry point, persistent per-user data paths, local file-only dependency checking and GitHub Windows build/draft-release workflow are implemented. The collector file check no longer starts a Playwright driver, which could hang under execution restrictions. Windows packaging and online exchange validation have not run. Source tests include package-data separation, exact browser revisions, required headless shell, launcher behavior and runtime-data exclusion from archives.

User installation contains the matching Playwright, Greenlet and Chromium/headless-shell files. The execution sandbox uses a different default cache directory; checking the actual user browser cache succeeds. This is a dependency-file check, not a browser-launch or trading check.

## First Windows CI result / 首次 Windows 构建结果

GitHub Actions run 43638508070 completed successfully for commit 0dc011e1112ff731d0a737830e16e89ccf2f4a6d. Both the independent source test workflow and the Windows build succeeded. The built EXE launched bundled Chromium on local HTML, served the local frontend/API and started disconnected with no account following. The clean runtime ZIP and checksum were uploaded as polo-windows (artifact 14130482921). No Binance account or external trading request was used. No public Release has been published yet.

Run: https://github.com/zfen0061-lang/polo-copytrade/actions/runs/43638508070

## Public preview / 公开预览版

v0.3.0-preview is published with draft=false and prerelease=true, with the Windows runtime ZIP and SHA256 file. Preview build run 43639131046 and draft-release job succeeded. Source start.cmd now uses polo.py so a successful launch opens the local webpage automatically. Online Binance source/account/execution validation remains pending.

## Desktop installer checks

58 source tests pass. Added release-download checksum and archive extraction checks, including traversal and symlink rejection. The Windows icon was converted to ICO and read back at 256x256. A test shortcut was created only inside the writable workspace, and launcher PowerShell syntax was checked. The actual Desktop/user program directory installation must be run by the user; no desktop shortcut was created there by the agent.

## Restored live local UI / 本机界面恢复

The browser was connecting to a legacy CopyTradeStudio/0.1 backend while reading newer frontend files. The legacy service returned 404 for live-ui.js, polo-logo.png and api/live/state. The verified legacy Python backend was stopped and replaced with PoloCopyTrade/0.3.0. All three resources then returned 200. A real headless browser loaded the logo, switched navigation, opened/closed the trader dialog and opened/closed account help, with no JavaScript errors or failed requests. No account connection button was clicked and no order request was sent. Current account state remains unconfigured, disconnected and not following.

Added a visible startup notice until frontend handlers are installed and added navigation/dialog checks to the packaged browser smoke test. No logo file modification was needed.

## Read-only production launcher

60 local source tests pass, including production environment selection and a server-side execution lock for read-only account sessions. The read-only guard rejects account-follow starts before scheduling any worker. Fake credentials were used in tests; no real credentials were collected by the agent.

## Public Aoying signal observation

The user entered production credentials locally and the account read-only connection returned an account snapshot.
Account execution remains disabled and account following remains inactive. Credentials were not read by the agent.

The actual visible Aoying portfolio (`5075281354358777856`) was opened with a clean headless browser.
Ten public operations were parsed, covering OPEN_LONG, OPEN_SHORT and CLOSE_SHORT, with filled quantities.
The same operation body was checked in UTC and Asia/Kuala_Lumpur browser contexts; its displayed timestamp
shifted eight hours. Observation now explicitly uses UTC. A timestamp split across DOM elements and early
SSR tab clicks were handled in the public collector.

A separate observer was started beside the connected account server, preserving its in-memory credentials.
At least four successful live polls retained ten unique historical baseline records, zero new observations,
zero paper orders and zero account orders. This verifies repeated page reading and baseline de-duplication;
the arrival of a new live operation has not yet been witnessed. New-operation, pause/resume and history-gap
behavior are covered with synthetic collector fixtures.

69 source tests pass. Browser checks confirmed the locked observer card, ten signal rows, source quantities,
disabled account execution controls and no JavaScript errors or mutating requests. This is a source update;
the previously published portable release has not been rebuilt with the observer.
## Idle account snapshot refresh

Fixed a stale-data issue: the dashboard previously polled the cached account state, while idle/read-only
sessions fetched a fresh Binance snapshot only after a manual click. The existing refresh endpoint is
now called automatically from the open dashboard about every 10 seconds without blocking signal rendering.
Single-flight requests prevent overlap, failures back off and keep the previous successful snapshot, and
the visible status distinguishes refreshing, failed refresh and last successful account update.

Three Node tests cover interval scheduling, concurrent manual/automatic requests and failure recovery.
Real-browser verification observes automatic read-only refresh responses and distinct snapshot timestamps
without manual clicks. No account-follow or order request is involved. The connected backend and public
observer do not need to restart, preserving the locally entered credentials.
## Allocated-pool draft and Windows idle-sleep guard

73 Python tests and 3 Node refresh tests pass. The additional tests cover allocated-pool arithmetic,
losses and occupied funds, draft execution blocking, per-symbol/side full-close preference, and temporary
AC-only sleep-request activation/release. Arithmetic preview is not certified compounding execution.

The running Windows host accepted the AC system-awake request. The guard heartbeat reports active,
on AC, display-off allowed and restart prevention false. No power-plan, update-policy, startup task,
credential persistence or account permissions were modified. A draft was saved locally without a
transfer or order. The connected read-only account and independent public observer remain running.
## Public-tab hydration recovery

After 103 successful observation polls, selecting the public operation tab timed out repeatedly.
A clean-page check confirmed the public records were still available after client rendering settled.
The collector now waits for the load event and a bounded two-second client-render settling period
before tab selection. The failed observation process alone was replaced; the connected account server
and AC awake guard stayed running. Two successful recovery polls recorded eleven cumulative baseline
operations, zero new-operation executions and no orders. The operation first visible after the outage
was treated as reconnection history, not replayed as a trade. Restart baseline-count preservation is tested.
This recovery does not establish an uptime guarantee for the public website.

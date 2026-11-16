# Demo execution verification / 模拟执行验证

Production execution remains disabled. This procedure does not establish production readiness.
实盘执行保持关闭；这些测试不能证明程序已经适合实盘。

## Results recorded on 2026-11-16 (Asia/Shanghai)

- Demo BTCUSDT configuration was verified at 10x.
- Four Demo orders settled: open long, close long, open short, close short.
- Protective stop placement was verified for both directions.
- The first short-stop cancellation confirmation failed; recovery subsequently cleared the known stop. The original underlying exception was masked, so its exact cause remains unconfirmed.
- The exchange and strategy journal agreed on net virtual cash change: -1.14763794 USDT. Exchange balance after the roundtrip was 4998.85236206 USDT; strategy allocation was 58.85236206 USDT. No position or unresolved intent remained.
- 154 Python tests passed after adding duplicate/restart/network and cancellation confirmation coverage. The process-crash test uses a fake broker in a real child process; it is not a crash of the live Demo server.

## Follow-up changes / 后续修正

Cancellation is submitted once, followed by at most three status queries. Delayed cancellation status and lost cancellation replies are covered by tests. An unresolved stop remains recorded and halts the session. An already-flat position now reports a cleanup problem without claiming that an emergency exit was required. Safe error details are retained.

撤单只提交一次，再有限次查询状态；无法确认时保留记录并停止。已平仓后的清理错误会单独报告。上述修正针对已发现的处理缺口，不能据此断定首次异常的具体原因。

## Bounded stop-fill check / 有时限的止损实测

Run `verify-demo-stop.cmd` locally and enter a **Demo** API pair in the hidden terminal prompt. The updated Demo workspace must already be running, with following stopped and the shared execution lease available. The test refuses existing positions or BTC orders, and requires Demo BTCUSDT leverage to be 10x. Production transport is rejected.

This independent journal uses a **20 USDT virtual allocation** and a **temporary 1% margin-loss stop** (roughly 0.1% entry-price distance at 10x, before costs). This tight stop is solely for testing; it does not change the normal strategy's 40% margin-loss stop.

The script opens one Demo long, replays the same opening event to check deduplication, then waits up to 180 seconds. A pass requires reconciliation of the exchange stop's actual order/fills and verified flat positions. If the mark price does not reach the stop, the result is **timeout**, not pass; the script attempts to close only its own position and verify stop cleanup. Any failed cleanup is recorded as an error requiring review. No program can guarantee an exchange exit during an outage.

Results and journals are written under ignored runtime data `data/demo-verification/<run-id>/`. After completion, the interactive script attempts to hand Demo credentials to the local workspace through its authenticated pipe for diagnostic account reads, including after a failed test. This connection does not place orders or start following. Unresolved positions/orders must still be reviewed before any new session. Credentials are memory-only unless the separate Windows-encrypted Demo connection is explicitly remembered locally.

输入同一对模拟密钥即可，不必重新创建。测试有独立账本；只有实际止损成交、仓位和保护单均核对完成，才能记为通过。超时会尝试关闭本轮测试仓位；清理失败则记录错误，需检查模拟交易账户。测试完成后不会自动启动跟随。

## Overnight operation / 过夜观察

- Screen-off does not itself stop the backend. Plugged-in automatic sleep was set to Never for the active Windows power plan; AC hibernation was already disabled. Battery sleep settings were left unchanged. To restore the prior AC idle timeout, use `powercfg /change standby-timeout-ac 5`.
- Keep AC power and the lid open. Manual sleep, logout, shutdown, reboot, a different power plan, or an outage can interrupt operation. A UI tab is not required for the local backend.
- The read-only supervisor and AC awake guard were healthy when checked. Demo execution does not automatically resume following after restart. A restart loses its memory-only Demo credentials.
- An overnight observation period is evidence to review, not a guarantee that future failures or losses cannot occur.

## Follow-up stop test, 02:22-02:23 Asia/Shanghai

The first bounded stop-fill run accepted the local Demo credentials, opened 0.0029 BTC, and verified deduplication. It ended with Binance error `-1021` (invalid request timestamp). Its cleanup verified an empty Demo account, no remaining BTC orders/stops, and zero pending intents. The stop-fill check did **not** pass; its final virtual capital was 19.87344157 USDT.

The verifier now synchronizes server time at startup, at 15-second intervals, and before cleanup. The Demo transport retries only a rejected `GET` once after a fresh time synchronization; order submissions and cancellations are not blindly replayed. Terminal progress and `progress.json` now show the active stage and remaining wait. All 157 Python tests passed after these changes.

## Follow-up stop test, 02:28-02:29 Asia/Shanghai

The next run accepted credentials and settled its opening. Protection could not be verified: the stop query returned `-2013`. The emergency reduce-only close also settled, and the journal quantity reached zero. The subsequent protection-state cleanup still failed, so the report remains **error**, with `flat_verified=false` and `protection_cleared=false`; do not claim complete cleanup from the flat journal alone. No overnight follow session was started.

The original stop-submission exception was still being masked by the later query error. Source code now retains both errors, and a regression test verifies that an explicit rejection is not hidden by a later missing-order response. A missing order is not silently treated as canceled. The verifier now attempts to retain a local diagnostic connection after a failed run without starting following. All 159 Python tests passed. These latest changes have not yet been validated against a further exchange run.

## Operator review and mark-price guard

The user subsequently reported zero Demo positions and zero orders on the phone. This is operator confirmation, not a new API reconciliation of the failed journal.

The failed test requested a MARK_PRICE sell stop at 64633.00. Public Demo mark-price candles for 18:28-18:29 UTC included values below that trigger (18:29 candle opened at 64604.87711957). This supports, but does not prove, the hypothesis that the narrow test stop was already crossed when submitted; the original submission error was not retained in that run.

The bounded verifier now checks the proposed tight stop against the current mark before entry and blocks incompatible entries without opening a position. The engine checks a newly required stop against the mark after fill and refuses automatic stop widening. A crossed stop follows the existing owned-position emergency-exit path. All 161 Python tests passed. No further Demo orders were placed during this diagnosis.

## Follow-up stop test, 02:39-02:43 Asia/Shanghai

The next run passed the mark-price preflight (ask 64588.70, mark 64589.14851449, proposed trigger 64524.20) but again stopped on a missing-order query (`-2013`). It did not verify an actual stop fill. Its emergency exit and cleanup completed: `flat_verified=true`, `protection_cleared=true`, and zero pending intents. Final test capital was 19.81884629 USDT. The local diagnostic connection was retained, and a fresh read at 02:43 confirmed an empty Demo account and 4998.22728843 USDT available.

The recurring query failure despite valid preflight means the mark-price hypothesis is insufficient to explain all failures. Source changes now persist acknowledged exchange `algoId` values, use them for later stop queries/cancellation, validate returned client identity, and retry missing-order reads up to three times without resubmitting an order. These changes passed 163 Python tests; they still require exchange validation. The current connected workspace remains stopped; no overnight follow or production execution was enabled.

## Remaining-work order and repeatable verification

1. Preserve stop acknowledgements and validate lookup using the exchange `algoId`: implemented in source, exchange validation pending.
2. Stop repeated manual key entry: opt-in current-user DPAPI Demo storage, automatic connection restore without order restart, and a background verification worker are implemented. The local remember step is still required for this installation.
3. A bounded worker exposes progress/result in the UI and cannot overlap with following or another verification. It reads only the separate Demo vault; no API keys are passed through HTTP, arguments, environment, logs or source files.
4. After an actual stop fill is verified, review Demo journal/account consistency and separately start Demo following on fresh future signals. Historical openings are not replayed. Current policy authorizes BTCUSDT only; other contracts require a separately reviewed policy/journal.
5. Observe the signal-to-Demo-order chain overnight, retaining the exchange stop and recording any halt. This has not yet started and does not establish production readiness.

All 170 Python tests and the independent browser fixture passed after these workflow changes. The browser fixture exercised verification progress/results and mutual exclusion using a fake child process, not actual exchange stop execution.

## Deployed follow-up and Demo observation, 02:55-02:59 Asia/Shanghai

The separate Demo connection was locally remembered and its Windows-user unlock verified. The updated workspace was restarted and restored the connection without a new prompt or orders. The authenticated UI route launched an independent bounded verification worker using the separate encrypted Demo file.

This exchange run acknowledged and persisted a stop id, confirmed protection, and verified that a duplicate opening event did not create another entry. A later read-only comparison found both the client identifier and the exchange identifier could query the same `NEW` stop. This does not prove which server-side condition caused every earlier `-2013`; the missing early visibility and discarded acknowledgements are now handled more conservatively.

The mark did not trigger the test stop during the bounded wait. The run ended **timeout**, not pass, at 02:58:51: stop_triggered=false, duplicate_checked=true, flat_verified=true, protection_cleared=true, pending_count=0. Final independent test allocation was 20.02147636 USDT. Actual stop-trigger fill reconciliation remains unvalidated on the exchange.

After fresh account and source checks, **Demo following was explicitly started at 02:59:23**. State was running, entries enabled, no error, no owned positions and no pending intents. Current policy authorizes **BTCUSDT only**, 10x, 3% adverse entry limit, 40% margin-loss stop, and full owned matching-direction close on a close signal. Strategy initial allocation is 60 USDT and its existing verified net journal capital is 58.85236206 USDT. Other symbols have not been enabled. Startup baselined existing history; only later public events are eligible. Production account execution remained false.

Remaining checks: an actual exchange stop-trigger fill, the next real public BTC signal through the Demo worker, overnight continuity, and separately reviewed policies/configuration for additional symbols. Restart restores the encrypted connection, not order execution or an automatic takeover of recovered positions.

## User-authorized scope expansion, 03:10-03:12 Asia/Shanghai

Following the user's request to include ETH and other contracts, the flat Demo session was stopped and the catalogue scope expanded with an archived SQLite backup. The actual included scope has 540 candidates: 508 crypto, 26 equity, 6 traditional/index/commodity contracts. Inactive, unsupported or ambiguous entries were excluded. Source policy classification uses the exchange metadata and checks it again before a new entry.

The approved fixed leverage remains 10x for crypto and 3x for equity/traditional assets. Expansion mode prepares leverage on the first eligible Demo entry, only with an unallocated pool and no unowned orders/positions, and verifies the setting before submitting an order. Actual Demo account configuration checks changed ETH and ZEC from 20x to 10x and NVDA from 20x to 3x; no orders were placed by those checks. Other catalogue candidates have not all been exchange-tested.

Capital remained exactly 58.85236206 USDT, preserving the original 60 USDT basis, loss allowance, realized fills, peak and deduplication history. The expanded Demo session was restored to running with entries enabled, no error, fresh source, no positions and no pending intents. Production execution remained false. All 180 Python tests and the independent browser fixture passed after these changes.

### Transient source recovery follow-up

A subsequent source freshness gap stopped the first expanded session under its previous fail-stop rule, although the collector later became fresh again. The Demo tick now holds public signal processing on a temporary freshness gap, continuing exchange protection/risk maintenance and explicit user exits. It resumes from the original source cursor and retains the opening-age and deduplication checks when freshness returns. Exchange uncertainty, ownership mismatch, identity changes and other execution failures still halt for review. The disconnected-source tests were updated to verify holding, preserved stops, and exactly one close after recovery. All 180 tests passed. The flat expanded session was restarted with this change and its saved connection.

## Evening status review, 2026-11-16 Asia/Shanghai

The user requested a limited status review, without further trade tests or changes to the proposed multi-position allocation. Read-only inspection found the Demo session had halted at 18:52:26 on `-1021`. Public collection continued with intermittent navigation timeouts. No owned Demo position, pending intent or protection row remained; production execution stayed disabled.

Since the overnight start, the source recorded one new observed operation: BTCUSDT CLOSE_LONG, source time 13:50:41, first observed 13:54:58.732 (about 4m18s later). It was correctly skipped because the strategy had no matching owned position. No real-source Demo opening occurred, so this interval is not evidence of a completed automated trade cycle. Publication delay and collector retry delay cannot be separated from this record alone.

The account snapshot called several signed reads directly through `TradeClient.account`, bypassing the Demo adapter's timestamp retry. The adapter now resynchronizes and retries that read-only snapshot once on `-1021`; persistent timestamp and permission errors still halt, and order writes are not replayed. Only six targeted clock checks were run, all passed, with no new exchange test orders. The flat Demo workspace was restarted, restored its encrypted connection and resumed the existing 540-symbol, single-position policy. The 20+20+20 allocation remains an unimplemented proposal.

## Detection-price review and user-approved entry/exit semantics

Only one newly observed public event was available for the delay-price review: BTCUSDT CLOSE_LONG, source reference 64558.60, execution 13:50:41, first detection 13:54:58.732. A read-only query of the production public aggregate-trades endpoint found the last trade before detection at 13:54:58.339, price 64424.90 (393 ms earlier). Relative to the source reference this is -0.2070986669%, within 3%. This is a nearby last-trade estimate, not an executable bid/ask quote or evidence about all opening signals; this sample is itself an exit.

The user requested a symmetric +/-3% opening gate and matching exits regardless of price deviation. The engine now uses absolute executable-quote deviation for both long and short entries; public `first_seen` defines the 60-second processing deadline, while execution time remains available for delay statistics. Same-batch openings superseded by a matching later close are skipped. Recorded exits receive priority even during a subsequent public-source freshness gap, and close planning no longer requests an entry quote or requires entry leverage to remain unchanged.

The related strategy/session suite passed 51 checks, including delayed publication, both price-band directions and exact boundaries, price-independent closes, close-first batch handling, and safe waiting startup with an active retrying collector. No exchange test orders were submitted. The saved Demo workspace was restarted to load the rules and reached running/waiting-for-source with no owned positions or pending intents. Production execution remained disabled; the multi-position allocation proposal was not implemented.

## Recurring runtime failures repaired, 2026-11-16 23:07–23:15 Asia/Shanghai

The review found that Demo following had stopped again on `-1021` at 21:02 and the observer had stopped on `Network.getResponseBody: No resource with given identifier found`. Earlier snapshot retries were therefore insufficient to establish reliability.

Signed requests now use a server-time anchor plus monotonic elapsed time, with a 250 ms conservative margin instead of a wall-clock offset and guessed half-RTT. Clock samples taking more than 2 seconds are discarded, with at most three samples before pausing signed requests. Signed GET timestamp correction is centralized in the transport, retries only the rejected GET once, and is not multiplied by Demo adapter retries. Writes and cancellations are never automatically replayed. Measured host/server offset changed between this turn's measurements; the exact cause of every historical rejection is not proven.

The collector now validates matched, current-navigation portfolio responses immediately on `requestfinished`, rather than retaining browser Response objects through page hydration. Verified results/errors are retained instead of a body handle. The specific expired-body transport error rebuilds the collector under the existing bounded backoff while preserving the in-process observation cursor. Access denials, rate limits, invalid payloads and identity/history failures still require review. An initial operation-request timeout recovered automatically on retry in the deployed observer.

The 29 targeted transport/signing/response/observer tests passed. Another 42 related account/session/supervisor tests passed on the host, including its native named-pipe checks (two named-pipe tests could not connect inside the restricted shell and passed when run on the host). Three fresh Demo account reads confirmed zero positions, ordinary orders and stop orders; no exchange test trades were submitted.

The observer was restored and the flat Demo workspace reloaded its separately encrypted saved connection without prompting for keys. Previously authorized Demo following resumed on future signals. Four status samples across 45 seconds at 23:14–23:15 confirmed advancing source poll times and Demo maintenance, fresh source, no errors, zero owned positions and zero pending intents. This short observation is not an overnight stability result or a verified public-signal-to-fill cycle. Production execution remained disabled. Allocation and the proposed multi-position policy were not changed; source changes have not been pushed to GitHub.

## Production source integration, 2026-11-17 00:10–00:38 Asia/Shanghai

The new source work connects a separately gated production broker and production session to the same strategy/accounting and public-event-processing core used by Demo. The Demo engine still rejects production, and the Demo broker cannot switch endpoints. The legacy account HTTP start is disabled; the dedicated production workspace uses localhost:8767 with its own policy, ledger, logs and account-bound local start review. Opening it never arms execution, and neither the launcher nor a restart automatically starts following.

The production transport permits only durable matching order/protection intents and known-stop cancellations, checks its process-local permit for every write, and refuses other mutating endpoints. Contract setup requires an unused pool and flat account, verifies isolated margin and selected leverage, and refuses automatic extra margin. One-way, single-asset USDT mode and USDT fee accounting are required; no account-mode or BNB fee-setting changes are performed by this workflow. Existing manual positions and unconfirmed orders/protection block starting rather than being adopted or reset.

**All 228 Python tests passed on the host.** The separate headless-browser scenario also passed with zero browser errors, two offline fixture orders, explicit reviewed start, signal-driven opening and a full matching close after price moved outside the entry band. The fixture asserts `actual_binance_orders=false`; these are not real exchange trades. The suite exercises actual stop settlement using an offline exchange fixture, not an actual Binance stop-trigger fill.

The installed production preview was opened disarmed, the previously selected 60 USDT / crypto 10x / equity 3x / 40% margin-loss stop / absolute 3% opening band / 60-second detection deadline was saved separately, and the saved production connection was read successfully without re-entering keys. Read-only inspection found account-mode and existing-position blockers and displayed them. No actual order, cancellation, leverage/margin change, account-mode change or transfer was submitted. Detailed private account holdings are kept in the local workspace, not published in this verification record.

A further public-source halt returned the explicit business error `11012005` (service busy). That code now uses bounded connection-error backoff, while access denials, throttling, unknown codes and invalid identity remain blocked. The observer was restored and a later successful public poll verified. Future automatic restarts after a verified transient error retain known public-history continuity, including intervening closes, provided the history can be linked. First initialization and manual pauses/stops still baseline; gaps still require review.

The source implementation and its local verification are complete for this version's documented constraints. This is not a successful real-money execution result, an overnight reliability guarantee, or completion of the previously outstanding actual Demo stop-trigger test. No new portable binary was built or released, and the accumulated source changes have not been pushed to GitHub. See `REAL_EXECUTION.md` for the supported local user workflow and limits.

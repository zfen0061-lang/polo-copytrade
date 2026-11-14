# Risk preview / 风险试算

Open **账户工作台 → 跟单资金草案 → 风险设置 / 试算**.
The calculator adjusts pool size, entry margin, crypto/equity leverage, price-stop or margin-loss
percentage, a per-trade pool-risk budget and a drawdown scenario.

The entered stop percentage has an explicit unit. Ignoring costs:

- Notional = entry margin × leverage.
- Stop loss = notional × adverse price distance.
- Margin-loss percentage ≈ leverage × price-stop percentage.
- Margin compatible with a chosen risk budget ≈ pool × risk percentage ÷ (leverage × price distance).

For illustration only, a pool of 60, margin of 60, leverage of 10 and price stop of 2% implies a loss
of about 12, or 20% of the pool. A 2% pool-risk budget would imply margin of about 6 before costs.
At 10x, a 30% margin-loss scenario corresponds to about a 3% adverse price move.

2% per-trade risk and 10% drawdown are editable **preview examples**, not verified optimal parameters
or enabled account settings. The stop field starts empty. Pool drawdown is only scenario arithmetic;
no high-watermark enforcement is implemented by this calculator.

保存仅保存在本浏览器的试算草案，不修改后台策略草案或实盘参数，不开启交易。
手续费、资金费、滑点、维持保证金、强平机制、交易所最小下单量均可能改变实际结果。
止损订单不保证按触发价成交，达到维持保证金门槛时也可能先发生强平。

References:
- https://www.cmegroup.com/education/courses/trade-and-risk-management/the-2-percent-rule
- https://www.binance.com/en/academy/articles/what-are-stop-loss-and-take-profit-levels-and-how-to-calculate-them

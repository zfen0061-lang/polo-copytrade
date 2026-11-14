"""Reviewable strategy preferences. This module never enables account execution."""
from .core import Invalid,dec,now


def make_compounding_draft(initial_capital):
    capital=dec(initial_capital)
    if capital<=0:raise Invalid('Initial allocated capital must be positive')
    return dict(status='draft',execution_enabled=False,initial_capital_usdt=str(capital),
                sizing='allocated_pool_compounding',use_available_pool_fraction='1',
                realized_net_profit_only=True,outside_funds_included=False,
                close_rule='full_owned_symbol_and_side',close_fraction='1',
                crypto_symbols=['BTCUSDT','ETHUSDT','ZECUSDT'],crypto_leverage=10,crypto_leverage_cap=10,
                equity_leverage_cap=5,equity_leverage_policy=None,
                max_adverse_entry_deviation='0.03',price_stop_pct=None,max_loss_usdt=None,
                account_existing_positions_checked=False,
                blockers=['price_stop_pct','max_loss_usdt','equity_leverage_policy',
                          'existing_position_ownership','verified_compounding_execution'],updated_at=now())


def preview_pool_margin(initial_capital,verified_net_realized,occupied_margin,fee_reserve,exchange_available):
    """Arithmetic preview only. No unrealized P&L or unrelated wallet funds are included."""
    initial=dec(initial_capital)
    occupied,reserve,available=map(dec,(occupied_margin,fee_reserve,exchange_available))
    if initial<=0 or min(occupied,reserve,available)<0:
        raise Invalid('Invalid pool preview amounts')
    pool=max(dec('0'),initial+dec(verified_net_realized)-occupied)
    return max(dec('0'),min(pool,available)-reserve)


def set_margin_stop_target(draft,fraction):
    if draft.get('status')!='draft' or draft.get('execution_enabled') is not False:
        raise Invalid('Only an inactive strategy draft can be updated')
    target=dec(fraction)
    if not 0<target<1:
        raise Invalid('Margin stop target must be between zero and one')
    result=dict(draft)
    result.update(stop_mode='margin_loss_target',margin_stop_loss_fraction=str(target),
                  stop_cost_basis='before_fees_funding_and_slippage',
                  margin_stop_updated_at=now(),updated_at=now())
    result['price_stop_pct']=None  # Legacy unified-price setting is not used by this draft.
    blockers=[b for b in result.get('blockers',[]) if b!='price_stop_pct']
    if 'verified_margin_stop_execution' not in blockers:
        blockers.append('verified_margin_stop_execution')
    result['blockers']=blockers
    return result

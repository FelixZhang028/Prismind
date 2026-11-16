"""The large-pool fast path preserves filtering, scores and point-in-time data."""
import pandas as pd
import numpy as np

from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_based import RuleBasedStrategy, RuleBasedParameters, rank_score
from quant_platform.strategies.rule_schema import RuleStrategyDefinition


def test_batch_numeric_conversion_matches_per_stock_reference_with_missing_and_future_rows():
    days = pd.bdate_range("2024-01-02", periods=80)
    frames = []
    for i in range(15):
        close = (10 + np.arange(80) * .02 + np.sin(np.arange(80) / 3 + i)).astype(object)
        close[10] = "bad"
        close[70:] = 99999  # These future prices must never enter the score.
        frames.append(pd.DataFrame(dict(symbol=f"{i:06d}.SZ", trade_date=days, adjusted_close=close, amount="100000000")))
    bars = pd.concat(frames, ignore_index=True).sample(frac=1, random_state=3)
    rule = RuleStrategyDefinition.from_mapping(dict(strategy_id="test", name="test", entry_logic="all",
        entry_rules=[dict(left=dict(name="close"), operator="greater_than", right=dict(name="moving_average", window=20))],
        ranking=dict(indicator=dict(name="return", window=5), direction="ascending")))
    context = StrategyContext.create(days[60].date(), bars, [f"{i:06d}.SZ" for i in range(10)])
    strategy = RuleBasedStrategy("test", RuleBasedParameters(rule))
    actual = [(s.symbol, s.score) for s in strategy.generate_signals(context)]
    expected = []
    history = context.history(["adjusted_close", "amount"], lookback=rule.minimum_history_days)
    for symbol, original in history.groupby("symbol", observed=True):
        group = original.sort_values("trade_date").copy()
        group[["adjusted_close", "amount"]] = group[["adjusted_close", "amount"]].apply(pd.to_numeric, errors="coerce")
        score = rank_score(group, rule)
        if score is not None:
            expected.append((symbol, score))
    assert actual == sorted(expected, key=lambda item: (-item[1], item[0]))
    assert actual and all(abs(score) < 1 for _, score in actual)

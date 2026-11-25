"""Which stocks meet a rule strategy's conditions on one day (normally the newest local trading day).

It uses the same condition and ranking code as the backtest (``rule_based.rank_score``), so a stock
is listed here exactly when the strategy would consider it on that day. The list only describes the
data: the conditions are the user's own, nothing here is a recommendation.
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any

import pandas as pd

from quant_platform.strategies.rule_based import evaluate_universe
from quant_platform.strategies.rule_schema import QUANTILE_OPERATORS, RuleStrategyDefinition

_NUMERIC = ("adjusted_close", "amount", "raw_close", "pre_close", "raw_open", "raw_high", "raw_low", "volume")
_NON_NUMERIC = frozenset({"symbol", "trade_date", "industry", "sector", "quality_status", "is_st", "is_suspended"})


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def screen(definition: RuleStrategyDefinition, bars: pd.DataFrame, day: date, *,
           exclude_st: bool = True, exclude_suspended: bool = True) -> dict[str, Any]:
    """``{checked, matched, items}``: the stocks with a bar on ``day`` that pass, best first.

    ``bars`` holds each stock's history up to ``day`` (``adjusted_close`` and ``amount`` at least).
    Stocks without a bar that day, ST stocks and suspended stocks are left out (the last two on request).
    Each item has the latest price, the day's change, the ranking value and the values behind every condition.
    """

    if bars.empty:
        return {"checked": 0, "matched": 0, "items": []}
    frame = bars.copy()
    for column in (*_NUMERIC, *definition.data_fields):
        if column in frame.columns and column not in _NON_NUMERIC:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    cutoff = pd.Timestamp(day)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    # 排序、按日期截断、找出每只股票的最后一天都只做一次，不在每只股票里各做一遍
    frame = frame[frame["trade_date"] <= cutoff].sort_values(["symbol", "trade_date"], kind="stable")
    last_rows = frame.groupby("symbol", observed=True, sort=False).tail(1).set_index("symbol")
    keep = last_rows["trade_date"] == cutoff
    if exclude_st:
        if "is_st" in last_rows:
            keep &= last_rows["is_st"].eq(False).fillna(False)
            if "quality_status" in last_rows:
                keep &= last_rows["quality_status"].ne("UNKNOWN_STATUS")
        else:
            keep &= False
    if exclude_suspended and "is_suspended" in last_rows.columns:
        keep &= ~last_rows["is_suspended"].fillna(False).astype(bool)
    wanted = set(last_rows.index[keep])
    frame = frame[frame["symbol"].isin(wanted)]
    checked = len(wanted)
    evaluation = evaluate_universe(frame, cutoff, definition)
    items: list[dict[str, Any]] = []
    for symbol, score in evaluation.scores.items():
        last = last_rows.loc[symbol]
        close, previous = _number(last.get("raw_close")), _number(last.get("pre_close"))
        items.append({
            "symbol": str(symbol),
            "close": close,
            "change": close / previous - 1.0 if close is not None and previous else None,
            "score": score,
            "ranking": evaluation.indicator_values.get(definition.ranking.indicator, {}).get(symbol),
            "conditions": [
                {
                    "left": evaluation.indicator_values.get(rule.left, {}).get(symbol),
                    "right": (
                        evaluation.indicator_values.get(rule.right, {}).get(symbol)
                        if rule.right is not None
                        else rule.value
                    ),
                    **({"quantile": True} if rule.operator in QUANTILE_OPERATORS else {}),
                }
                for rule in definition.entry_rules
            ],
        })
    items.sort(key=lambda item: (-item["score"], item["symbol"]))
    for item in items:
        item.pop("score")
    return {"checked": checked, "matched": len(items), "items": items}

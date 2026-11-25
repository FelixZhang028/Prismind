"""Unit tests for rule strategy factor-library references (builtin/Alpha101/custom) and cross-sectional quantile filters."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.quant.rules import definition_to_frontend, definition_to_quant
from quant_platform.core.exceptions import ConfigurationError
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_based import RuleBasedStrategy, evaluate_universe
from quant_platform.strategies.rule_schema import RuleStrategyDefinition
from quant_platform.strategies.screen import screen


def _synthetic_bars(n_stocks: int = 10, n_days: int = 45) -> tuple[pd.DataFrame, date]:
    dates = pd.bdate_range("2025-01-02", periods=n_days)
    rows = []
    # Stock i has steadily higher trend (higher momentum_20) AND higher daily oscillation (higher volatility_20).
    for i in range(n_stocks):
        sym = f"0000{i:02d}.SZ"
        drift = 0.001 * (i + 1)
        amp = 0.002 * (i + 1)
        price = 10.0
        for d_idx, day in enumerate(dates):
            step = drift + (amp if d_idx % 2 == 0 else -amp * 0.5)
            prev = price
            price = max(1.0, price * (1.0 + step))
            rows.append(
                {
                    "trade_date": day,
                    "symbol": sym,
                    "raw_open": prev,
                    "raw_high": max(prev, price) * 1.005,
                    "raw_low": min(prev, price) * 0.995,
                    "raw_close": price,
                    "adjusted_close": price,
                    "pre_close": prev,
                    "volume": 100_000.0 + i * 5_000.0 + (d_idx % 5) * 1_000.0,
                    "amount": price * (100_000.0 + i * 5_000.0),
                    "is_st": False,
                    "is_suspended": False,
                }
            )
    return pd.DataFrame(rows), dates[-1].date()


def test_rule_schema_validates_factor_references_and_quantile_operators():
    defn = RuleStrategyDefinition.from_mapping(
        {
            "strategy_id": "factor_quantile_test",
            "name": "剔除最差波动与动量选股",
            "entry_logic": "all",
            "entry_rules": [
                {"left": {"name": "factor:volatility_20"}, "operator": "exclude_worst_pct", "value": 20},
                {"left": {"name": "factor:alpha101_101"}, "operator": "top_pct", "value": 80},
            ],
            "ranking": {"indicator": {"name": "factor:momentum_20"}, "direction": "descending"},
        }
    )
    assert defn.has_factor_indicators is True
    assert defn.has_cross_sectional_rules is True
    assert defn.minimum_history_days >= 21
    desc = defn.describe(top_n=10, rebalance="monthly")
    assert "20日波动率剔除最差20%（按因子方向）" in desc
    assert "20日动量" in desc

    # Invalid cases
    with pytest.raises(ConfigurationError, match="未注册的因子"):
        RuleStrategyDefinition.from_mapping(
            {
                "strategy_id": "bad_factor",
                "name": "bad",
                "entry_rules": [{"left": {"name": "factor:no_such_factor"}, "operator": "greater_than", "value": 0}],
                "ranking": {"indicator": {"name": "close"}, "direction": "descending"},
            }
        )
    with pytest.raises(ConfigurationError, match="百分比"):
        RuleStrategyDefinition.from_mapping(
            {
                "strategy_id": "bad_pct",
                "name": "bad",
                "entry_rules": [{"left": {"name": "factor:momentum_20"}, "operator": "exclude_worst_pct", "value": 100}],
                "ranking": {"indicator": {"name": "close"}, "direction": "descending"},
            }
        )
    with pytest.raises(ConfigurationError, match="不需要周期"):
        RuleStrategyDefinition.from_mapping(
            {
                "strategy_id": "bad_win",
                "name": "bad",
                "entry_rules": [{"left": {"name": "factor:momentum_20", "window": 20}, "operator": "greater_than", "value": 0}],
                "ranking": {"indicator": {"name": "close"}, "direction": "descending"},
            }
        )


def test_exclude_worst_pct_respects_factor_direction_in_backtest_and_screen():
    bars, last_day = _synthetic_bars(n_stocks=10, n_days=45)

    # 1. Positive-direction factor (momentum_20, direction=+1): exclude_worst_pct=20 removes lowest 2 (000000, 000001).
    mom_def = RuleStrategyDefinition.from_mapping(
        {
            "strategy_id": "mom_excl",
            "name": "动量剔除最差20%",
            "entry_rules": [{"left": {"name": "factor:momentum_20"}, "operator": "exclude_worst_pct", "value": 20}],
            "ranking": {"indicator": {"name": "factor:momentum_20"}, "direction": "descending"},
        }
    )
    mom_eval = evaluate_universe(bars, pd.Timestamp(last_day), mom_def)
    assert len(mom_eval.scores) == 8
    assert "000000.SZ" not in mom_eval.scores and "000001.SZ" not in mom_eval.scores
    assert "000009.SZ" in mom_eval.scores

    # 2. Negative-direction factor (volatility_20, direction=-1): exclude_worst_pct=20 removes HIGHEST vol 2 (000008, 000009).
    vol_def = RuleStrategyDefinition.from_mapping(
        {
            "strategy_id": "vol_excl",
            "name": "波动率剔除最差20%",
            "entry_rules": [{"left": {"name": "factor:volatility_20"}, "operator": "exclude_worst_pct", "value": 20}],
            "ranking": {"indicator": {"name": "factor:momentum_20"}, "direction": "descending"},
        }
    )
    ctx = StrategyContext.create(last_day, bars, tuple(sorted(bars["symbol"].unique())))
    strategy = RuleBasedStrategy.from_parameters("vol_excl", {"definition_json": vol_def.to_json()})
    signals = strategy.generate_signals(ctx)
    kept_symbols = {s.symbol for s in signals}
    assert len(kept_symbols) == 8
    assert "000009.SZ" not in kept_symbols and "000008.SZ" not in kept_symbols
    assert "000000.SZ" in kept_symbols

    # 3. Stock screen returns identical matched set as backtest RuleBasedStrategy.
    screened = screen(vol_def, bars, last_day, exclude_st=True, exclude_suspended=True)
    assert screened["checked"] == 10
    assert screened["matched"] == 8
    assert {item["symbol"] for item in screened["items"]} == kept_symbols
    assert screened["items"][0]["conditions"][0]["quantile"] is True


def test_alpha101_and_quantile_operators_round_trip_through_rules_adapter():
    frontend_def = {
        "name": "Alpha101 分位过滤策略",
        "entry_logic": "all",
        "entry_rules": [
            {"left": {"name": "factor:alpha101_006"}, "operator": "exclude_bottom_pct", "value": 20},
            {"left": {"name": "factor:alpha101_101"}, "operator": "top_pct", "value": 50},
        ],
        "ranking": {"indicator": {"name": "factor:momentum_20"}, "direction": "descending"},
    }
    quant_def = definition_to_quant(frontend_def)
    quant_def["strategy_id"] = "alpha101_q"
    parsed = RuleStrategyDefinition.from_mapping(quant_def)
    back = definition_to_frontend(parsed.to_dict())
    assert back["entry_rules"] == frontend_def["entry_rules"]
    assert back["ranking"] == frontend_def["ranking"]

    bars, last_day = _synthetic_bars(n_stocks=10, n_days=45)
    ctx = StrategyContext.create(last_day, bars, tuple(sorted(bars["symbol"].unique())))
    strat = RuleBasedStrategy.from_parameters("alpha101_q", {"definition_json": parsed.to_json()})
    signals = strat.generate_signals(ctx)
    assert len(signals) <= 5

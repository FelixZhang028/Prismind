"""Unit tests for quarterly rebalance, backtest hold_buffer, built-in dividend_yield, top-card FDR q, and 250d vol style."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.quant.result_adapter import factor_report_to_dict
from app.routes.backtests import BacktestIn
from app.routes.workspace import PackageBacktestIn
from quant_platform.application.backtest_service import BacktestRequest, BacktestService
from quant_platform.backtest.engine import BacktestEngine
from quant_platform.data.corporate_actions import DIVIDEND_YIELD
from quant_platform.factors.evaluation import FactorEvaluator
from quant_platform.factors.registry import default_registry


def test_quarterly_rebalance_dates_pick_quarter_ends():
    dates = [
        date(2024, 1, 15),
        date(2024, 3, 28),
        date(2024, 3, 29),
        date(2024, 4, 1),
        date(2024, 6, 28),
        date(2024, 9, 30),
        date(2024, 12, 31),
    ]
    engine = object.__new__(BacktestEngine)
    engine.rebalance = "quarterly"
    rebalance_dates = engine._rebalance_dates(dates)
    assert rebalance_dates == {
        date(2024, 3, 29),
        date(2024, 6, 28),
        date(2024, 9, 30),
        date(2024, 12, 31),
    }


def test_backtest_request_and_schemas_accept_quarterly_and_hold_buffer():
    req = BacktestRequest(
        strategy_plugin="factor_composite",
        strategy_id="fc_1",
        strategy_parameters={},
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        initial_cash=1_000_000.0,
        top_n=20,
        rebalance="quarterly",
        hold_buffer=20,
    )
    BacktestService._validate_request(req)

    bad_buffer = BacktestRequest(
        strategy_plugin="factor_composite",
        strategy_id="fc_1",
        strategy_parameters={},
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        initial_cash=1_000_000.0,
        top_n=20,
        rebalance="quarterly",
        hold_buffer=-1,
    )
    with pytest.raises(ValueError, match="hold_buffer"):
        BacktestService._validate_request(bad_buffer)

    api_in = BacktestIn(
        strategy="factor_composite",
        market="current_pool",
        from_date="2024-01-01",
        to_date="2024-12-31",
        max_positions=20,
        rebalance="quarterly",
        hold_buffer=20,
    )
    assert api_in.rebalance == "quarterly"
    assert api_in.hold_buffer == 20

    pkg_in = PackageBacktestIn(
        from_date="2024-01-01",
        to_date="2024-12-31",
        top_n=20,
        rebalance="quarterly",
        hold_buffer=15,
    )
    assert pkg_in.rebalance == "quarterly"
    assert pkg_in.hold_buffer == 15


def test_builtin_dividend_yield_factor_registered_and_computes():
    registry = default_registry()
    assert DIVIDEND_YIELD in registry
    factor = registry.get(DIVIDEND_YIELD)
    assert factor.category == "估值"
    assert factor.direction == 1
    assert factor.required_fields == (DIVIDEND_YIELD,)

    bars = pd.DataFrame(
        [
            {"trade_date": pd.Timestamp("2025-01-02"), "symbol": "000001.SZ", DIVIDEND_YIELD: 0.045},
            {"trade_date": pd.Timestamp("2025-01-02"), "symbol": "600519.SH", DIVIDEND_YIELD: 0.025},
        ]
    )
    result = factor.compute(bars)
    values = dict(zip(result["symbol"], result["value"], strict=True))
    assert values["000001.SZ"] == pytest.approx(0.045)
    assert values["600519.SH"] == pytest.approx(0.025)


class _StubFactorRepo:
    def __init__(self, bars: pd.DataFrame) -> None:
        self._bars = bars

    def get_daily_bars(self, symbols=None, end_date=None, **kwargs):
        frame = self._bars.copy()
        if symbols:
            frame = frame[frame["symbol"].isin(symbols)]
        if end_date is not None:
            frame = frame[pd.to_datetime(frame["trade_date"]) <= pd.Timestamp(end_date)]
        return frame

    def read_table(self, name: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self) -> pd.DataFrame:
        return pd.DataFrame()


def test_single_factor_report_includes_significance_fdr_q_and_volatility_250_style():
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-02", periods=310)
    symbols = [f"00000{i}.SZ" for i in range(1, 9)]
    rows = []
    for idx, sym in enumerate(symbols):
        vol = 0.008 + idx * 0.004
        returns = rng.normal(0.0005, vol, size=len(dates))
        prices = 10.0 * np.cumprod(1.0 + returns)
        for day, price in zip(dates, prices, strict=True):
            rows.append(
                {
                    "trade_date": day,
                    "symbol": sym,
                    "raw_open": float(price),
                    "raw_high": float(price * 1.01),
                    "raw_low": float(price * 0.99),
                    "raw_close": float(price),
                    "adjusted_close": float(price),
                    "pre_close": float(price),
                    "volume": 100_000.0,
                    "amount": float(price * 100_000.0),
                }
            )
    bars = pd.DataFrame(rows)
    repo = _StubFactorRepo(bars)
    evaluator = FactorEvaluator(repo)
    factor = default_registry().get("momentum_20")

    report = evaluator.evaluate(
        factor,
        start_date=dates[260].date(),
        end_date=dates[-1].date(),
        horizon=5,
        n_groups=4,
        diagnostics=True,
    )
    assert "fdr_q" in report.significance
    assert report.significance["fdr_horizons"] == 4
    decay_5 = report.decay.loc[report.decay["horizon"] == 5].iloc[0]
    assert report.significance["fdr_q"] == pytest.approx(decay_5["fdr_q"], nan_ok=True)

    style_keys = {item["style"] for item in report.style_correlations}
    assert "volatility_20" in style_keys
    assert "volatility_250" in style_keys

    payload = factor_report_to_dict(report)
    assert "fdr_q" in payload["significance"]
    assert payload["significance"]["fdr_horizons"] == 4
    assert any(item["style"] == "volatility_250" for item in payload["style_correlations"])

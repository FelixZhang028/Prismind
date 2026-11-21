"""Tests for per-position stop-loss / trailing take-profit exit rules and trade reason tagging."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.quant.result_adapter import backtest_run_to_result
from app.quant.run_trades import symbol_trades
from quant_platform.backtest.engine import BacktestEngine
from quant_platform.core.exceptions import ConfigurationError
from quant_platform.execution.models import TradeReason
from quant_platform.execution.next_open import ExecutionConfig, NextOpenExecutionModel
from quant_platform.execution.order_generator import OrderGenerator
from quant_platform.portfolio.equal_weight import EqualWeightPortfolio
from quant_platform.risk.config import RiskLimits
from quant_platform.signals.models import Signal
from quant_platform.strategies.base import Strategy
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_based import RuleBasedStrategy
from quant_platform.strategies.rule_schema import ExitRulesSpec, MarketTimingSpec, RuleStrategyDefinition
from quant_platform.strategies.templates import beginner_templates
from quant_platform.universe.a_share import AShareUniverse, AShareUniverseConfig
from test_strategy_workflow import api, workflow  # noqa: F401 - pytest fixtures


def _base_definition(**extra) -> dict:
    return {
        "schema_version": 1,
        "strategy_id": "exit_rules_test",
        "name": "止损止盈测试策略",
        "description": "",
        "entry_logic": "all",
        "entry_rules": [
            {"left": {"name": "close"}, "operator": "greater_than", "value": 0.0},
        ],
        "ranking": {
            "indicator": {"name": "return", "window": 5},
            "direction": "descending",
        },
        **extra,
    }


def _trading_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    cur = start
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


class _MemoryRepository:
    def __init__(
        self,
        daily_bars: pd.DataFrame,
        benchmark_bars: pd.DataFrame | None = None,
        corporate_actions: pd.DataFrame | None = None,
    ) -> None:
        self._daily_bars = daily_bars.copy()
        self._benchmark_bars = (
            benchmark_bars.copy()
            if benchmark_bars is not None
            else pd.DataFrame(columns=["symbol", "trade_date", "raw_close"])
        )
        self._corporate_actions = (
            corporate_actions.copy()
            if corporate_actions is not None
            else pd.DataFrame()
        )
        unique_dates = sorted(pd.to_datetime(daily_bars["trade_date"]).dt.normalize().unique())
        self._calendar = pd.DataFrame({"cal_date": unique_dates, "is_open": 1})
        symbols = sorted(daily_bars["symbol"].unique())
        self._master = pd.DataFrame(
            {
                "symbol": symbols,
                "list_date": [pd.Timestamp("2015-01-01")] * len(symbols),
                "delist_date": [pd.NaT] * len(symbols),
            }
        )

    def get_trade_calendar(self, start_date: date, end_date: date) -> pd.DataFrame:
        mask = self._calendar["cal_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
        return self._calendar.loc[mask].copy()

    def get_daily_bars(
        self,
        symbols: list[str] | None,
        start_date: date,
        end_date: date,
        extras: tuple[str, ...] | None = None,
    ) -> pd.DataFrame:
        frame = self._daily_bars
        mask = frame["trade_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
        if symbols is not None:
            mask &= frame["symbol"].isin(symbols)
        return frame.loc[mask].copy()

    def read_table(self, name: str) -> pd.DataFrame:
        if name == "benchmark_bars":
            return self._benchmark_bars.copy()
        if name == "security_master":
            return self._master.copy()
        if name == "trade_calendar":
            return self._calendar.copy()
        if name == "corporate_actions":
            return self._corporate_actions.copy()
        return pd.DataFrame()


class _ConstantStrategy(Strategy):
    required_fields = frozenset({"symbol", "trade_date", "adjusted_close"})

    def __init__(
        self,
        scores: dict[str, float],
        *,
        hold_buffer: int = 0,
        market_timing: MarketTimingSpec | None = None,
        exit_rules: ExitRulesSpec | None = None,
    ) -> None:
        self.strategy_id = "const_exit_test"
        self._scores = scores
        self.hold_buffer = hold_buffer
        self.market_timing = market_timing
        self.exit_rules = exit_rules

    @classmethod
    def from_parameters(cls, strategy_id: str, parameters: dict) -> _ConstantStrategy:
        return cls(parameters.get("scores", {}))

    def generate_signals(self, context: StrategyContext) -> list[Signal]:
        return [
            Signal(
                strategy_id=self.strategy_id,
                trade_date=context.trade_date,
                symbol=symbol,
                signal_type="CONST",
                score=score,
            )
            for symbol, score in sorted(self._scores.items(), key=lambda item: (-item[1], item[0]))
        ]


def _make_price_bars(
    dates: list[date],
    price_paths: dict[str, list[tuple[float, float] | tuple[float, float, float]]],
) -> pd.DataFrame:
    """Build bars from (raw_open, raw_close[, adj_factor]) tuples per symbol."""
    rows = []
    for day_idx, trade_date in enumerate(dates):
        for symbol, series in price_paths.items():
            item = series[day_idx]
            raw_open = float(item[0])
            raw_close = float(item[1])
            factor = float(item[2]) if len(item) >= 3 else 1.0
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp(trade_date),
                    "raw_open": raw_open,
                    "raw_high": max(raw_open, raw_close) * 1.01,
                    "raw_low": min(raw_open, raw_close) * 0.99,
                    "raw_close": raw_close,
                    "adjusted_close": raw_close * factor,
                    "adj_factor": factor,
                    "volume": 50_000_000.0,
                    "amount": 50_000_000.0 * raw_close,
                    "is_suspended": False,
                    "is_st": False,
                    "is_listed": True,
                    "quality_status": "OK",
                    "up_limit": round(raw_open * 1.2, 2),
                    "down_limit": round(raw_open * 0.8, 2),
                    "can_buy_open": True,
                    "can_sell_open": True,
                }
            )
    return pd.DataFrame(rows)


def _build_engine(repo, strategy, *, top_n: int = 1, rebalance: str = "monthly") -> BacktestEngine:
    symbols = tuple(sorted(repo._daily_bars["symbol"].unique()))
    return BacktestEngine(
        repository=repo,
        universe=AShareUniverse(AShareUniverseConfig(symbols=symbols, minimum_history_days=0)),
        strategy=strategy,
        portfolio=EqualWeightPortfolio(top_n=top_n),
        order_generator=OrderGenerator(100),
        execution_model=NextOpenExecutionModel(ExecutionConfig(historical_fees=False)),
        rebalance=rebalance,
        risk_limits=RiskLimits(enabled=False),
        fixed_universe=True,
        benchmark_symbol="000300.SH",
        warmup_days=0,
    )


# --------------------------------------------------------------------------- #
# 1. Schema 序列化、校验与白话解释
# --------------------------------------------------------------------------- #


def test_exit_rules_schema_defaults_roundtrip_and_describe():
    plain = RuleStrategyDefinition.from_mapping(_base_definition())
    assert plain.exit_rules is None
    assert "exit_rules" not in plain.to_dict()
    assert "个股风控" not in plain.describe(top_n=5, rebalance="weekly")

    both = RuleStrategyDefinition.from_mapping(
        _base_definition(exit_rules={"stop_loss_pct": 0.1, "trailing_stop_pct": 0.15})
    )
    restored = RuleStrategyDefinition.from_json(both.to_json())
    assert restored == both
    assert restored.exit_rules == ExitRulesSpec(stop_loss_pct=0.1, trailing_stop_pct=0.15)
    desc = restored.describe(top_n=5, rebalance="weekly")
    assert "单只持仓较成本亏损达到10%时次日开盘止损卖出" in desc
    assert "从持仓以来最高价回撤达到15%时次日开盘止盈卖出" in desc

    strategy = RuleBasedStrategy.from_parameters("s1", {"definition_json": restored.to_json()})
    assert strategy.exit_rules == ExitRulesSpec(stop_loss_pct=0.1, trailing_stop_pct=0.15)

    # 关闭或全空归零为 None
    for empty_spec in (
        {"enabled": False, "stop_loss_pct": 0.1},
        {"stop_loss_pct": None, "trailing_stop_pct": None},
        {"stop_loss_pct": 0, "trailing_stop_pct": ""},
    ):
        assert RuleStrategyDefinition.from_mapping(_base_definition(exit_rules=empty_spec)).exit_rules is None


@pytest.mark.parametrize(
    "bad_exit",
    [
        {"stop_loss_pct": 0.01},
        {"stop_loss_pct": 0.55},
        {"stop_loss_pct": True},
        {"trailing_stop_pct": 0.02},
        {"trailing_stop_pct": 0.60},
        {"trailing_stop_pct": False},
        "invalid",
    ],
)
def test_exit_rules_schema_rejects_invalid_values(bad_exit):
    with pytest.raises(ConfigurationError):
        RuleStrategyDefinition.from_mapping(_base_definition(exit_rules=bad_exit))


# --------------------------------------------------------------------------- #
# 2. 个股止损在非调仓日触发，并标注卖出原因
# --------------------------------------------------------------------------- #


def test_engine_stop_loss_triggers_between_rebalances_and_tags_fill_reason():
    # Day 0 = 2025-01-31（1月末月度调仓日）-> Day 1 开盘 10.0 买入 -> Day 3（2月非调仓日）收盘 8.8 (-12%) -> Day 4 开盘止损卖出
    days = _trading_days(date(2025, 1, 31), 6)
    bars = _make_price_bars(
        days,
        {
            "000001.SZ": [
                (10.0, 10.0),
                (10.0, 9.8),
                (9.8, 9.5),
                (9.4, 8.8),
                (8.7, 8.5),
                (8.5, 8.4),
            ]
        },
    )
    repo = _MemoryRepository(bars)
    strategy = _ConstantStrategy({"000001.SZ": 1.0}, exit_rules=ExitRulesSpec(stop_loss_pct=0.10))
    result = _build_engine(repo, strategy, top_n=1, rebalance="monthly").run(
        days[0], days[-1], initial_cash=1_000_000.0
    )

    assert len(result.fills) == 2
    assert list(result.fills["side"]) == ["BUY", "SELL"]
    assert list(result.fills["reason"]) == [TradeReason.REBALANCE_BUY.value, TradeReason.STOP_LOSS.value]
    assert list(result.fills["trade_date"]) == [days[1], days[4]]
    assert result.summary["exit_rules"] == {"stop_loss_pct": 0.10}
    assert result.summary["stop_loss_triggers"] == 1
    assert result.summary["trailing_stop_triggers"] == 0
    exit_events = result.risk_events[result.risk_events["event_type"] == "POSITION_EXIT"]
    assert len(exit_events) == 1
    assert "个股止损触发" in exit_events.iloc[0]["reason"]

    adapted = backtest_run_to_result(SimpleNamespace(result=result, output_dir=Path("runs/test")))
    assert [t["reason_label"] for t in adapted["trades"]] == ["调仓买入", "个股止损"]
    assert adapted["stop_loss_triggers"] == 1


# --------------------------------------------------------------------------- #
# 3. 移动止盈跟踪持仓期最高价，从高点回撤达阈值触发卖出
# --------------------------------------------------------------------------- #


def test_engine_trailing_stop_triggers_from_holding_peak_even_while_profitable():
    # Day 0 = 2025-01-31（月末调仓）-> Day 1 买入 10.0 -> Day 3 冲高到 14.0 -> Day 4 回落到 11.8 (较峰值回撤 -15.7%, 仍盈利 +18%) -> Day 5 止盈卖出
    days = _trading_days(date(2025, 1, 31), 7)
    bars = _make_price_bars(
        days,
        {
            "000001.SZ": [
                (10.0, 10.0),
                (10.0, 11.5),
                (11.6, 13.0),
                (13.2, 14.0),
                (13.8, 11.8),
                (11.7, 11.5),
                (11.5, 11.4),
            ]
        },
    )
    repo = _MemoryRepository(bars)
    strategy = _ConstantStrategy({"000001.SZ": 1.0}, exit_rules=ExitRulesSpec(trailing_stop_pct=0.15))
    result = _build_engine(repo, strategy, top_n=1, rebalance="monthly").run(
        days[0], days[-1], initial_cash=1_000_000.0
    )

    assert len(result.fills) == 2
    assert list(result.fills["reason"]) == [TradeReason.REBALANCE_BUY.value, TradeReason.TRAILING_STOP.value]
    assert list(result.fills["trade_date"]) == [days[1], days[5]]
    assert result.summary["trailing_stop_triggers"] == 1
    assert result.summary["stop_loss_triggers"] == 0


# --------------------------------------------------------------------------- #
# 4. 除权除息不会误触发个股止损（复权口径一致）
# --------------------------------------------------------------------------- #


def test_engine_ex_dividend_drop_does_not_falsely_trigger_stop_loss():
    # Day 0 = 2025-01-31（月末调仓）-> Day 1 买入 -> Day 3 现金分红 1.5 元/股：未复权价 10.0 -> 8.5 (-15%)，复权因子 1.0 -> 10/8.5，真实收益 0%
    days = _trading_days(date(2025, 1, 31), 6)
    div_factor = 10.0 / 8.5
    bars = _make_price_bars(
        days,
        {
            "000001.SZ": [
                (10.0, 10.0, 1.0),
                (10.0, 10.0, 1.0),
                (10.0, 10.0, 1.0),
                (8.5, 8.5, div_factor),
                (8.5, 8.5, div_factor),
                (8.5, 8.5, div_factor),
            ]
        },
    )
    actions = pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "ex_date": pd.Timestamp(days[3]),
                "cash_per_share": 1.5,
                "share_multiplier": 1.0,
            }
        ]
    )
    repo = _MemoryRepository(bars, corporate_actions=actions)
    strategy = _ConstantStrategy({"000001.SZ": 1.0}, exit_rules=ExitRulesSpec(stop_loss_pct=0.10))
    result = _build_engine(repo, strategy, top_n=1, rebalance="monthly").run(
        days[0], days[-1], initial_cash=1_000_000.0
    )

    assert len(result.fills) == 1  # 仅首笔买入，除息日未误触发止损
    assert result.summary["stop_loss_triggers"] == 0


# --------------------------------------------------------------------------- #
# 5. 调仓日触发止损时优先卖出且不被 hold_buffer 强行留仓
# --------------------------------------------------------------------------- #


def test_rebalance_day_stop_loss_overrides_hold_buffer_and_prevents_same_day_rebuy():
    days = _trading_days(date(2025, 2, 3), 5)
    # 每日调仓 + hold_buffer=2，000001.SZ 永远排第 1；Day 2 收盘暴跌 -15%，必须止损卖出而不是被缓冲留仓
    bars = _make_price_bars(
        days,
        {
            "000001.SZ": [(10.0, 10.0), (10.0, 9.9), (9.8, 8.5), (8.4, 8.4), (8.4, 8.4)],
            "000002.SZ": [(10.0, 10.0), (10.0, 10.0), (10.0, 10.0), (10.0, 10.0), (10.0, 10.0)],
        },
    )
    repo = _MemoryRepository(bars)
    strategy = _ConstantStrategy(
        {"000001.SZ": 2.0, "000002.SZ": 1.0},
        hold_buffer=2,
        exit_rules=ExitRulesSpec(stop_loss_pct=0.10),
    )
    result = _build_engine(repo, strategy, top_n=1, rebalance="daily").run(
        days[0], days[-1], initial_cash=1_000_000.0
    )

    day3_sells = result.fills[(result.fills["trade_date"] == days[3]) & (result.fills["side"] == "SELL")]
    assert len(day3_sells) == 1
    assert day3_sells.iloc[0]["symbol"] == "000001.SZ"
    assert day3_sells.iloc[0]["reason"] == TradeReason.STOP_LOSS.value


# --------------------------------------------------------------------------- #
# 6. 大盘择时卖出原因 + run_trades.symbol_trades Parquet 透传与旧记录兼容
# --------------------------------------------------------------------------- #


def test_market_timing_sell_reason_and_symbol_trades_parquet(tmp_path):
    all_days = _trading_days(date(2025, 1, 2), 14)
    bt_days = all_days[8:]
    bars = _make_price_bars(
        bt_days,
        {"000001.SZ": [(10.0, 10.0)] * len(bt_days)},
    )
    bench_prices = [3500.0] * 8 + [3600.0, 3620.0, 3100.0, 3050.0, 3000.0, 2980.0]
    benchmark_bars = pd.DataFrame(
        {
            "symbol": ["000300.SH"] * len(all_days),
            "trade_date": [pd.Timestamp(d) for d in all_days],
            "raw_close": bench_prices,
        }
    )
    repo = _MemoryRepository(bars, benchmark_bars)
    timing = MarketTimingSpec(benchmark="000300.SH", ma_window=5, off_weight=0.0)
    result = _build_engine(repo, _ConstantStrategy({"000001.SZ": 1.0}, market_timing=timing), top_n=1, rebalance="daily").run(
        bt_days[0], bt_days[-1], initial_cash=1_000_000.0
    )

    sell_fills = result.fills[result.fills["side"] == "SELL"]
    assert len(sell_fills) == 1
    assert sell_fills.iloc[0]["reason"] == TradeReason.MARKET_TIMING_SELL.value

    # 持久化到 parquet 并经 symbol_trades 读取，应带出中文原因标签
    run_dir = tmp_path / "run_with_reason"
    run_dir.mkdir()
    result.fills.to_parquet(run_dir / "fills.parquet", index=False)
    result.orders.to_parquet(run_dir / "orders.parquet", index=False)
    result.positions.to_parquet(run_dir / "positions.parquet", index=False)
    result.nav.to_parquet(run_dir / "nav.parquet", index=False)

    tr = symbol_trades(run_dir, "000001.SZ")
    assert [f["reason_label"] for f in tr["fills"]] == ["调仓买入", "大盘择时降仓"]

    # 旧版没有 reason 列的 fills.parquet 也应正常读取，不报错
    legacy_dir = tmp_path / "run_legacy"
    legacy_dir.mkdir()
    result.fills.drop(columns=["reason"]).to_parquet(legacy_dir / "fills.parquet", index=False)
    result.orders.to_parquet(legacy_dir / "orders.parquet", index=False)
    result.positions.to_parquet(legacy_dir / "positions.parquet", index=False)
    result.nav.to_parquet(legacy_dir / "nav.parquet", index=False)
    legacy_tr = symbol_trades(legacy_dir, "000001.SZ")
    assert [f["reason_label"] for f in legacy_tr["fills"]] == ["", ""]


# --------------------------------------------------------------------------- #
# 7. API 往返：preflight / create / template_modified / backtest
# --------------------------------------------------------------------------- #


def test_studio_api_roundtrips_exit_rules_and_detects_template_edit(workflow):
    client, _, captured, *_ = workflow
    template = beginner_templates()[0]
    preset = template.presets["balanced"]
    definition = {
        "name": f"{template.name}-止损止盈版",
        "entry_logic": preset.definition.entry_logic,
        "entry_rules": [{"left": {"name": "close"}, "operator": "gt", "value": 0.0}],
        "ranking": {"indicator": {"name": "return_1d", "window": 20}, "direction": "descending"},
        "exit_rules": {"stop_loss_pct": 0.1, "trailing_stop_pct": 0.15},
    }

    preflight = client.post(
        "/api/v1/packages/preflight",
        json={"definition": definition, "top_n": 5, "rebalance": "weekly", "source": "visual_builder"},
    )
    assert preflight.status_code == 200, preflight.text
    assert "个股风控" in preflight.json()["description"]

    created = client.post(
        "/api/v1/packages",
        json={
            "definition": definition,
            "top_n": 5,
            "rebalance": "weekly",
            "source": f"template:{template.template_id}",
            "style": "balanced",
        },
    )
    assert created.status_code == 201, created.text
    pkg = created.json()
    assert pkg["source"].startswith("template_modified:")
    assert pkg["definition"]["exit_rules"] == {"stop_loss_pct": 0.1, "trailing_stop_pct": 0.15}

    run_resp = client.post(
        "/api/v1/backtests",
        json={
            "strategy": f"package:{pkg['package_id']}",
            "market": "当前股票池",
            "from_date": "2025-01-01",
            "to_date": "2025-12-31",
            "initial_capital": 250000,
            "max_positions": 5,
            "rebalance": "weekly",
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    sent_def = json.loads(captured[0].strategy_parameters["definition_json"])
    assert sent_def["exit_rules"] == {"stop_loss_pct": 0.1, "trailing_stop_pct": 0.15}

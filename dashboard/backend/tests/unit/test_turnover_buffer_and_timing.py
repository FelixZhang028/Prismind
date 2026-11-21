"""Tests for rank hold buffer (防频繁换手缓冲) and benchmark MA market timing (大盘均线择时)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.quant.result_adapter import backtest_run_to_result
from quant_platform.backtest.engine import BacktestEngine
from quant_platform.core.exceptions import BacktestValidityError, ConfigurationError
from quant_platform.execution.next_open import ExecutionConfig, NextOpenExecutionModel
from quant_platform.execution.order_generator import OrderGenerator
from quant_platform.portfolio.equal_weight import EqualWeightPortfolio
from quant_platform.portfolio.risk_weighted import RiskWeightedPortfolio
from quant_platform.risk.config import RiskLimits
from quant_platform.signals.models import Signal
from quant_platform.strategies.base import Strategy
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.rule_based import RuleBasedStrategy
from quant_platform.strategies.rule_schema import MarketTimingSpec, RuleStrategyDefinition
from quant_platform.strategies.templates import beginner_templates
from quant_platform.universe.a_share import AShareUniverse, AShareUniverseConfig
from test_strategy_workflow import api, workflow  # noqa: F401 - pytest fixtures


def _base_definition(**extra) -> dict:
    return {
        "schema_version": 1,
        "strategy_id": "buffer_timing_test",
        "name": "缓冲与择时测试策略",
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


class _MemoryRepository:
    def __init__(self, daily_bars: pd.DataFrame, benchmark_bars: pd.DataFrame | None = None) -> None:
        self._daily_bars = daily_bars.copy()
        self._benchmark_bars = (
            benchmark_bars.copy()
            if benchmark_bars is not None
            else pd.DataFrame(columns=["symbol", "trade_date", "raw_close"])
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
        return pd.DataFrame()


class _ScriptedScoreStrategy(Strategy):
    """Strategy emitting deterministic daily scores per symbol so rank churn is exact."""

    required_fields = frozenset({"symbol", "trade_date", "adjusted_close"})

    def __init__(
        self,
        scores_by_date: dict[date, dict[str, float]],
        *,
        hold_buffer: int = 0,
        market_timing: MarketTimingSpec | None = None,
    ) -> None:
        self.strategy_id = "scripted_scores"
        self._scores_by_date = scores_by_date
        self.hold_buffer = hold_buffer
        self.market_timing = market_timing

    @classmethod
    def from_parameters(cls, strategy_id: str, parameters: dict) -> _ScriptedScoreStrategy:
        return cls(parameters.get("scores_by_date", {}))

    def generate_signals(self, context: StrategyContext) -> list[Signal]:
        mapping = self._scores_by_date.get(context.trade_date, {})
        return [
            Signal(
                strategy_id=self.strategy_id,
                trade_date=context.trade_date,
                symbol=symbol,
                signal_type="SCRIPTED",
                score=score,
            )
            for symbol, score in sorted(mapping.items(), key=lambda item: (-item[1], item[0]))
        ]


def _make_bars(dates: list[date], symbols: list[str], base_price: float = 10.0) -> pd.DataFrame:
    rows = []
    for day_idx, trade_date in enumerate(dates):
        for sym_idx, symbol in enumerate(symbols):
            price = base_price + sym_idx * 0.5 + day_idx * 0.02
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp(trade_date),
                    "raw_open": price,
                    "raw_high": price * 1.01,
                    "raw_low": price * 0.99,
                    "raw_close": price,
                    "adjusted_close": price,
                    "adj_factor": 1.0,
                    "volume": 5_000_000.0,
                    "amount": 5_000_000.0 * price,
                    "is_suspended": False,
                    "is_st": False,
                    "is_listed": True,
                    "quality_status": "OK",
                    "up_limit": round(price * 1.1, 2),
                    "down_limit": round(price * 0.9, 2),
                    "can_buy_open": True,
                    "can_sell_open": True,
                }
            )
    return pd.DataFrame(rows)


def _trading_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    cur = start
    while len(days) < count:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


# --------------------------------------------------------------------------- #
# 1. Schema 序列化、校验与白话解释
# --------------------------------------------------------------------------- #


def test_rule_schema_defaults_preserve_legacy_dict_shape():
    definition = RuleStrategyDefinition.from_mapping(_base_definition())
    payload = definition.to_dict()
    assert definition.hold_buffer == 0
    assert definition.market_timing is None
    assert "hold_buffer" not in payload
    assert "market_timing" not in payload
    assert "防频繁换手" not in definition.describe(top_n=5, rebalance="weekly")
    assert "大盘择时" not in definition.describe(top_n=5, rebalance="weekly")


def test_rule_schema_roundtrips_and_describes_buffer_and_timing():
    definition = RuleStrategyDefinition.from_mapping(
        _base_definition(
            hold_buffer=10,
            market_timing={"benchmark": "000300.SH", "ma_window": 60, "off_weight": 0.3},
        )
    )
    restored = RuleStrategyDefinition.from_json(definition.to_json())
    assert restored == definition
    assert restored.hold_buffer == 10
    assert restored.market_timing == MarketTimingSpec("000300.SH", 60, 0.3)

    text = restored.describe(top_n=5, rebalance="weekly")
    assert "排名在前15名以内继续保留" in text
    assert "大盘择时：当沪深 300收盘低于60日均线时，目标总仓位降至30%。" in text

    # enabled=False 应归零为 None
    disabled = RuleStrategyDefinition.from_mapping(
        _base_definition(market_timing={"enabled": False, "benchmark": "000300.SH", "ma_window": 60, "off_weight": 0.0})
    )
    assert disabled.market_timing is None

    # RuleBasedStrategy 属性透传
    strategy = RuleBasedStrategy.from_parameters("s1", {"definition_json": restored.to_json()})
    assert strategy.hold_buffer == 10
    assert strategy.market_timing == MarketTimingSpec("000300.SH", 60, 0.3)


@pytest.mark.parametrize(
    "override",
    [
        {"hold_buffer": -1},
        {"hold_buffer": 101},
        {"hold_buffer": True},
        {"market_timing": {"benchmark": "999999.SH", "ma_window": 60, "off_weight": 0.0}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": 4, "off_weight": 0.0}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": 251, "off_weight": 0.0}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": True, "off_weight": 0.0}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": 60, "off_weight": -0.1}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": 60, "off_weight": 1.0}},
        {"market_timing": {"benchmark": "000300.SH", "ma_window": 60, "off_weight": False}},
    ],
)
def test_rule_schema_rejects_invalid_buffer_or_timing(override):
    with pytest.raises(ConfigurationError):
        RuleStrategyDefinition.from_mapping(_base_definition(**override))


# --------------------------------------------------------------------------- #
# 2. Portfolio 排名缓冲选股逻辑
# --------------------------------------------------------------------------- #


def test_equal_weight_and_risk_weighted_portfolio_honor_hold_buffer():
    day = date(2025, 3, 3)
    signals = [
        Signal("s", day, "000001.SZ", "SCORE", 5.0),
        Signal("s", day, "000002.SZ", "SCORE", 4.0),
        Signal("s", day, "000003.SZ", "SCORE", 3.0),
        Signal("s", day, "000004.SZ", "SCORE", 2.0),
        Signal("s", day, "000005.SZ", "SCORE", 1.0),
    ]
    portfolio = EqualWeightPortfolio(top_n=2)

    # 无缓冲：直接取前 2
    plain = [t.symbol for t in portfolio.construct(signals, held_symbols={"000003.SZ", "000005.SZ"}, hold_buffer=0)]
    assert plain == ["000001.SZ", "000002.SZ"]

    # buffer=2：前 4 名内已持股 000003.SZ 保留；第 5 名的 000005.SZ 跌出前 4 名被卖出，补入第 1 名 000001.SZ
    buffered = portfolio.construct(signals, held_symbols={"000003.SZ", "000005.SZ"}, hold_buffer=2)
    assert [t.symbol for t in buffered] == ["000001.SZ", "000003.SZ"]
    assert all(t.target_weight == pytest.approx(0.5) for t in buffered)

    # 已持股不在 signals 里（不再满足买入条件），即使开了缓冲也必须退出
    missing_held = portfolio.construct(signals, held_symbols={"999999.SZ"}, hold_buffer=5)
    assert [t.symbol for t in missing_held] == ["000001.SZ", "000002.SZ"]

    # RiskWeightedPortfolio 同样透传 hold_buffer
    dates = _trading_days(date(2025, 1, 2), 30)
    rng = np.random.default_rng(7)
    rows = []
    for sym_idx, symbol in enumerate([s.symbol for s in signals]):
        prices = 10.0 * np.cumprod(1.0 + rng.normal(0.001, 0.01 + sym_idx * 0.002, len(dates)))
        for d, p in zip(dates, prices, strict=True):
            rows.append({"symbol": symbol, "trade_date": pd.Timestamp(d), "adjusted_close": float(p)})
    history = pd.DataFrame(rows)
    rw = RiskWeightedPortfolio(top_n=2, method="inverse_volatility", lookback=25)
    rw_targets = rw.construct_with_history(
        [Signal("s", dates[-1], s.symbol, "SCORE", s.score) for s in signals],
        history,
        held_symbols={"000003.SZ", "000005.SZ"},
        hold_buffer=2,
    )
    assert [t.symbol for t in rw_targets] == ["000001.SZ", "000003.SZ"]
    assert sum(t.target_weight for t in rw_targets) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# 3. BacktestEngine 端到端：防换手缓冲降换手 + 大盘择时降仓/清仓
# --------------------------------------------------------------------------- #


def _build_engine(repo, strategy, *, top_n: int = 2, rebalance: str = "daily") -> BacktestEngine:
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


def test_engine_hold_buffer_reduces_churn_and_records_summary():
    days = _trading_days(date(2025, 2, 3), 8)
    symbols = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
    bars = _make_bars(days, symbols)
    repo = _MemoryRepository(bars)

    # 每天 4 只股票在 2/3 名之间微弱交替：无缓冲会天天换股，有 buffer=2 会稳定持有最初 2 只
    scores_by_date: dict[date, dict[str, float]] = {}
    for idx, day in enumerate(days):
        if idx % 2 == 0:
            scores_by_date[day] = {"000001.SZ": 4.0, "000002.SZ": 3.0, "000003.SZ": 2.0, "000004.SZ": 1.0}
        else:
            scores_by_date[day] = {"000003.SZ": 4.0, "000004.SZ": 3.0, "000001.SZ": 2.0, "000002.SZ": 1.0}

    plain_run = _build_engine(repo, _ScriptedScoreStrategy(scores_by_date, hold_buffer=0)).run(
        days[0], days[-1], initial_cash=1_000_000.0
    )
    buffered_run = _build_engine(repo, _ScriptedScoreStrategy(scores_by_date, hold_buffer=2)).run(
        days[0], days[-1], initial_cash=1_000_000.0
    )

    assert len(buffered_run.fills) < len(plain_run.fills)
    assert set(plain_run.fills["symbol"]) == set(symbols)
    assert set(buffered_run.fills["symbol"]) == {"000001.SZ", "000002.SZ"}
    assert buffered_run.summary["total_transaction_cost"] < plain_run.summary["total_transaction_cost"]
    assert buffered_run.summary["hold_buffer"] == 2
    assert "hold_buffer" not in plain_run.summary


@pytest.mark.parametrize("off_weight,expected_weight", [(0.0, 0.0), (0.3, 0.3)])
def test_engine_market_timing_scales_or_clears_targets_and_logs_events(off_weight, expected_weight):
    # 10 天预热基准 + 6 天回测期：前 3 天在均线上方，后 3 天暴跌到均线下方
    all_days = _trading_days(date(2025, 1, 2), 16)
    bt_days = all_days[10:]
    symbols = ["000001.SZ", "000002.SZ"]
    bars = _make_bars(bt_days, symbols)

    bench_prices = [3500.0] * 10 + [3600.0, 3620.0, 3650.0, 3100.0, 3050.0, 3000.0]
    benchmark_bars = pd.DataFrame(
        {
            "symbol": ["000300.SH"] * len(all_days),
            "trade_date": [pd.Timestamp(d) for d in all_days],
            "raw_close": bench_prices,
        }
    )
    repo = _MemoryRepository(bars, benchmark_bars)
    scores_by_date = {day: {"000001.SZ": 2.0, "000002.SZ": 1.0} for day in bt_days}
    timing = MarketTimingSpec(benchmark="000300.SH", ma_window=5, off_weight=off_weight)

    result = _build_engine(repo, _ScriptedScoreStrategy(scores_by_date, market_timing=timing)).run(
        bt_days[0], bt_days[-1], initial_cash=1_000_000.0
    )

    # bt_days[3] 和 bt_days[4] 是回测期倒数第 3、2 个调仓日（最后一天 bt_days[5] 不调仓），均低于 5 日均线
    timing_events = result.risk_events[result.risk_events["event_type"] == "MARKET_TIMING"]
    assert len(timing_events) == 2
    assert result.summary["market_timing"] == timing.to_dict()
    assert result.summary["market_timing_triggers"] == 2
    assert all(w == pytest.approx(expected_weight) for w in timing_events["total_weight"])

    # 适配器透传给前端
    adapted = backtest_run_to_result(SimpleNamespace(result=result, output_dir=Path("runs/test")))
    assert adapted["market_timing"] == timing.to_dict()
    assert adapted["market_timing_triggers"] == 2


def test_engine_market_timing_raises_when_benchmark_missing():
    days = _trading_days(date(2025, 2, 3), 5)
    repo = _MemoryRepository(_make_bars(days, ["000001.SZ"]))
    scores_by_date = {day: {"000001.SZ": 1.0} for day in days}
    timing = MarketTimingSpec(benchmark="000300.SH", ma_window=5, off_weight=0.0)
    engine = _build_engine(repo, _ScriptedScoreStrategy(scores_by_date, market_timing=timing), top_n=1)
    with pytest.raises(BacktestValidityError, match="000300.SH"):
        engine.run(days[0], days[-1], initial_cash=1_000_000.0)


# --------------------------------------------------------------------------- #
# 4. API 路由往返：options / preflight / create / template_modified / backtest
# --------------------------------------------------------------------------- #


def test_studio_api_roundtrips_buffer_and_timing_and_detects_template_edit(workflow):
    client, _, captured, *_ = workflow

    opts = client.get("/api/v1/studio/options")
    assert opts.status_code == 200
    benchmarks = opts.json()["market_timing_benchmarks"]
    assert any(item["value"] == "000300.SH" for item in benchmarks)

    template = beginner_templates()[0]
    preset = template.presets["balanced"]
    # 基于模板加上防换手缓冲与大盘择时
    definition = {
        "name": f"{template.name}-保护版",
        "entry_logic": preset.definition.entry_logic,
        "entry_rules": [
            {"left": {"name": "close"}, "operator": "gt", "value": 0.0},
        ],
        "ranking": {"indicator": {"name": "return_1d", "window": 20}, "direction": "descending"},
        "hold_buffer": 10,
        "market_timing": {"benchmark": "000300.SH", "ma_window": 60, "off_weight": 0.3},
    }

    preflight = client.post(
        "/api/v1/packages/preflight",
        json={"definition": definition, "top_n": 5, "rebalance": "weekly", "source": "visual_builder"},
    )
    assert preflight.status_code == 200, preflight.text
    desc = preflight.json()["description"]
    assert "防频繁换手" in desc
    assert "大盘择时" in desc

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
    assert pkg["definition"]["hold_buffer"] == 10
    assert pkg["definition"]["market_timing"] == {"benchmark": "000300.SH", "ma_window": 60, "off_weight": 0.3}

    # 提交回测时 definition_json 完整携带这两个配置
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
    assert sent_def["hold_buffer"] == 10
    assert sent_def["market_timing"] == {"benchmark": "000300.SH", "ma_window": 60, "off_weight": 0.3}

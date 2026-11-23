"""Tests for industry cap backfill, factor composite backtest neutralization, and backtest cost/filter overrides."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from app.routes.backtests import (
    ExecutionOverridesIn,
    FilterOverridesIn,
    apply_backtest_overrides,
    extract_snapshot_assumptions,
)
from quant_platform.portfolio.equal_weight import EqualWeightPortfolio
from quant_platform.signals.models import Signal
from quant_platform.strategies.context import StrategyContext
from quant_platform.strategies.factor_composite import FactorCompositeParameters, FactorCompositeStrategy
from test_research_integrity import api  # noqa: F401 - pytest fixture


def _sig(symbol: str, score: float) -> Signal:
    return Signal(
        strategy_id="s1",
        trade_date=date(2025, 1, 2),
        symbol=symbol,
        signal_type="FACTOR_COMPOSITE_SCORE",
        score=score,
        model_version="v1",
    )


def test_equal_weight_portfolio_caps_industry_and_backfills_other_industries():
    # 前 6 名全是银行，后 4 名分别是电子/医药/食品/电力；top_n=4，单一行业上限 25% -> 每行业最多 1 只
    signals = [
        _sig("B1", 10.0), _sig("B2", 9.0), _sig("B3", 8.0),
        _sig("B4", 7.0), _sig("B5", 6.0), _sig("B6", 5.0),
        _sig("E1", 4.0), _sig("M1", 3.0), _sig("F1", 2.0), _sig("P1", 1.0),
    ]
    industry_map = {
        "B1": "银行", "B2": "银行", "B3": "银行", "B4": "银行", "B5": "银行", "B6": "银行",
        "E1": "电子", "M1": "医药", "F1": "食品", "P1": "电力",
    }
    portfolio = EqualWeightPortfolio(top_n=4)
    targets = portfolio.construct(signals, max_industry_weight=0.25, industry_map=industry_map)
    symbols = [t.symbol for t in targets]
    assert symbols == ["B1", "E1", "M1", "F1"]
    assert all(t.target_weight == pytest.approx(0.25) for t in targets)

    # 上限 50% 时每行业最多 2 只 -> 选 B1, B2 加上 E1, M1
    targets_50 = portfolio.construct(signals, max_industry_weight=0.50, industry_map=industry_map)
    assert [t.symbol for t in targets_50] == ["B1", "B2", "E1", "M1"]


def test_factor_composite_strategy_supports_industry_rank_and_size_neutralization():
    # 构造 4 只股票（2 银行 + 2 电子），银行动量整体高于电子，但在各自行业内 B1 > B2、E1 > E2
    days = pd.bdate_range("2025-01-02", periods=25)
    rows = []
    slopes = {"B1": 0.012, "B2": 0.010, "E1": 0.004, "E2": 0.001}
    for sym, slope in slopes.items():
        price = 10.0
        for d in days:
            price *= (1.0 + slope)
            rows.append({"symbol": sym, "trade_date": d, "adjusted_close": price, "raw_close": price})
    history = pd.DataFrame(rows)
    industry_map = {"B1": "银行", "B2": "银行", "E1": "电子", "E2": "电子"}
    market_caps = {"B1": 5e11, "B2": 4e11, "E1": 2e10, "E2": 1e10}

    context = StrategyContext.create(
        days[-1].date(),
        history,
        list(slopes.keys()),
        industry_map=industry_map,
        market_caps=market_caps,
    )

    # 不中性化：前 2 名全是银行（B1, B2）
    plain_json = json.dumps([{"name": "momentum_20", "weight": 1.0, "direction": 1, "neutralization": "none"}])
    plain = FactorCompositeStrategy.from_parameters("fc_plain", {"factors_json": plain_json})
    assert plain.needs_market_cap is False
    plain_top2 = [s.symbol for s in plain.generate_signals(context)[:2]]
    assert plain_top2 == ["B1", "B2"]

    # 行业内排名中性化：银行第 1（B1）与电子第 1（E1）并列最高，不再集中于银行！
    ind_json = json.dumps([{"name": "momentum_20", "weight": 1.0, "direction": 1, "neutralization": "industry_rank"}])
    ind_params = FactorCompositeParameters.from_json(ind_json)
    assert ind_params.neutralization == "industry_rank"
    assert '"neutralization": "industry_rank"' in ind_params.to_json()
    ind_strategy = FactorCompositeStrategy.from_parameters("fc_ind", {"factors_json": ind_json})
    ind_top2 = set(s.symbol for s in ind_strategy.generate_signals(context)[:2])
    assert ind_top2 == {"B1", "E1"}

    # 市值中性化声明 needs_market_cap=True 并能正常产生信号
    size_json = json.dumps([{"name": "momentum_20", "weight": 1.0, "direction": 1, "neutralization": "size"}])
    size_strategy = FactorCompositeStrategy.from_parameters("fc_size", {"factors_json": size_json})
    assert size_strategy.needs_market_cap is True
    assert len(size_strategy.generate_signals(context)) == 4


def test_risk_api_persists_max_industry_weight_and_validates(api):  # noqa: F811
    client, _, _ = api
    default_risk = client.get("/api/v1/risk").json()
    assert default_risk["max_industry_weight"] == 1.0

    bad = client.put("/api/v1/risk", json={**default_risk, "max_industry_weight": 1.5})
    assert bad.status_code == 422

    ok = client.put("/api/v1/risk", json={**default_risk, "max_industry_weight": 0.25})
    assert ok.status_code == 200
    assert client.get("/api/v1/risk").json()["max_industry_weight"] == pytest.approx(0.25)


def test_backtest_overrides_and_snapshot_assumptions_extraction(tmp_path: Path):
    service = SimpleNamespace(
        configs={
            "execution": {"execution": {"commission_rate": 0.0003, "minimum_commission": 5.0, "historical_fees": True, "stamp_tax_rate": 0.0005, "slippage_rate": 0.0005}},
            "universe": {"universe": {"filters": {"exclude_st": True, "exclude_suspended": True, "minimum_listing_days": 60, "minimum_history_days": 120, "minimum_average_amount": 0.0}}},
        }
    )
    eff_exec, eff_filters = apply_backtest_overrides(
        service,
        ExecutionOverridesIn(commission_rate=0.00015, slippage_rate=0.001, historical_fees=False, stamp_tax_rate=0.0005),
        FilterOverridesIn(minimum_listing_days=250, exclude_st=True),
    )
    assert eff_exec["commission_rate"] == pytest.approx(0.00015)
    assert eff_exec["slippage_rate"] == pytest.approx(0.001)
    assert eff_exec["historical_fees"] is False
    assert eff_filters["minimum_listing_days"] == 250
    assert eff_filters["reject_limit_moves"] is True

    # 从持久化 config.snapshot.yaml 回读旧回测费率与过滤假设
    run_dir = tmp_path / "run_old"
    run_dir.mkdir()
    (run_dir / "config.snapshot.yaml").write_text(
        yaml.safe_dump(service.configs, allow_unicode=True),
        encoding="utf-8",
    )
    snap_exec, snap_filters = extract_snapshot_assumptions(run_dir)
    assert snap_exec is not None and snap_exec["commission_rate"] == pytest.approx(0.00015)
    assert snap_filters is not None and snap_filters["minimum_listing_days"] == 250
